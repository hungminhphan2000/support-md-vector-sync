#!/usr/bin/env python3
"""Scraper-uploader job: refresh Help Center articles into an OpenAI vector store."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.articles import (
    REQUIRED_ARTICLE_ID,
    ArticleFetchError,
    fetch_article_by_id,
    fetch_published_articles,
)
from src.normalize import article_to_markdown
from src.vector_store import (
    DeltaDecision,
    DeltaKind,
    LocalArticle,
    StoredFile,
    VectorStoreError,
    api_key,
    content_digest,
    decide_deltas,
    delete_store_file,
    get_store,
    list_stored_files,
    load_dotenv,
    request_json,
    require_vector_store_id,
    upload_and_attach,
)

POLL_SECONDS = 900


@dataclass(frozen=True)
class RefreshCollection:
    """Published articles ready for delta decisions, plus ids skipped on fetch."""

    articles: tuple[LocalArticle, ...]
    fetched_by_id: tuple[int, ...]
    skipped_ids: tuple[int, ...]


@dataclass(frozen=True)
class JobResult:
    added: int
    updated: int
    skipped: int
    failed: int
    removed_old: int
    file_counts: dict[str, int]


def article_ids_from_stored(stored: Iterable[StoredFile]) -> set[int]:
    """Return every article id already present in the vector-store file list."""
    return {item.article_id for item in stored}


def _to_local_article(article: dict[str, Any], markdown: str) -> LocalArticle:
    article_id = int(article["id"])
    content = markdown.encode("utf-8")
    return LocalArticle(
        article_id=article_id,
        path=Path(f"{article_id}.md"),
        content=content,
        digest=content_digest(content),
    )


def collect_refresh_articles(
    stored_ids: Iterable[int],
    *,
    fetch_page: Callable[..., list[dict[str, Any]]] = fetch_published_articles,
    fetch_by_id: Callable[..., dict[str, Any]] = fetch_article_by_id,
    to_markdown: Callable[[dict[str, Any]], str] = article_to_markdown,
    required_article_id: int = REQUIRED_ARTICLE_ID,
) -> RefreshCollection:
    """
    Build the refresh set for one job run.

    1. Fetch the current page (and required backfill when the page omits it).
    2. Union page ids with every id already in the vector store (and the required id).
    3. GET ``/articles/{id}.json`` for any refresh-set id missing from the page payload.
    4. Convert valid published articles to Markdown ``LocalArticle`` records.

    Unpublished, missing, or invalid single-article responses are logged and skipped.
    """
    page_articles = fetch_page()
    by_id: dict[int, dict[str, Any]] = {
        int(article["id"]): article for article in page_articles
    }
    page_ids = set(by_id)

    refresh_ids = page_ids | set(stored_ids) | {required_article_id}
    missing_ids = sorted(refresh_ids - page_ids)

    fetched_by_id: list[int] = []
    skipped_ids: list[int] = []

    for article_id in missing_ids:
        try:
            article = fetch_by_id(article_id)
        except (ArticleFetchError, ValueError, TypeError) as exc:
            skipped_ids.append(article_id)
            print(
                f"skip article_id={article_id} reason={exc}",
                file=sys.stderr,
            )
            continue
        by_id[article_id] = article
        fetched_by_id.append(article_id)

    locals_: list[LocalArticle] = []
    for article_id in sorted(by_id):
        article = by_id[article_id]
        try:
            markdown = to_markdown(article)
        except (ValueError, TypeError) as exc:
            skipped_ids.append(article_id)
            print(
                f"skip article_id={article_id} reason={exc}",
                file=sys.stderr,
            )
            continue
        locals_.append(_to_local_article(article, markdown))

    return RefreshCollection(
        articles=tuple(locals_),
        fetched_by_id=tuple(fetched_by_id),
        skipped_ids=tuple(skipped_ids),
    )


def _file_counts(store: dict[str, Any]) -> dict[str, int]:
    raw = store.get("file_counts")
    if not isinstance(raw, dict):
        return {}
    counts: dict[str, int] = {}
    for key in ("completed", "in_progress", "failed", "cancelled", "total"):
        value = raw.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            counts[key] = value
    return counts


def _counts_as_update(decision: DeltaDecision) -> bool:
    return decision.kind is DeltaKind.CHANGED or bool(decision.old_file_ids)


def _delete_old_files(
    key: str,
    store_id: str,
    file_ids: Iterable[str],
    *,
    delete_file: Callable[..., None] = delete_store_file,
) -> int:
    removed = 0
    for file_id in file_ids:
        delete_file(key, store_id, file_id)
        removed += 1
        print(f"removed_old file_id={file_id}")
    return removed


def _retrieve_store_file(
    key: str,
    store_id: str,
    file_id: str,
    *,
    request: Callable[..., Any] = request_json,
) -> dict[str, Any]:
    result = request("GET", f"/vector_stores/{store_id}/files/{file_id}", key)
    if not isinstance(result, dict):
        raise VectorStoreError(
            f"Vector store file {file_id} response was not an object."
        )
    return result


def apply_delta_decisions(
    key: str,
    store_id: str,
    decisions: list[DeltaDecision],
    *,
    upload: Callable[..., str] = upload_and_attach,
    retrieve: Callable[..., dict[str, Any]] = _retrieve_store_file,
    delete_file: Callable[..., None] = delete_store_file,
    sleep: Callable[[float], None] = time.sleep,
    poll_timeout: float = POLL_SECONDS,
) -> tuple[int, int, int, int, int]:
    """
    Apply delta decisions: upload/poll/retry, then delete replaced files.

    Returns ``(added, updated, skipped, failed, removed_old)``.
    Old completed files are removed only after a replacement reaches ``completed``.
    """
    added = 0
    updated = 0
    skipped = 0
    failed = 0
    removed_old = 0
    pending: list[tuple[DeltaDecision, str]] = []

    for decision in decisions:
        article = decision.article
        if decision.kind is DeltaKind.UNCHANGED:
            skipped += 1
            removed_old += _delete_old_files(
                key, store_id, decision.old_file_ids, delete_file=delete_file
            )
            continue

        if decision.kind is DeltaKind.IN_PROGRESS:
            if decision.current_file_id is None:
                failed += 1
                print(
                    f"failed article_id={article.article_id}: "
                    "in_progress decision missing file id",
                    file=sys.stderr,
                )
                continue
            pending.append((decision, decision.current_file_id))
            continue

        if decision.kind is DeltaKind.FAILED and decision.current_file_id:
            try:
                delete_file(key, store_id, decision.current_file_id)
            except VectorStoreError as exc:
                failed += 1
                print(
                    f"failed article_id={article.article_id}: "
                    f"could not delete failed file: {exc}",
                    file=sys.stderr,
                )
                continue

        try:
            file_id = upload(key, store_id, article)
        except VectorStoreError as exc:
            failed += 1
            print(f"failed article_id={article.article_id}: {exc}", file=sys.stderr)
            continue
        pending.append((decision, file_id))

    remaining = {file_id: decision for decision, file_id in pending}
    deadline = time.monotonic() + poll_timeout

    while remaining and time.monotonic() < deadline:
        finished: list[str] = []
        for file_id, decision in remaining.items():
            result = retrieve(key, store_id, file_id)
            status = result.get("status")
            if status not in {"completed", "failed", "cancelled"}:
                continue
            finished.append(file_id)
            article_id = decision.article.article_id
            if status == "completed":
                if _counts_as_update(decision):
                    updated += 1
                else:
                    added += 1
                removed_old += _delete_old_files(
                    key,
                    store_id,
                    decision.old_file_ids,
                    delete_file=delete_file,
                )
            else:
                failed += 1
                print(
                    f"failed article_id={article_id} file_id={file_id} status={status!r}",
                    file=sys.stderr,
                )
        for file_id in finished:
            del remaining[file_id]
        if remaining:
            sleep(2)

    for file_id, decision in remaining.items():
        failed += 1
        print(
            f"failed article_id={decision.article.article_id} "
            f"file_id={file_id} status='timed_out'",
            file=sys.stderr,
        )

    return added, updated, skipped, failed, removed_old


def run_job(
    *,
    list_files: Callable[..., list[StoredFile]] = list_stored_files,
    collect: Callable[..., RefreshCollection] = collect_refresh_articles,
    get_store_fn: Callable[..., dict[str, Any]] = get_store,
    upload: Callable[..., str] = upload_and_attach,
    retrieve: Callable[..., dict[str, Any]] = _retrieve_store_file,
    delete_file: Callable[..., None] = delete_store_file,
    sleep: Callable[[float], None] = time.sleep,
    poll_timeout: float = POLL_SECONDS,
) -> JobResult:
    load_dotenv()
    key = api_key()
    store_id = require_vector_store_id()

    stored = list_files(key, store_id)
    collection = collect(article_ids_from_stored(stored))
    decisions = decide_deltas(list(collection.articles), stored)

    if collection.fetched_by_id:
        print(
            "fetched_by_id="
            + ",".join(str(article_id) for article_id in collection.fetched_by_id)
        )

    added, updated, skipped, failed, removed_old = apply_delta_decisions(
        key,
        store_id,
        decisions,
        upload=upload,
        retrieve=retrieve,
        delete_file=delete_file,
        sleep=sleep,
        poll_timeout=poll_timeout,
    )

    store = get_store_fn(key, store_id)
    counts = _file_counts(store)

    print(f"vector_store_id={store_id}")
    print(f"refresh_articles={len(collection.articles)}")
    print(f"added={added}")
    print(f"updated={updated}")
    print(f"skipped={skipped}")
    print(f"failed={failed}")
    print(f"removed_old={removed_old}")
    print(f"completed_file_count={counts.get('completed', 0)}")
    print(f"in_progress_file_count={counts.get('in_progress', 0)}")
    print(f"failed_file_count={counts.get('failed', 0)}")
    print(f"total_file_count={counts.get('total', 0)}")
    print("indexed_chunk_count_field=absent")

    return JobResult(
        added=added,
        updated=updated,
        skipped=skipped,
        failed=failed,
        removed_old=removed_old,
        file_counts=counts,
    )


def main() -> int:
    try:
        result = run_job()
    except VectorStoreError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if result.failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

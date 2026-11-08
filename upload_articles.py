#!/usr/bin/env python3
"""Upload local Markdown articles into an existing OpenAI vector store."""

from __future__ import annotations

import sys
import time
from typing import Any

from src.vector_store import (
    LocalArticle,
    VectorStoreError,
    api_key,
    get_store,
    list_stored_files,
    load_dotenv,
    load_local_articles,
    plan_uploads,
    request_json,
    require_vector_store_id,
    upload_and_attach,
)

BATCH_POLL_SECONDS = 900


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


def _poll_pending(
    key: str,
    store_id: str,
    pending: list[tuple[LocalArticle, str]],
    *,
    timeout: float = BATCH_POLL_SECONDS,
) -> tuple[int, int]:
    """Poll every newly attached file until it leaves in_progress."""
    remaining = {file_id: article for article, file_id in pending}
    added = 0
    failed = 0
    deadline = time.monotonic() + timeout

    while remaining and time.monotonic() < deadline:
        finished: list[str] = []
        for file_id, article in remaining.items():
            result = request_json(
                "GET",
                f"/vector_stores/{store_id}/files/{file_id}",
                key,
            )
            if not isinstance(result, dict):
                raise VectorStoreError(
                    f"Vector store file {file_id} response was not an object."
                )
            status = result.get("status")
            if status not in {"completed", "failed", "cancelled"}:
                continue
            finished.append(file_id)
            if status == "completed":
                added += 1
            else:
                failed += 1
                print(
                    f"failed article_id={article.article_id} "
                    f"file_id={file_id} status={status!r}",
                    file=sys.stderr,
                )
        for file_id in finished:
            del remaining[file_id]
        if remaining:
            time.sleep(2)

    for file_id, article in remaining.items():
        failed += 1
        print(
            f"failed article_id={article.article_id} file_id={file_id} status='timed_out'",
            file=sys.stderr,
        )
    return added, failed


def run_upload() -> int:
    load_dotenv()
    key = api_key()
    store_id = require_vector_store_id()
    locals_ = load_local_articles()
    if not locals_:
        raise VectorStoreError("No Markdown articles found under data/articles/.")

    stored = list_stored_files(key, store_id)
    plan = plan_uploads(locals_, stored)

    failed = 0
    pending: list[tuple[LocalArticle, str]] = list(plan.to_poll)

    for article in plan.to_upload:
        try:
            file_id = upload_and_attach(key, store_id, article)
            pending.append((article, file_id))
        except VectorStoreError as exc:
            failed += 1
            print(f"failed article_id={article.article_id}: {exc}", file=sys.stderr)

    added, poll_failed = _poll_pending(key, store_id, pending)
    failed += poll_failed

    store = get_store(key, store_id)
    counts = _file_counts(store)

    print(f"vector_store_id={store_id}")
    print(f"local_articles={len(locals_)}")
    print(f"added={added}")
    print(f"skipped={len(plan.skipped)}")
    print(f"failed={failed}")
    print(f"completed_file_count={counts.get('completed', 0)}")
    print(f"in_progress_file_count={counts.get('in_progress', 0)}")
    print(f"failed_file_count={counts.get('failed', 0)}")
    print(f"total_file_count={counts.get('total', 0)}")
    print("indexed_chunk_count_field=absent")

    if failed:
        return 1
    if counts.get("completed", 0) < 30:
        return 1
    return 0


def main() -> int:
    try:
        return run_upload()
    except VectorStoreError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

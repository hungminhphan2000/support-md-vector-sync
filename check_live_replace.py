#!/usr/bin/env python3
"""Isolated live check: replace one article file using the real delta path.

Creates a temporary vector store, uploads a tiny version A, replaces it with
version B via ``decide_deltas`` + ``apply_delta_decisions``, asserts the old
file remains until B is ``completed`` and is removed afterward, then deletes
the temporary store and uploaded Files objects.

``VECTOR_STORE_ID`` is ignored (popped after ``.env`` load) so the production
store is never used. Only ``API_KEY`` / ``OPENAI_API_KEY`` (and optional ``.env``
for the key) are used. Any temp-store or uploaded-File cleanup failure exits
non-zero; ``cleanup_status=ok`` prints only after every cleanup step succeeds.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from main import apply_delta_decisions
from src.vector_store import (
    LocalArticle,
    StoredFile,
    VectorStoreError,
    api_key,
    content_digest,
    decide_deltas,
    delete_store_file,
    list_stored_files,
    load_dotenv,
    request_json,
    upload_and_attach,
)

ARTICLE_ID = 1
POLL_SECONDS = 180
FINAL_SETTLE_SECONDS = 60
STORE_NAME = "optibot-live-replace-check"


def _local(article_id: int, markdown: str) -> LocalArticle:
    content = markdown.encode("utf-8")
    return LocalArticle(
        article_id=article_id,
        path=Path(f"{article_id}.md"),
        content=content,
        digest=content_digest(content),
    )


def _create_store(key: str) -> str:
    store = request_json(
        "POST",
        "/vector_stores",
        key,
        payload={"name": STORE_NAME},
    )
    if not isinstance(store, dict):
        raise VectorStoreError("Vector store create response was not an object.")
    store_id = str(store.get("id", ""))
    if not store_id.startswith("vs_"):
        raise VectorStoreError("Temporary vector store response did not include an id.")
    return store_id


def _delete_store(key: str, store_id: str) -> None:
    request_json("DELETE", f"/vector_stores/{store_id}", key)


def _delete_file_object(key: str, file_id: str) -> None:
    request_json("DELETE", f"/files/{file_id}", key)


def _retrieve_store_file(key: str, store_id: str, file_id: str) -> dict[str, Any]:
    result = request_json("GET", f"/vector_stores/{store_id}/files/{file_id}", key)
    if not isinstance(result, dict):
        raise VectorStoreError(
            f"Vector store file {file_id} response was not an object."
        )
    return result


def _filenames_for_article(key: str, store_id: str, article_id: int) -> set[str]:
    return {
        item.filename
        for item in list_stored_files(key, store_id)
        if item.article_id == article_id
    }


def _completed_for_article(key: str, store_id: str, article_id: int) -> list[str]:
    return [
        item.filename
        for item in list_stored_files(key, store_id)
        if item.article_id == article_id and item.status == "completed"
    ]


def _format_article_files(items: list[StoredFile]) -> str:
    if not items:
        return "(none)"
    return ",".join(f"{item.filename}:{item.status}" for item in items)


def _wait_for_sole_completed(
    key: str,
    store_id: str,
    article_id: int,
    expected_filename: str,
    *,
    timeout: float = FINAL_SETTLE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Poll with one ``list_stored_files`` snapshot per attempt until only B remains."""
    deadline = time.monotonic() + timeout
    last_related: list[StoredFile] = []
    while True:
        snapshot = list_stored_files(key, store_id)
        last_related = [item for item in snapshot if item.article_id == article_id]
        print(f"final_poll_state={_format_article_files(last_related)}")
        if (
            len(last_related) == 1
            and last_related[0].filename == expected_filename
            and last_related[0].status == "completed"
        ):
            print(f"final_sole_completed_filename={expected_filename}")
            return
        if time.monotonic() >= deadline:
            raise VectorStoreError(
                "timed out waiting for sole completed "
                f"{expected_filename!r}; last_observed="
                f"{_format_article_files(last_related)}"
            )
        sleep(2)


def main() -> int:
    load_dotenv()
    # Refuse the production store even if .env exported it into this process.
    ignored = os.environ.pop("VECTOR_STORE_ID", None)
    print(f"ignored_env_VECTOR_STORE_ID={bool(ignored)}")

    key = api_key()
    article_a = _local(
        ARTICLE_ID,
        "# replace-check A\n\nArticle URL: https://example.com/a\n\nversion A\n",
    )
    article_b = _local(
        ARTICLE_ID,
        "# replace-check B\n\nArticle URL: https://example.com/b\n\nversion B\n",
    )
    if article_a.digest == article_b.digest:
        raise SystemExit("version A and B digests must differ.")

    store_id: str | None = None
    file_ids: set[str] = set()
    saw_both_while_b_completed = False
    exit_code = 1

    try:
        store_id = _create_store(key)
        print(f"temp_vector_store_id={store_id}")
        print(f"article_id={ARTICLE_ID}")
        print(f"version_a_filename={article_a.filename}")
        print(f"version_b_filename={article_b.filename}")

        decisions_a = decide_deltas([article_a], [])
        if decisions_a[0].kind.value != "new":
            raise VectorStoreError(
                f"expected NEW for empty store, got {decisions_a[0].kind.value}"
            )

        def track_upload(api_key_value: str, sid: str, article: LocalArticle) -> str:
            file_id = upload_and_attach(api_key_value, sid, article)
            file_ids.add(file_id)
            return file_id

        added, updated, skipped, failed, removed_old = apply_delta_decisions(
            key,
            store_id,
            decisions_a,
            upload=track_upload,
            retrieve=_retrieve_store_file,
            delete_file=delete_store_file,
            sleep=time.sleep,
            poll_timeout=POLL_SECONDS,
        )
        print(
            f"phase_a added={added} updated={updated} skipped={skipped} "
            f"failed={failed} removed_old={removed_old}"
        )
        if failed or added != 1:
            raise VectorStoreError("version A did not reach completed as added=1.")

        completed_a = _completed_for_article(key, store_id, ARTICLE_ID)
        if completed_a != [article_a.filename]:
            raise VectorStoreError(
                f"after A expected only {article_a.filename!r}, got {completed_a!r}"
            )
        print(f"phase_a_completed_filename={article_a.filename}")

        stored_after_a = list_stored_files(key, store_id)
        decisions_b = decide_deltas([article_b], stored_after_a)
        decision_b = decisions_b[0]
        if decision_b.kind.value != "changed":
            raise VectorStoreError(
                f"expected CHANGED for version B, got {decision_b.kind.value}"
            )
        if article_a.filename.split("-", 1)[0] != str(ARTICLE_ID):
            raise VectorStoreError("unexpected A filename shape")
        if not decision_b.old_file_ids:
            raise VectorStoreError("CHANGED decision missing old_file_ids.")
        print(f"phase_b_old_file_ids={','.join(decision_b.old_file_ids)}")

        def retrieve_and_assert(
            api_key_value: str, sid: str, file_id: str
        ) -> dict[str, Any]:
            nonlocal saw_both_while_b_completed
            result = _retrieve_store_file(api_key_value, sid, file_id)
            if result.get("status") == "completed" and not saw_both_while_b_completed:
                names = _filenames_for_article(api_key_value, sid, ARTICLE_ID)
                print(
                    "mid_replace_filenames="
                    + ",".join(sorted(names))
                )
                if article_a.filename not in names or article_b.filename not in names:
                    raise VectorStoreError(
                        "when B reached completed, both A and B filenames must "
                        f"still be listed; got {sorted(names)!r}"
                    )
                saw_both_while_b_completed = True
            return result

        added, updated, skipped, failed, removed_old = apply_delta_decisions(
            key,
            store_id,
            decisions_b,
            upload=track_upload,
            retrieve=retrieve_and_assert,
            delete_file=delete_store_file,
            sleep=time.sleep,
            poll_timeout=POLL_SECONDS,
        )
        print(
            f"phase_b added={added} updated={updated} skipped={skipped} "
            f"failed={failed} removed_old={removed_old}"
        )
        if failed or updated != 1 or removed_old < 1:
            raise VectorStoreError(
                "version B replace did not report updated=1 with removed_old>=1."
            )
        if not saw_both_while_b_completed:
            raise VectorStoreError(
                "never observed both A and B filenames while B was completed."
            )

        _wait_for_sole_completed(
            key,
            store_id,
            ARTICLE_ID,
            article_b.filename,
            timeout=FINAL_SETTLE_SECONDS,
            sleep=time.sleep,
        )

        print("replace_check=passed")
        exit_code = 0
    except VectorStoreError as exc:
        print(str(exc), file=sys.stderr)
        exit_code = 1
    finally:
        cleanup_ok = True
        if store_id is not None:
            try:
                for item in list_stored_files(key, store_id):
                    file_ids.add(item.file_id)
                    try:
                        delete_store_file(key, store_id, item.file_id)
                    except VectorStoreError as exc:
                        cleanup_ok = False
                        print(
                            f"cleanup_store_file_error file_id={item.file_id}: {exc}",
                            file=sys.stderr,
                        )
            except VectorStoreError as exc:
                cleanup_ok = False
                print(f"cleanup_list_error: {exc}", file=sys.stderr)
            try:
                _delete_store(key, store_id)
                print(f"temp_vector_store_deleted={store_id}")
            except VectorStoreError as exc:
                cleanup_ok = False
                print(f"cleanup_store_error: {exc}", file=sys.stderr)
        for file_id in sorted(file_ids):
            try:
                _delete_file_object(key, file_id)
                print(f"temp_file_deleted={file_id}")
            except VectorStoreError as exc:
                cleanup_ok = False
                print(f"cleanup_file_error file_id={file_id}: {exc}", file=sys.stderr)
        if cleanup_ok:
            print("cleanup_status=ok")
        else:
            print("cleanup_status=failed", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

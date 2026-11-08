"""Mocked tests for main.py delta apply, replace-delete, and counts."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from main import apply_delta_decisions, run_job
from src.vector_store import (
    LocalArticle,
    StoredFile,
    decide_delta,
    store_filename,
)


def _local(article_id: int, digest: str) -> LocalArticle:
    return LocalArticle(
        article_id=article_id,
        path=Path(f"{article_id}.md"),
        content=b"unused",
        digest=digest,
    )


def _stored(
    article_id: int,
    digest: str,
    *,
    status: str,
    file_id: str,
) -> StoredFile:
    return StoredFile(
        file_id=file_id,
        filename=store_filename(article_id, digest),
        article_id=article_id,
        digest=digest,
        status=status,
    )


class ApplyDeltaDecisionsTests(unittest.TestCase):
    def test_new_upload_counts_added_after_poll(self) -> None:
        article = _local(1, "aaaaaaaaaaaaaaaa")
        decision = decide_delta(article, [])
        deleted: list[str] = []
        calls = {"n": 0}

        def upload(key: str, store_id: str, item: LocalArticle) -> str:
            self.assertEqual(item.article_id, 1)
            return "file_new"

        def retrieve(key: str, store_id: str, file_id: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"status": "in_progress"}
            return {"status": "completed"}

        def delete_file(key: str, store_id: str, file_id: str) -> None:
            deleted.append(file_id)

        sleeps: list[float] = []
        added, updated, skipped, failed, removed_old = apply_delta_decisions(
            "key",
            "vs_test",
            [decision],
            upload=upload,
            retrieve=retrieve,
            delete_file=delete_file,
            sleep=sleeps.append,
            poll_timeout=30,
        )
        self.assertEqual((added, updated, skipped, failed, removed_old), (1, 0, 0, 0, 0))
        self.assertEqual(deleted, [])
        self.assertEqual(sleeps, [2])

    def test_changed_deletes_old_only_after_replacement_completes(self) -> None:
        article = _local(5, "neweeeeeeeeeeee")
        decision = decide_delta(
            article,
            [_stored(5, "oldoldoldoldold0", status="completed", file_id="file_old")],
        )
        deleted: list[str] = []
        order: list[str] = []

        def upload(key: str, store_id: str, item: LocalArticle) -> str:
            order.append("upload")
            return "file_new"

        def retrieve(key: str, store_id: str, file_id: str) -> dict:
            order.append(f"retrieve:{file_id}")
            return {"status": "completed"}

        def delete_file(key: str, store_id: str, file_id: str) -> None:
            order.append(f"delete:{file_id}")
            deleted.append(file_id)

        added, updated, skipped, failed, removed_old = apply_delta_decisions(
            "key",
            "vs_test",
            [decision],
            upload=upload,
            retrieve=retrieve,
            delete_file=delete_file,
            sleep=lambda _: None,
            poll_timeout=30,
        )
        self.assertEqual((added, updated, skipped, failed, removed_old), (0, 1, 0, 0, 1))
        self.assertEqual(deleted, ["file_old"])
        self.assertEqual(order, ["upload", "retrieve:file_new", "delete:file_old"])

    def test_failed_replacement_keeps_old_completed_file(self) -> None:
        article = _local(5, "neweeeeeeeeeeee")
        decision = decide_delta(
            article,
            [_stored(5, "oldoldoldoldold0", status="completed", file_id="file_old")],
        )
        deleted: list[str] = []

        def upload(key: str, store_id: str, item: LocalArticle) -> str:
            return "file_new"

        def retrieve(key: str, store_id: str, file_id: str) -> dict:
            return {"status": "failed"}

        def delete_file(key: str, store_id: str, file_id: str) -> None:
            deleted.append(file_id)

        added, updated, skipped, failed, removed_old = apply_delta_decisions(
            "key",
            "vs_test",
            [decision],
            upload=upload,
            retrieve=retrieve,
            delete_file=delete_file,
            sleep=lambda _: None,
            poll_timeout=30,
        )
        self.assertEqual((added, updated, skipped, failed, removed_old), (0, 0, 0, 1, 0))
        self.assertEqual(deleted, [])

    def test_unchanged_with_stale_old_files_skips_and_removes_old(self) -> None:
        article = _local(2, "bbbbbbbbbbbbbbbb")
        decision = decide_delta(
            article,
            [
                _stored(2, "bbbbbbbbbbbbbbbb", status="completed", file_id="file_ok"),
                _stored(2, "oldoldoldoldold0", status="completed", file_id="file_old"),
            ],
        )
        deleted: list[str] = []

        def upload(*args: object, **kwargs: object) -> str:
            raise AssertionError("unchanged must not upload")

        def delete_file(key: str, store_id: str, file_id: str) -> None:
            deleted.append(file_id)

        added, updated, skipped, failed, removed_old = apply_delta_decisions(
            "key",
            "vs_test",
            [decision],
            upload=upload,
            retrieve=lambda *a, **k: {"status": "completed"},
            delete_file=delete_file,
            sleep=lambda _: None,
        )
        self.assertEqual((added, updated, skipped, failed, removed_old), (0, 0, 1, 0, 1))
        self.assertEqual(deleted, ["file_old"])

    def test_failed_same_hash_deletes_failed_file_before_reupload(self) -> None:
        article = _local(4, "dddddddddddddddd")
        decision = decide_delta(
            article,
            [_stored(4, "dddddddddddddddd", status="failed", file_id="file_bad")],
        )
        deleted: list[str] = []
        order: list[str] = []

        def upload(key: str, store_id: str, item: LocalArticle) -> str:
            order.append("upload")
            return "file_retry"

        def retrieve(key: str, store_id: str, file_id: str) -> dict:
            return {"status": "completed"}

        def delete_file(key: str, store_id: str, file_id: str) -> None:
            order.append(f"delete:{file_id}")
            deleted.append(file_id)

        added, updated, skipped, failed, removed_old = apply_delta_decisions(
            "key",
            "vs_test",
            [decision],
            upload=upload,
            retrieve=retrieve,
            delete_file=delete_file,
            sleep=lambda _: None,
        )
        self.assertEqual((added, updated, skipped, failed, removed_old), (1, 0, 0, 0, 0))
        self.assertEqual(order, ["delete:file_bad", "upload"])
        self.assertEqual(deleted, ["file_bad"])


class RunJobTests(unittest.TestCase):
    def test_run_job_wires_list_collect_decide_and_logs_counts(self) -> None:
        article = _local(1, "aaaaaaaaaaaaaaaa")
        stored = [_stored(1, "aaaaaaaaaaaaaaaa", status="completed", file_id="file_ok")]

        def list_files(key: str, store_id: str) -> list[StoredFile]:
            return stored

        def collect(stored_ids: set[int]):
            from main import RefreshCollection

            self.assertEqual(stored_ids, {1})
            return RefreshCollection(
                articles=(article,),
                fetched_by_id=(),
                skipped_ids=(),
            )

        def get_store_fn(key: str, store_id: str) -> dict:
            return {
                "file_counts": {
                    "completed": 1,
                    "in_progress": 0,
                    "failed": 0,
                    "cancelled": 0,
                    "total": 1,
                }
            }

        with patch.dict(
            os.environ,
            {"API_KEY": "sk-test", "VECTOR_STORE_ID": "vs_test"},
            clear=False,
        ):
            result = run_job(
                list_files=list_files,
                collect=collect,
                get_store_fn=get_store_fn,
                upload=lambda *a, **k: (_ for _ in ()).throw(
                    AssertionError("should skip")
                ),
                retrieve=lambda *a, **k: {"status": "completed"},
                delete_file=lambda *a, **k: None,
                sleep=lambda _: None,
            )

        self.assertEqual(result.added, 0)
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.file_counts.get("completed"), 1)


if __name__ == "__main__":
    unittest.main()

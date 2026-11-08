"""Focused mocked tests for batch vector-store upload planning."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.vector_store import (
    LocalArticle,
    StoredFile,
    parse_store_filename,
    plan_uploads,
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
    status: str = "completed",
    file_id: str = "file_1",
) -> StoredFile:
    return StoredFile(
        file_id=file_id,
        filename=store_filename(article_id, digest),
        article_id=article_id,
        digest=digest,
        status=status,
    )


class ParseStoreFilenameTests(unittest.TestCase):
    def test_parses_id_and_digest(self) -> None:
        self.assertEqual(
            parse_store_filename("360051014713-599d0a98e6285548.md"),
            (360051014713, "599d0a98e6285548"),
        )

    def test_rejects_non_matching_names(self) -> None:
        self.assertIsNone(parse_store_filename("notes.md"))
        self.assertIsNone(parse_store_filename("360051014713.md"))


class PlanUploadsTests(unittest.TestCase):
    def test_skips_completed_same_hash(self) -> None:
        youtube = _local(360051014713, "599d0a98e6285548")
        other = _local(1, "aaaaaaaaaaaaaaaa")
        plan = plan_uploads(
            [youtube, other],
            [_stored(360051014713, "599d0a98e6285548", status="completed")],
        )
        self.assertEqual([item.article_id for item in plan.skipped], [360051014713])
        self.assertEqual(plan.to_poll, ())
        self.assertEqual([item.article_id for item in plan.to_upload], [1])

    def test_uploads_when_hash_changed(self) -> None:
        article = _local(10, "bbbbbbbbbbbbbbbb")
        plan = plan_uploads(
            [article],
            [_stored(10, "aaaaaaaaaaaaaaaa", status="completed")],
        )
        self.assertEqual(plan.skipped, ())
        self.assertEqual(plan.to_poll, ())
        self.assertEqual(plan.to_upload, (article,))

    def test_retries_failed_same_hash(self) -> None:
        article = _local(11, "cccccccccccccccc")
        plan = plan_uploads(
            [article],
            [_stored(11, "cccccccccccccccc", status="failed")],
        )
        self.assertEqual(plan.skipped, ())
        self.assertEqual(plan.to_poll, ())
        self.assertEqual(plan.to_upload, (article,))

    def test_uploads_new_article_id(self) -> None:
        article = _local(12, "dddddddddddddddd")
        plan = plan_uploads([article], [])
        self.assertEqual(plan.skipped, ())
        self.assertEqual(plan.to_poll, ())
        self.assertEqual(plan.to_upload, (article,))

    def test_restarted_run_polls_in_progress_skips_completed_retries_failed(self) -> None:
        completed = _local(1, "aaaaaaaaaaaaaaaa")
        in_progress = _local(2, "bbbbbbbbbbbbbbbb")
        failed = _local(3, "cccccccccccccccc")
        fresh = _local(4, "dddddddddddddddd")

        plan = plan_uploads(
            [completed, in_progress, failed, fresh],
            [
                _stored(1, "aaaaaaaaaaaaaaaa", status="completed", file_id="file_done"),
                _stored(2, "bbbbbbbbbbbbbbbb", status="in_progress", file_id="file_busy"),
                _stored(3, "cccccccccccccccc", status="failed", file_id="file_bad"),
            ],
        )

        self.assertEqual([item.article_id for item in plan.skipped], [1])
        self.assertEqual(
            [(article.article_id, file_id) for article, file_id in plan.to_poll],
            [(2, "file_busy")],
        )
        self.assertEqual([item.article_id for item in plan.to_upload], [3, 4])


if __name__ == "__main__":
    unittest.main()

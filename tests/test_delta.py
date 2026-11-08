"""Mocked tests for pure vector-store delta decisions."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.vector_store import (
    DeltaKind,
    LocalArticle,
    StoredFile,
    decide_delta,
    decide_deltas,
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


class DecideDeltaTests(unittest.TestCase):
    def test_new_when_id_absent(self) -> None:
        article = _local(1, "aaaaaaaaaaaaaaaa")
        decision = decide_delta(article, [])
        self.assertEqual(decision.kind, DeltaKind.NEW)
        self.assertIsNone(decision.current_file_id)
        self.assertEqual(decision.old_file_ids, ())

    def test_unchanged_when_completed_same_hash(self) -> None:
        article = _local(2, "bbbbbbbbbbbbbbbb")
        decision = decide_delta(
            article,
            [_stored(2, "bbbbbbbbbbbbbbbb", status="completed", file_id="file_ok")],
        )
        self.assertEqual(decision.kind, DeltaKind.UNCHANGED)
        self.assertEqual(decision.current_file_id, "file_ok")

    def test_in_progress_when_same_hash_still_indexing(self) -> None:
        article = _local(3, "cccccccccccccccc")
        decision = decide_delta(
            article,
            [
                _stored(3, "cccccccccccccccc", status="in_progress", file_id="file_busy"),
                _stored(3, "oldoldoldoldold0", status="completed", file_id="file_old"),
            ],
        )
        self.assertEqual(decision.kind, DeltaKind.IN_PROGRESS)
        self.assertEqual(decision.current_file_id, "file_busy")
        self.assertEqual(decision.old_file_ids, ("file_old",))

    def test_failed_when_same_hash_failed_or_cancelled(self) -> None:
        article = _local(4, "dddddddddddddddd")
        failed = decide_delta(
            article,
            [_stored(4, "dddddddddddddddd", status="failed", file_id="file_bad")],
        )
        cancelled = decide_delta(
            article,
            [_stored(4, "dddddddddddddddd", status="cancelled", file_id="file_cancel")],
        )
        self.assertEqual(failed.kind, DeltaKind.FAILED)
        self.assertEqual(cancelled.kind, DeltaKind.FAILED)

    def test_changed_when_only_older_completed_hash_exists(self) -> None:
        article = _local(5, "neweeeeeeeeeeee")
        decision = decide_delta(
            article,
            [_stored(5, "oldoldoldoldold0", status="completed", file_id="file_old")],
        )
        self.assertEqual(decision.kind, DeltaKind.CHANGED)
        self.assertIsNone(decision.current_file_id)
        self.assertEqual(decision.old_file_ids, ("file_old",))

    def test_decide_deltas_covers_each_kind(self) -> None:
        locals_ = [
            _local(1, "aaaaaaaaaaaaaaaa"),
            _local(2, "bbbbbbbbbbbbbbbb"),
            _local(3, "cccccccccccccccc"),
            _local(4, "dddddddddddddddd"),
            _local(5, "eeeeeeeeeeeeeeee"),
        ]
        stored = [
            _stored(2, "bbbbbbbbbbbbbbbb", status="completed", file_id="f2"),
            _stored(3, "cccccccccccccccc", status="in_progress", file_id="f3"),
            _stored(4, "dddddddddddddddd", status="failed", file_id="f4"),
            _stored(5, "oldoldoldoldold0", status="completed", file_id="f5"),
        ]
        kinds = [decision.kind for decision in decide_deltas(locals_, stored)]
        self.assertEqual(
            kinds,
            [
                DeltaKind.NEW,
                DeltaKind.UNCHANGED,
                DeltaKind.IN_PROGRESS,
                DeltaKind.FAILED,
                DeltaKind.CHANGED,
            ],
        )


if __name__ == "__main__":
    unittest.main()

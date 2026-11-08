"""Regression: chunking strategy settings are not indexed chunk counts."""

from __future__ import annotations

import unittest

from check_one_file import _count_fields, _strategy_settings, indexed_chunk_count_lines


VECTOR_STORE_FILE = {
    "id": "file_abc",
    "status": "completed",
    "usage_bytes": 4096,
    "chunking_strategy": {
        "type": "static",
        "static": {
            "max_chunk_size_tokens": 800,
            "chunk_overlap_tokens": 400,
        },
    },
}

VECTOR_STORE = {
    "status": "completed",
    "usage_bytes": 4096,
    "file_counts": {
        "cancelled": 0,
        "completed": 1,
        "failed": 0,
        "in_progress": 0,
        "total": 1,
    },
}


class ChunkCountDetectionTests(unittest.TestCase):
    def test_strategy_settings_are_not_indexed_chunk_counts(self) -> None:
        count_lines = _count_fields(VECTOR_STORE_FILE) + _count_fields(VECTOR_STORE)
        settings = _strategy_settings(VECTOR_STORE_FILE)

        self.assertIn("usage_bytes=4096", count_lines)
        self.assertIn("file_counts.completed=1", count_lines)
        self.assertIn("file_counts.total=1", count_lines)
        self.assertIn("chunking_strategy.static.max_chunk_size_tokens=800", settings)
        self.assertIn("chunking_strategy.static.chunk_overlap_tokens=400", settings)
        self.assertEqual(indexed_chunk_count_lines(count_lines), [])

        counted = dict(VECTOR_STORE_FILE)
        counted["chunk_count"] = 3
        chunk_lines = indexed_chunk_count_lines(_count_fields(counted))
        self.assertEqual(chunk_lines, ["chunk_count=3"])
        self.assertNotIn("max_chunk_size_tokens=800", " ".join(chunk_lines))


if __name__ == "__main__":
    unittest.main()

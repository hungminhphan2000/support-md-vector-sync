"""Mocked tests for main.py refresh-set collection."""

from __future__ import annotations

import unittest
from pathlib import Path

from main import (
    RefreshCollection,
    article_ids_from_stored,
    collect_refresh_articles,
)
from src.articles import ArticleFetchError
from src.vector_store import StoredFile, content_digest


def _article(article_id: int, **overrides: object) -> dict:
    article = {
        "id": article_id,
        "draft": False,
        "title": f"Title {article_id}",
        "body": f"<p>Body {article_id}</p>",
        "html_url": f"https://support.optisigns.com/hc/en-us/articles/{article_id}",
        "updated_at": "2024-01-15T12:34:56Z",
    }
    article.update(overrides)
    return article


def _markdown(article: dict) -> str:
    return (
        f"# {article['title']}\n\n"
        f"Article URL: {article['html_url']}\n\n"
        f"Body {article['id']}\n"
    )


class ArticleIdsFromStoredTests(unittest.TestCase):
    def test_collects_unique_article_ids(self) -> None:
        stored = [
            StoredFile("file-a", "1-aaaaaaaaaaaaaaaa.md", 1, "aaaaaaaaaaaaaaaa", "completed"),
            StoredFile("file-b", "99-bbbbbbbbbbbbbbbb.md", 99, "bbbbbbbbbbbbbbbb", "completed"),
            StoredFile("file-c", "1-cccccccccccccccc.md", 1, "cccccccccccccccc", "failed"),
        ]
        self.assertEqual(article_ids_from_stored(stored), {1, 99})


class CollectRefreshArticlesTests(unittest.TestCase):
    def test_fetches_stored_id_absent_from_page_payload(self) -> None:
        page = [_article(1), _article(2)]
        off_page = _article(99)
        by_id_calls: list[int] = []

        def fetch_page() -> list[dict]:
            return page

        def fetch_by_id(article_id: int) -> dict:
            by_id_calls.append(article_id)
            if article_id == 99:
                return off_page
            raise AssertionError(f"unexpected by-id fetch: {article_id}")

        result = collect_refresh_articles(
            stored_ids={1, 99},
            fetch_page=fetch_page,
            fetch_by_id=fetch_by_id,
            to_markdown=_markdown,
            required_article_id=1,
        )

        self.assertIsInstance(result, RefreshCollection)
        self.assertEqual(by_id_calls, [99])
        self.assertEqual(result.fetched_by_id, (99,))
        self.assertEqual(result.skipped_ids, ())
        self.assertEqual(
            [article.article_id for article in result.articles],
            [1, 2, 99],
        )
        off_page_local = next(a for a in result.articles if a.article_id == 99)
        expected = _markdown(off_page).encode("utf-8")
        self.assertEqual(off_page_local.content, expected)
        self.assertEqual(off_page_local.digest, content_digest(expected))
        self.assertEqual(off_page_local.path, Path("99.md"))
        self.assertEqual(off_page_local.filename, f"99-{off_page_local.digest}.md")

    def test_skips_invalid_or_unpublished_missing_ids(self) -> None:
        def fetch_page() -> list[dict]:
            return [_article(1)]

        def fetch_by_id(article_id: int) -> dict:
            if article_id == 50:
                raise ArticleFetchError("Article 50 is not published (draft=True).")
            if article_id == 60:
                raise ArticleFetchError("Article 60 was not found.")
            raise AssertionError(f"unexpected by-id fetch: {article_id}")

        result = collect_refresh_articles(
            stored_ids={1, 50, 60},
            fetch_page=fetch_page,
            fetch_by_id=fetch_by_id,
            to_markdown=_markdown,
            required_article_id=1,
        )

        self.assertEqual([a.article_id for a in result.articles], [1])
        self.assertEqual(result.fetched_by_id, ())
        self.assertEqual(result.skipped_ids, (50, 60))

    def test_includes_required_id_when_absent_from_page_and_store(self) -> None:
        required = 360051014713
        by_id_calls: list[int] = []

        def fetch_page() -> list[dict]:
            return [_article(1)]

        def fetch_by_id(article_id: int) -> dict:
            by_id_calls.append(article_id)
            return _article(article_id)

        result = collect_refresh_articles(
            stored_ids=set(),
            fetch_page=fetch_page,
            fetch_by_id=fetch_by_id,
            to_markdown=_markdown,
            required_article_id=required,
        )

        self.assertEqual(by_id_calls, [required])
        self.assertEqual(result.fetched_by_id, (required,))
        self.assertEqual(
            [a.article_id for a in result.articles],
            [1, required],
        )


if __name__ == "__main__":
    unittest.main()

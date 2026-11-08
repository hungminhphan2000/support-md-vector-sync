"""Focused unit tests for article validation and pagination safety."""

from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from src.articles import (
    ARTICLES_LIST_URL,
    ArticleFetchError,
    _validate_published_article,
    fetch_article_by_id,
    fetch_published_articles,
)


def _valid_article(article_id: int = 1, **overrides: object) -> dict:
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


class ValidatePublishedArticleTests(unittest.TestCase):
    def test_accepts_well_formed_published_article(self) -> None:
        article_id = _validate_published_article(_valid_article(42))
        self.assertEqual(article_id, 42)

    def test_rejects_non_integer_id(self) -> None:
        with self.assertRaisesRegex(ArticleFetchError, r"Article 'abc': invalid field 'id'\."):
            _validate_published_article(_valid_article(id="abc"))

    def test_rejects_bool_id(self) -> None:
        with self.assertRaisesRegex(ArticleFetchError, r"Article True: invalid field 'id'\."):
            _validate_published_article(_valid_article(id=True))

    def test_rejects_empty_title(self) -> None:
        with self.assertRaisesRegex(ArticleFetchError, r"Article 7: invalid field 'title'\."):
            _validate_published_article(_valid_article(7, title="   "))

    def test_rejects_missing_body(self) -> None:
        article = _valid_article(8)
        del article["body"]
        with self.assertRaisesRegex(ArticleFetchError, r"Article 8: invalid field 'body'\."):
            _validate_published_article(article)

    def test_rejects_empty_html_url(self) -> None:
        with self.assertRaisesRegex(ArticleFetchError, r"Article 9: invalid field 'html_url'\."):
            _validate_published_article(_valid_article(9, html_url=""))

    def test_rejects_unparseable_updated_at(self) -> None:
        with self.assertRaisesRegex(
            ArticleFetchError, r"Article 10: invalid field 'updated_at'\."
        ):
            _validate_published_article(_valid_article(10, updated_at="not-a-timestamp"))

    def test_rejects_non_string_updated_at(self) -> None:
        with self.assertRaisesRegex(
            ArticleFetchError, r"Article 11: invalid field 'updated_at'\."
        ):
            _validate_published_article(_valid_article(11, updated_at=1700000000))


class RepeatedPaginationTests(unittest.TestCase):
    def test_raises_when_pagination_url_repeats(self) -> None:
        page_two = "https://support.optisigns.com/api/v2/help_center/en-us/articles.json?page=2&per_page=100"
        pages = {
            ARTICLES_LIST_URL: {
                "articles": [_valid_article(1)],
                "next_page": page_two,
            },
            page_two: {
                "articles": [_valid_article(2)],
                "next_page": page_two,
            },
        }

        def fake_request_json(url: str, *, timeout: float) -> dict:
            self.assertGreater(timeout, 0)
            try:
                return pages[url]
            except KeyError as exc:
                raise AssertionError(f"Unexpected URL requested: {url!r}") from exc

        with patch("src.articles._request_json", side_effect=fake_request_json):
            with self.assertRaisesRegex(
                ArticleFetchError,
                rf"Repeated pagination URL: {re.escape(repr(page_two))}\.",
            ):
                fetch_published_articles(min_count=5, required_article_id=1, timeout=5.0)

    def test_skips_drafts_without_validating_them(self) -> None:
        payload = {
            "articles": [
                _valid_article(1, draft=True, title="", body="", html_url="", updated_at="bad"),
                _valid_article(2),
            ],
            "next_page": None,
        }

        with patch("src.articles._request_json", return_value=payload):
            articles = fetch_published_articles(
                min_count=1, required_article_id=2, timeout=5.0
            )

        self.assertEqual([article["id"] for article in articles], [2])


class FetchArticleByIdLogTests(unittest.TestCase):
    def test_logs_each_by_id_fetch(self) -> None:
        article = _valid_article(360051014713)
        with patch(
            "src.articles._request_json",
            return_value={"article": article},
        ):
            with patch("builtins.print") as printed:
                fetch_article_by_id(360051014713, timeout=5.0)

        printed.assert_any_call("fetch_article_by_id article_id=360051014713")

    def test_required_backfill_logs_by_id_fetch(self) -> None:
        page = {
            "articles": [_valid_article(1)],
            "next_page": None,
        }
        required = _valid_article(99)

        def fake_request_json(url: str, *, timeout: float) -> dict:
            if "articles/99.json" in url:
                return {"article": required}
            return page

        with patch("src.articles._request_json", side_effect=fake_request_json):
            with patch("builtins.print") as printed:
                articles = fetch_published_articles(
                    min_count=1, required_article_id=99, timeout=5.0
                )

        self.assertEqual(sorted(a["id"] for a in articles), [1, 99])
        printed.assert_any_call("fetch_article_by_id article_id=99")


if __name__ == "__main__":
    unittest.main()

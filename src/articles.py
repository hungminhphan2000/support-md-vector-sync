"""Fetch published OptiSigns Help Center articles via the Zendesk API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

ARTICLES_LIST_URL = (
    "https://support.optisigns.com/api/v2/help_center/en-us/articles.json"
    "?per_page=100"
)
ARTICLE_BY_ID_URL = (
    "https://support.optisigns.com/api/v2/help_center/en-us/articles/{article_id}.json"
)
REQUIRED_ARTICLE_ID = 360051014713
MIN_PUBLISHED_ARTICLES = 30
DEFAULT_TIMEOUT_SECONDS = 30.0


class ArticleFetchError(Exception):
    """Raised when an article request fails or returns an invalid payload."""


def _request_json(url: str, *, timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "optibot-article-fetcher/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            if status != 200:
                raise ArticleFetchError(
                    f"Request to {url!r} failed with HTTP status {status}."
                )
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        detail = f" Response body: {body[:300]}" if body else ""
        raise ArticleFetchError(
            f"Request to {url!r} failed with HTTP status {exc.code}.{detail}"
        ) from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise ArticleFetchError(
                f"Request to {url!r} timed out after {timeout}s."
            ) from exc
        raise ArticleFetchError(f"Request to {url!r} failed: {reason}") from exc
    except TimeoutError as exc:
        raise ArticleFetchError(
            f"Request to {url!r} timed out after {timeout}s."
        ) from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArticleFetchError(
            f"Response from {url!r} was not valid JSON: {exc}"
        ) from exc


def _is_published(article: dict[str, Any]) -> bool:
    return article.get("draft") is False


def _parse_updated_at(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _validate_published_article(article: dict[str, Any]) -> int:
    """
    Validate a published article record.

    Returns the article id. Raises ArticleFetchError naming the article id and
    the invalid field when a required field is missing or malformed.
    """
    raw_id = article.get("id")
    if isinstance(raw_id, bool) or not isinstance(raw_id, int):
        raise ArticleFetchError(f"Article {raw_id!r}: invalid field 'id'.")

    article_id = raw_id
    for field in ("title", "body", "html_url"):
        value = article.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ArticleFetchError(
                f"Article {article_id}: invalid field '{field}'."
            )

    updated_at = article.get("updated_at")
    if not isinstance(updated_at, str) or not updated_at.strip():
        raise ArticleFetchError(
            f"Article {article_id}: invalid field 'updated_at'."
        )
    try:
        _parse_updated_at(updated_at)
    except ValueError as exc:
        raise ArticleFetchError(
            f"Article {article_id}: invalid field 'updated_at'."
        ) from exc

    return article_id


def _extract_articles(payload: Any, *, url: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ArticleFetchError(
            f"Invalid response from {url!r}: expected a JSON object, got {type(payload).__name__}."
        )
    articles = payload.get("articles")
    if articles is None and isinstance(payload.get("article"), dict):
        return [payload["article"]]
    if not isinstance(articles, list):
        raise ArticleFetchError(
            f"Invalid response from {url!r}: missing or non-list 'articles' field."
        )
    for index, article in enumerate(articles):
        if not isinstance(article, dict):
            raise ArticleFetchError(
                f"Invalid response from {url!r}: articles[{index}] is not an object."
            )
    return articles


def _next_page_url(payload: dict[str, Any], *, url: str) -> str | None:
    next_page = payload.get("next_page")
    if next_page is None:
        return None
    if not isinstance(next_page, str) or not next_page.strip():
        raise ArticleFetchError(
            f"Invalid response from {url!r}: 'next_page' must be a URL string or null."
        )
    return next_page


def fetch_article_by_id(
    article_id: int,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """
    Fetch one published article by id from ``/articles/{id}.json``.

    Raises ArticleFetchError when the article is missing, unpublished, or invalid.
    """
    if timeout <= 0:
        raise ValueError("timeout must be positive.")

    print(f"fetch_article_by_id article_id={article_id}")
    url = ARTICLE_BY_ID_URL.format(article_id=article_id)
    payload = _request_json(url, timeout=timeout)
    articles = _extract_articles(payload, url=url)
    if not articles:
        raise ArticleFetchError(
            f"Article {article_id} was not found in response from {url!r}."
        )
    article = articles[0]
    if not _is_published(article):
        raise ArticleFetchError(
            f"Article {article_id} is not published (draft=True)."
        )
    validated_id = _validate_published_article(article)
    if validated_id != article_id:
        raise ArticleFetchError(
            f"Expected article id {article_id}, got {validated_id!r} from {url!r}."
        )
    return article


def fetch_published_articles(
    *,
    min_count: int = MIN_PUBLISHED_ARTICLES,
    required_article_id: int = REQUIRED_ARTICLE_ID,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """
    Fetch at least ``min_count`` distinct published Help Center articles.

    Paginates with ``next_page`` only while fewer than ``min_count`` published
    articles have been collected. Guarantees ``required_article_id`` is present
    by fetching it directly when it was not already on a collected page.
    """
    if min_count < 1:
        raise ValueError("min_count must be at least 1.")
    if timeout <= 0:
        raise ValueError("timeout must be positive.")

    by_id: dict[int, dict[str, Any]] = {}
    visited_urls: set[str] = set()
    url: str | None = ARTICLES_LIST_URL

    while url is not None and len(by_id) < min_count:
        if url in visited_urls:
            raise ArticleFetchError(f"Repeated pagination URL: {url!r}.")
        visited_urls.add(url)

        payload = _request_json(url, timeout=timeout)
        if not isinstance(payload, dict):
            raise ArticleFetchError(
                f"Invalid response from {url!r}: expected a JSON object."
            )

        for article in _extract_articles(payload, url=url):
            if not _is_published(article):
                continue
            article_id = _validate_published_article(article)
            by_id.setdefault(article_id, article)

        url = _next_page_url(payload, url=url) if len(by_id) < min_count else None

    if required_article_id not in by_id:
        by_id[required_article_id] = fetch_article_by_id(
            required_article_id, timeout=timeout
        )

    if len(by_id) < min_count:
        raise ArticleFetchError(
            f"Only collected {len(by_id)} distinct published articles; need at least {min_count}."
        )

    return list(by_id.values())


if __name__ == "__main__":
    articles = fetch_published_articles()
    ids = sorted(article["id"] for article in articles)
    print(f"fetched={len(articles)}")
    print(f"includes_required={REQUIRED_ARTICLE_ID in ids}")
    print(f"sample_ids={ids[:5]}")

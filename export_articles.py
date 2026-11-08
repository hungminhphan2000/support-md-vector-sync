#!/usr/bin/env python3
"""Fetch Help Center articles, convert to Markdown, and write data/articles/<id>.md."""

from __future__ import annotations

from pathlib import Path

from src.articles import fetch_published_articles
from src.normalize import article_to_markdown

OUTPUT_DIR = Path("data/articles")


def main() -> int:
    articles = fetch_published_articles()
    fetched = len(articles)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    saved = 0
    failed = 0
    for article in articles:
        article_id = article.get("id")
        try:
            markdown = article_to_markdown(article)
            if not isinstance(article_id, int):
                raise ValueError(f"missing integer article id: {article_id!r}")
            path = OUTPUT_DIR / f"{article_id}.md"
            path.write_text(markdown, encoding="utf-8")
            saved += 1
        except Exception as exc:  # noqa: BLE001 - report per-article failures and continue
            failed += 1
            print(f"failed article_id={article_id!r}: {exc}")

    print(f"fetched={fetched}")
    print(f"saved={saved}")
    print(f"failed={failed}")
    return 0 if failed == 0 and saved >= 30 else 1


if __name__ == "__main__":
    raise SystemExit(main())

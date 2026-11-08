"""Focused fixture tests for HTML-to-Markdown normalization."""

from __future__ import annotations

import unittest
from pathlib import Path

from src.normalize import article_to_markdown, html_body_to_markdown

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FORMATTING_FIXTURE_PATH = FIXTURES_DIR / "article_formatting.html"
FRAGMENT_FIXTURE_PATH = FIXTURES_DIR / "fragment_anchors.html"


class NormalizeFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_html = FORMATTING_FIXTURE_PATH.read_text(encoding="utf-8")
        cls.markdown = html_body_to_markdown(cls.fixture_html)

    def test_preserves_headings(self) -> None:
        self.assertIn("# Top Heading", self.markdown)
        self.assertIn("## Section", self.markdown)
        self.assertIn("### Subsection", self.markdown)

    def test_preserves_nested_lists(self) -> None:
        self.assertRegex(self.markdown, r"(?m)^- Alpha$")
        self.assertRegex(self.markdown, r"(?m)^  - Nested Alpha$")
        self.assertRegex(self.markdown, r"(?m)^    - Deep Alpha$")
        self.assertRegex(self.markdown, r"(?m)^- Beta$")

    def test_preserves_tables(self) -> None:
        self.assertIn("| Plan | Screens |", self.markdown)
        self.assertIn("| --- | --- |", self.markdown)
        self.assertIn("| Starter | 1 |", self.markdown)
        self.assertIn("| Pro | 10 |", self.markdown)

    def test_preserves_relative_links(self) -> None:
        self.assertIn(
            "[relative article](/hc/en-us/articles/123-relative)",
            self.markdown,
        )

    def test_preserves_inline_code(self) -> None:
        self.assertIn("`optisigns --help`", self.markdown)

    def test_preserves_fenced_code_blocks(self) -> None:
        self.assertIn("```python", self.markdown)
        self.assertIn('print(f"hello {name}")', self.markdown)
        self.assertIn("```", self.markdown)

    def test_removes_scripts_styles_and_nav(self) -> None:
        self.assertNotIn("Should not appear", self.markdown)
        self.assertNotIn("window.track", self.markdown)
        self.assertNotIn(".secret", self.markdown)
        self.assertNotIn("<script", self.markdown)
        self.assertNotIn("<style", self.markdown)
        self.assertNotIn("<nav", self.markdown)

    def test_article_to_markdown_includes_title_and_article_url(self) -> None:
        article = {
            "id": 360051014713,
            "title": "How to Use YouTube with OptiSigns",
            "html_url": (
                "https://support.optisigns.com/hc/en-us/articles/"
                "360051014713-How-to-Use-YouTube-with-OptiSigns"
            ),
            "body": self.fixture_html,
            "draft": False,
            "updated_at": "2024-01-15T12:34:56Z",
        }
        markdown = article_to_markdown(article)

        self.assertTrue(markdown.startswith("# How to Use YouTube with OptiSigns\n"))
        self.assertIn(
            "Article URL: https://support.optisigns.com/hc/en-us/articles/"
            "360051014713-How-to-Use-YouTube-with-OptiSigns",
            markdown,
        )
        self.assertIn("## Section", markdown)
        self.assertNotIn("Should not appear", markdown)


class FragmentAnchorRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture_html = FRAGMENT_FIXTURE_PATH.read_text(encoding="utf-8")
        cls.markdown = html_body_to_markdown(cls.fixture_html)

    def test_preserves_name_attribute_anchor_targets(self) -> None:
        self.assertIn("[Creating a YouTube App](#CreatingAYouTubeApp)", self.markdown)
        self.assertIn('<a id="CreatingAYouTubeApp"></a>', self.markdown)

        link_at = self.markdown.index("[Creating a YouTube App](#CreatingAYouTubeApp)")
        target_at = self.markdown.index('<a id="CreatingAYouTubeApp"></a>')
        self.assertLess(link_at, target_at)

    def test_preserves_element_id_anchor_targets(self) -> None:
        self.assertIn(
            "[heading target](#h_01M678KRMA1HP8507RRWACWRGF)",
            self.markdown,
        )
        self.assertIn('<a id="h_01M678KRMA1HP8507RRWACWRGF"></a>', self.markdown)
        self.assertIn("## Creating a YouTube App", self.markdown)

        target_at = self.markdown.index('<a id="h_01M678KRMA1HP8507RRWACWRGF"></a>')
        heading_at = self.markdown.index("## Creating a YouTube App")
        self.assertLess(target_at, heading_at)

    def test_keeps_relative_link_urls_unchanged(self) -> None:
        self.assertIn(
            "[relative article](/hc/en-us/articles/123-relative)",
            self.markdown,
        )


if __name__ == "__main__":
    unittest.main()

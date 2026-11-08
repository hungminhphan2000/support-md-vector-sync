"""Convert Help Center article HTML into clean Markdown."""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup, Tag
from markdownify import MarkdownConverter

_STRIP_TAGS = ("script", "style", "nav")


def _language_from_classes(classes: Any) -> str:
    for class_name in classes or []:
        if isinstance(class_name, str) and class_name.startswith("language-"):
            return class_name.removeprefix("language-")
    return ""


def _code_language(tag: Any) -> str:
    """Read a fenced-block language from ``<pre>`` or nested ``<code>`` classes."""
    language = _language_from_classes(tag.get("class"))
    if language:
        return language
    code = tag.find("code")
    if code is not None:
        return _language_from_classes(code.get("class"))
    return ""


def _escape_attr(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _anchor_markup(anchor_id: str) -> str:
    return f'<a id="{_escape_attr(anchor_id)}"></a>'


def _unique_anchor_ids(tag: Tag) -> list[str]:
    values: list[str] = []
    if tag.name == "a":
        name = tag.get("name")
        if isinstance(name, str) and name.strip():
            values.append(name.strip())
    element_id = tag.get("id")
    if isinstance(element_id, str) and element_id.strip():
        values.append(element_id.strip())

    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _is_target_only_anchor(tag: Tag) -> bool:
    return (
        tag.name == "a"
        and not tag.get("href")
        and not tag.get_text(strip=True)
    )


def _preserve_explicit_anchor_targets(soup: BeautifulSoup) -> None:
    """
    Keep fragment targets that markdownify would otherwise drop.

    - Empty ``<a name=\"...\">`` / ``<a id=\"...\">`` become id-only anchors.
    - Other elements with ``id`` (and named anchors with content) get an
      explicit empty ``<a id=\"...\">`` inserted before them.
    Relative ``href`` values are left unchanged.
    """
    for tag in list(soup.find_all(True)):
        if not isinstance(tag, Tag):
            continue
        anchor_ids = _unique_anchor_ids(tag)
        if not anchor_ids:
            continue

        if _is_target_only_anchor(tag):
            tag.attrs = {"id": anchor_ids[0]}
            for extra_id in anchor_ids[1:]:
                tag.insert_after(soup.new_tag("a", attrs={"id": extra_id}))
            continue

        for anchor_id in anchor_ids:
            tag.insert_before(soup.new_tag("a", attrs={"id": anchor_id}))
        tag.attrs.pop("id", None)
        if tag.name == "a":
            tag.attrs.pop("name", None)


class ArticleMarkdownConverter(MarkdownConverter):
    """Markdownify converter that keeps explicit fragment targets."""

    def convert_a(self, el: Any, text: str, parent_tags: set[str]) -> str:
        href = el.get("href")
        anchor_id = el.get("id") or el.get("name")
        if not (text or "").strip():
            if anchor_id and not href:
                return _anchor_markup(str(anchor_id))
            return ""
        return super().convert_a(el, text, parent_tags)


def html_body_to_markdown(html: str) -> str:
    """Convert article HTML to Markdown, dropping scripts, styles, and nav."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    _preserve_explicit_anchor_targets(soup)

    markdown = ArticleMarkdownConverter(
        heading_style="ATX",
        bullets="-",
        code_language_callback=_code_language,
        escape_asterisks=False,
        escape_underscores=False,
    ).convert(str(soup))
    return markdown.strip()


def article_to_markdown(article: dict[str, Any]) -> str:
    """
    Build Markdown for one article from ``fetch_published_articles()``.

    Output includes the title, an ``Article URL:`` line, and the converted body.
    """
    title = article.get("title")
    html_url = article.get("html_url")
    body = article.get("body")

    if not isinstance(title, str) or not title.strip():
        raise ValueError("article must include a non-empty string 'title'.")
    if not isinstance(html_url, str) or not html_url.strip():
        raise ValueError("article must include a non-empty string 'html_url'.")
    if not isinstance(body, str):
        raise ValueError("article must include a string 'body'.")

    body_md = html_body_to_markdown(body)
    parts = [f"# {title.strip()}", "", f"Article URL: {html_url.strip()}", ""]
    if body_md:
        parts.append(body_md)
        parts.append("")
    return "\n".join(parts)

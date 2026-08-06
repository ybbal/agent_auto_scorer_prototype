from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from markdown_it import MarkdownIt

MARKDOWN = MarkdownIt(
    "commonmark",
    {
        "html": False,
        "linkify": False,
        "typographer": False,
    },
).enable("strikethrough")


class TelegramHtmlRenderer(HTMLParser):
    """Reduce CommonMark HTML to the subset accepted by Telegram."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.list_stack: list[dict[str, int | str]] = []
        self.link_stack: list[bool] = []
        self.list_item_depth = 0
        self.pre_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"strong", "b"}:
            self.parts.append("<b>")
        elif tag in {"em", "i"}:
            self.parts.append("<i>")
        elif tag in {"s", "del", "strike"}:
            self.parts.append("<s>")
        elif tag == "code":
            language = attributes.get("class") or ""
            if language.startswith("language-"):
                safe_language = html.escape(language, quote=True)
                self.parts.append(f'<code class="{safe_language}">')
            else:
                self.parts.append("<code>")
        elif tag in {"pre", "blockquote"}:
            self.parts.append(f"<{tag}>")
            if tag == "pre":
                self.pre_depth += 1
        elif tag == "a":
            href = attributes.get("href")
            if href is not None and self._safe_link(href):
                self.link_stack.append(True)
                self.parts.append(f'<a href="{html.escape(href, quote=True)}">')
            else:
                self.link_stack.append(False)
        elif re.fullmatch(r"h[1-6]", tag):
            self.parts.append("<b>")
        elif tag == "ul":
            self.list_stack.append({"kind": "ul", "next": 1})
        elif tag == "ol":
            start = attributes.get("start") or "1"
            self.list_stack.append(
                {"kind": "ol", "next": int(start) if start.isdigit() else 1}
            )
        elif tag == "li":
            self._ensure_newline()
            prefix = "• "
            if self.list_stack and self.list_stack[-1]["kind"] == "ol":
                number = int(self.list_stack[-1]["next"])
                prefix = f"{number}. "
                self.list_stack[-1]["next"] = number + 1
            self.parts.append("  " * max(len(self.list_stack) - 1, 0) + prefix)
            self.list_item_depth += 1
        elif tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"strong", "b"}:
            self.parts.append("</b>")
        elif tag in {"em", "i"}:
            self.parts.append("</i>")
        elif tag in {"s", "del", "strike"}:
            self.parts.append("</s>")
        elif tag in {"code", "pre", "blockquote"}:
            self.parts.append(f"</{tag}>")
            if tag == "pre":
                self.pre_depth = max(self.pre_depth - 1, 0)
            if tag in {"pre", "blockquote"}:
                self.parts.append("\n")
        elif tag == "a":
            if self.link_stack and self.link_stack.pop():
                self.parts.append("</a>")
        elif re.fullmatch(r"h[1-6]", tag):
            self.parts.append("</b>\n")
        elif tag == "p":
            if self.list_item_depth == 0:
                self.parts.append("\n")
        elif tag == "li":
            self.list_item_depth = max(self.list_item_depth - 1, 0)
            self._ensure_newline()
        elif tag in {"ul", "ol"}:
            if self.list_stack:
                self.list_stack.pop()
            self._ensure_newline()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            attributes = dict(attrs)
            alt = attributes.get("alt") or "изображение"
            src = attributes.get("src")
            self.parts.append(html.escape(alt))
            if src is not None and self._safe_link(src):
                self.parts.append(f' (<a href="{html.escape(src, quote=True)}">ссылка</a>)')
            return
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.pre_depth == 0 and data.isspace():
            return
        self.parts.append(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&amp;{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&amp;#{name};")

    def _ensure_newline(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    @staticmethod
    def _safe_link(href: str) -> bool:
        return urlparse(href).scheme.casefold() in {"http", "https", "mailto", "tg"}

    def rendered(self) -> str:
        result = "".join(self.parts)
        return re.sub(r"\n{3,}", "\n\n", result).strip()


def render_telegram_markdown(text: str) -> str:
    renderer = TelegramHtmlRenderer()
    renderer.feed(MARKDOWN.render(text))
    renderer.close()
    return renderer.rendered()

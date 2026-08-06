from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.constants import ParseMode
from telegram.error import BadRequest

from auto_value_agent.telegram import TelegramController
from auto_value_agent.telegram_markdown import render_telegram_markdown


def test_common_markdown_is_rendered_as_telegram_html() -> None:
    rendered = render_telegram_markdown(
        "# Заголовок\n\n**Жирный** и _курсив_.\n\n"
        "- Первый\n- Второй\n\n"
        "[Ссылка](https://example.com)\n\n"
        "```python\nprint('<ok>')\n```"
    )

    assert "<b>Заголовок</b>" in rendered
    assert "<b>Жирный</b>" in rendered
    assert "<i>курсив</i>" in rendered
    assert "• Первый\n• Второй" in rendered
    assert '<a href="https://example.com">Ссылка</a>' in rendered
    assert (
        '<pre><code class="language-python">print(&#x27;&lt;ok&gt;&#x27;)\n</code></pre>'
        in rendered
    )
    assert not any(tag in rendered for tag in ("<p>", "<ul>", "<li>", "<h1>"))


def test_raw_html_and_unsafe_links_are_not_forwarded() -> None:
    rendered = render_telegram_markdown(
        "<script>alert('x')</script> [опасно](javascript:alert(1))"
    )

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert '<a href="javascript:' not in rendered


@pytest.mark.asyncio
async def test_telegram_bad_markdown_falls_back_to_plain_text() -> None:
    message = SimpleNamespace(reply_text=AsyncMock(side_effect=[BadRequest("bad html"), None]))
    update = SimpleNamespace(update_id=321, effective_message=message)

    await TelegramController._reply_text(update, "**Ответ**")

    assert message.reply_text.await_count == 2
    first_call, second_call = message.reply_text.await_args_list
    assert first_call.args[0] == "<b>Ответ</b>"
    assert first_call.kwargs["parse_mode"] == ParseMode.HTML
    assert second_call.args[0] == "**Ответ**"
    assert "parse_mode" not in second_call.kwargs

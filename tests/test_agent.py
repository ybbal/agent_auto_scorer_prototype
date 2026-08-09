from __future__ import annotations

from auto_value_agent.agent import SYSTEM_PROMPT, normalize_gigachat_credentials


def test_gigachat_credentials_restore_omitted_base64_padding() -> None:
    assert normalize_gigachat_credentials("Y2xpZW50OnNlY3JldA") == "Y2xpZW50OnNlY3JldA=="


def test_gigachat_credentials_leave_invalid_value_for_provider_diagnostics() -> None:
    assert normalize_gigachat_credentials("not:a:credential") == "not:a:credential"


def test_system_prompt_prioritizes_rounded_mileage_over_history() -> None:
    assert "Текущий JSON-контекст приоритетнее истории" in SYSTEM_PROMPT
    assert "не повторяйте его" in SYSTEM_PROMPT

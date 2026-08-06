from __future__ import annotations

from decimal import Decimal

from conftest import FixedClock

from auto_value_agent.config import Settings
from auto_value_agent.domain import Intent
from auto_value_agent.explanation import FEATURES, ExplanationPolicy, format_rubles
from auto_value_agent.mappings import FeatureMappingRepository
from auto_value_agent.repositories import CsvScoreRepository


def repository(settings: Settings) -> CsvScoreRepository:
    return CsvScoreRepository(
        csv_path=settings.score_csv_path,
        mappings=FeatureMappingRepository(path=settings.feature_mapping_path),
        clock=FixedClock(),
    )


def test_rounding_and_factor_whitelist(settings: Settings) -> None:
    policy = ExplanationPolicy(max_factors_per_direction=3)
    context = policy.context(repository(settings).get("demo-06"))

    assert context.price_text == "примерно 1 620 000 ₽"
    assert len(context.positive_factors) <= 3
    assert len(context.negative_factors) <= 3
    assert {factor.feature for factor in context.positive_factors} <= FEATURES.keys()
    assert {factor.feature for factor in context.negative_factors} <= FEATURES.keys()
    assert not any(
        factor.feature in {
            "market_prices_accidents_count",
            "registration_actions_count",
            "has_pts_duplicate",
        }
        and factor.contribution > 0
        for factor in context.positive_factors
    )
    assert format_rubles(Decimal("1318172.4")) == "1 318 000 ₽"


def test_fallbacks_are_grounded(settings: Settings) -> None:
    policy = ExplanationPolicy(max_factors_per_direction=3)
    context = policy.context(repository(settings).get("demo-03"))

    explain = policy.fallback_text(Intent.EXPLAIN, context)
    preserve = policy.fallback_text(Intent.PRESERVE_VALUE, context)

    assert "1 318 000 ₽" in explain
    assert "Техническое состояние" in explain
    assert "GAP-страхование" in preserve
    assert "1 802 957" not in explain

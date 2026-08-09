from __future__ import annotations

from decimal import Decimal

from conftest import FixedClock

from auto_value_agent.config import Settings
from auto_value_agent.domain import Intent
from auto_value_agent.explanation import (
    FEATURES,
    ExplanationPolicy,
    format_approximate_mileage,
    format_rubles,
)
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
    assert set(FEATURES) == {
        "brand",
        "model",
        "year_production",
        "max_recorded_mileage",
        "engine_power",
        "engine_model",
    }
    assert context.allowed_actions == []
    assert format_rubles(Decimal("1318172.4")) == "1 318 000 ₽"
    assert format_approximate_mileage(Decimal("48340")) == "примерно 48 000 км"
    assert format_approximate_mileage(Decimal("48500")) == "примерно 49 000 км"


def test_agent_context_contains_only_first_version_vehicle_attributes(
    settings: Settings,
) -> None:
    policy = ExplanationPolicy(max_factors_per_direction=3)
    context = policy.context(repository(settings).get("demo-03"))
    payload = context.prompt_payload()

    assert context.vehicle_facts == [
        "Марка: MITSUBISHI",
        "Модель: ASX",
        "Год выпуска: 2014",
        "Пробег: примерно 150 000 км",
        "Мощность двигателя: 150 л.с.",
        "Модель двигателя: 4B10",
    ]
    serialized = str(payload)
    assert "masked_vin" not in payload
    assert "JMB***3212" not in serialized
    assert "ДТП" not in serialized
    assert "ПТС" not in serialized
    assert "Объём двигателя" not in serialized
    assert "Привод" not in serialized
    mileage_factor = next(
        factor
        for factor in context.positive_factors + context.negative_factors
        if factor.feature == "max_recorded_mileage"
    )
    assert mileage_factor.raw_value.startswith("примерно ")
    assert mileage_factor.raw_value == "примерно 150 000 км"


def test_fallbacks_are_grounded(settings: Settings) -> None:
    policy = ExplanationPolicy(max_factors_per_direction=3)
    context = policy.context(repository(settings).get("demo-03"))

    explain = policy.fallback_text(Intent.EXPLAIN, context)
    vehicle_facts = policy.fallback_text(Intent.VEHICLE_FACTS, context)
    preserve = policy.fallback_text(Intent.PRESERVE_VALUE, context)

    assert "1 318 000 ₽" in explain
    assert "1 318 000 ₽" in vehicle_facts
    assert "Пробег в оценке является приблизительным" in explain
    assert "Техническое состояние" not in explain
    assert "GAP-страхование" in preserve
    assert "1 802 957" not in explain

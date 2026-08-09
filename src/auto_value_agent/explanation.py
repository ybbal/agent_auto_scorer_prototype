from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from dependency_injector.wiring import Provide, inject

from auto_value_agent.domain import (
    Action,
    ExplanationContext,
    FactorExplanation,
    Intent,
    VehicleScore,
)

FEATURES = {
    "brand": ("Марка", "shap_brand"),
    "model": ("Модель", "shap_model"),
    "year_production": ("Год выпуска", "shap_year_production"),
    "engine_power": ("Мощность двигателя", "shap_engine_power"),
    "max_recorded_mileage": (
        "Пробег (приблизительно)",
        "shap_max_recorded_mileage",
    ),
    "engine_model": ("Модель двигателя", "shap_engine_model"),
}

PRESERVE_VALUE_ADVICE = """Полностью остановить снижение стоимости автомобиля нельзя, \
но его можно замедлить:
1. Учитывайте ликвидность модели при выборе следующего автомобиля.
2. Бережно эксплуатируйте автомобиль и своевременно проходите ТО.
3. Сохраняйте прозрачную сервисную историю и подтверждающие документы.
4. Выбирайте момент продажи с учётом возраста, пробега и состояния рынка.
5. Для кредитного или премиального автомобиля рассмотрите GAP-страхование вместе \
с КАСКО: условия и исключения необходимо проверить у страховщика.

Дополнительные сценарии прототипа: продажа через СберАвто, запись на ТО и оформление КАСКО."""


def round_thousand(value: Decimal) -> Decimal:
    return value.quantize(Decimal("1E3"), rounding=ROUND_HALF_UP)


def format_integer(value: Decimal | int) -> str:
    return f"{int(value):,}".replace(",", " ")


def format_rubles(value: Decimal, *, signed: bool = False) -> str:
    rounded = round_thousand(value)
    prefix = "+" if signed and rounded > 0 else "−" if signed and rounded < 0 else ""
    return f"{prefix}{format_integer(abs(rounded))} ₽"


def format_approximate_mileage(value: Decimal) -> str:
    return f"примерно {format_integer(round_thousand(value))} км"


class ExplanationPolicy:
    @inject
    def __init__(
        self,
        max_factors_per_direction: int = Provide["config.max_factors_per_direction"],
    ) -> None:
        self._max_factors = max_factors_per_direction

    @staticmethod
    def _raw_value(score: VehicleScore, feature: str) -> str | None:
        payload = score.payload
        if feature == "brand":
            return score.brand_name
        if feature == "model":
            return score.model_name
        if feature == "year_production":
            return str(payload.year_production)
        if feature == "engine_power":
            return f"{format_integer(payload.engine_power)} л.с."
        if feature == "max_recorded_mileage":
            return format_approximate_mileage(payload.max_recorded_mileage)
        if feature == "engine_model":
            return score.engine_model_name
        raise KeyError(feature)

    def factors(
        self, score: VehicleScore
    ) -> tuple[list[FactorExplanation], list[FactorExplanation]]:
        candidates: list[FactorExplanation] = []
        for feature, (label, shap_field) in FEATURES.items():
            contribution = getattr(score.payload, shap_field)
            raw_value = self._raw_value(score, feature)
            if raw_value is None:
                continue
            candidates.append(
                FactorExplanation(
                    feature=feature,
                    label=label,
                    raw_value=raw_value,
                    contribution=contribution,
                    contribution_text=format_rubles(contribution, signed=True),
                )
            )
        positives = sorted(
            (factor for factor in candidates if factor.contribution > 0),
            key=lambda factor: factor.contribution,
            reverse=True,
        )[: self._max_factors]
        negatives = sorted(
            (factor for factor in candidates if factor.contribution < 0),
            key=lambda factor: factor.contribution,
        )[: self._max_factors]
        return positives, negatives

    def context(self, score: VehicleScore) -> ExplanationContext:
        positives, negatives = self.factors(score)
        payload = score.payload
        facts = [
            f"Марка: {score.brand_name}",
            f"Модель: {score.model_name}",
            f"Год выпуска: {payload.year_production}",
            f"Пробег: {format_approximate_mileage(payload.max_recorded_mileage)}",
            f"Мощность двигателя: {format_integer(payload.engine_power)} л.с.",
            f"Модель двигателя: {score.engine_model_name or 'не указана'}",
        ]
        return ExplanationContext(
            display_name=score.display_name,
            masked_vin=score.masked_vin,
            score_date=payload.report_dt,
            price=payload.market_price,
            price_text=f"примерно {format_rubles(payload.market_price)}",
            positive_factors=positives,
            negative_factors=negatives,
            vehicle_facts=facts,
            allowed_actions=[],
            warnings=score.warnings,
        )

    @staticmethod
    def actions_for(intent: Intent) -> list[Action]:
        del intent
        return []

    def fallback_text(self, intent: Intent, context: ExplanationContext) -> str:
        if intent is Intent.VEHICLE_FACTS:
            facts = "\n".join(f"• {fact}" for fact in context.vehicle_facts)
            return (
                f"Текущая оценка {context.display_name} на "
                f"{context.score_date:%d.%m.%Y} — {context.price_text}.\n\n"
                f"Данные, использованные в оценке:\n{facts}"
            )
        if intent is Intent.UPDATE_DATA:
            return "Уточнение и обновление данных в первой версии пока недоступны."
        if intent is Intent.PRESERVE_VALUE:
            return PRESERVE_VALUE_ADVICE
        if intent is Intent.UNSUPPORTED:
            return (
                "Не удалось сформировать свободный ответ. "
                "Попробуйте переформулировать вопрос или повторить его позже."
            )

        prefix = (
            "Понимаю, что оценка может отличаться от ваших ожиданий.\n\n"
            if intent is Intent.DISAGREE
            else ""
        )
        lines = [
            f"{prefix}Текущая оценка {context.display_name} на "
            f"{context.score_date:%d.%m.%Y} — {context.price_text}.",
        ]
        if context.positive_factors:
            lines.append("\nПовышающие модельные факторы:")
            lines.extend(
                f"• {factor.label} ({factor.raw_value}): {factor.contribution_text}"
                for factor in context.positive_factors
            )
        if context.negative_factors:
            lines.append("\nПонижающие модельные факторы:")
            lines.extend(
                f"• {factor.label} ({factor.raw_value}): {factor.contribution_text}"
                for factor in context.negative_factors
            )
        lines.append(
            "\nВклады показывают поведение модели относительно её базового уровня и не являются "
            "доказательством причинной связи. Пробег в оценке является приблизительным."
        )
        return "\n".join(lines)

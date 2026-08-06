from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from dependency_injector.wiring import Provide, inject

from auto_value_agent.domain import (
    Action,
    ActionId,
    ExplanationContext,
    FactorExplanation,
    Intent,
    VehicleScore,
)

FEATURES = {
    "year_production": ("Год выпуска", "shap_year_production"),
    "engine_power": ("Мощность двигателя", "shap_engine_power"),
    "max_recorded_mileage": ("Зафиксированный пробег", "shap_max_recorded_mileage"),
    "market_prices_accidents_count": (
        "ДТП в рыночных данных",
        "shap_market_prices_accidents_count",
    ),
    "registration_actions_count": (
        "Регистрационные действия",
        "shap_registration_actions_count",
    ),
    "engine_volume": ("Объём двигателя", "shap_engine_volume"),
    "has_pts_duplicate": ("Дубликат ПТС", "shap_has_pts_duplicate"),
    "body_style": ("Тип кузова", "shap_body_style"),
    "drive_type": ("Тип привода", "shap_drive_type"),
    "used_in_taxi": ("Использование в такси", "shap_used_in_taxi"),
}

RISK_FEATURES = {
    "market_prices_accidents_count",
    "registration_actions_count",
    "has_pts_duplicate",
    "used_in_taxi",
}

UPDATE_ACTIONS = [
    Action(id=ActionId.UPDATE_MILEAGE, label="Уточнить пробег"),
    Action(id=ActionId.UPDATE_CONDITION, label="Уточнить техническое состояние"),
    Action(id=ActionId.UPDATE_ACCIDENTS, label="Обновить информацию о ДТП"),
]

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


class ExplanationPolicy:
    @inject
    def __init__(
        self,
        max_factors_per_direction: int = Provide["config.max_factors_per_direction"],
    ) -> None:
        self._max_factors = max_factors_per_direction

    @staticmethod
    def _raw_value(score: VehicleScore, feature: str) -> str:
        payload = score.payload
        if feature == "year_production":
            return str(payload.year_production)
        if feature == "engine_power":
            return f"{format_integer(payload.engine_power)} л.с."
        if feature == "max_recorded_mileage":
            return f"{format_integer(payload.max_recorded_mileage)} км"
        if feature == "market_prices_accidents_count":
            return str(payload.market_prices_accidents_count)
        if feature == "registration_actions_count":
            return str(payload.registration_actions_count)
        if feature == "engine_volume":
            return f"{format_integer(payload.engine_volume)} см³"
        if feature == "has_pts_duplicate":
            return "есть" if payload.has_pts_duplicate else "нет"
        if feature == "body_style":
            return score.body_style_name or f"код {payload.body_style}"
        if feature == "drive_type":
            return score.drive_type_name or f"код {payload.drive_type}"
        if feature == "used_in_taxi":
            return "да" if payload.used_in_taxi else "нет"
        raise KeyError(feature)

    @staticmethod
    def _risk_is_present(score: VehicleScore, feature: str) -> bool:
        payload = score.payload
        values = {
            "market_prices_accidents_count": payload.market_prices_accidents_count,
            "registration_actions_count": payload.registration_actions_count,
            "has_pts_duplicate": payload.has_pts_duplicate,
            "used_in_taxi": payload.used_in_taxi,
        }
        return values[feature] > 0

    def factors(
        self, score: VehicleScore
    ) -> tuple[list[FactorExplanation], list[FactorExplanation]]:
        candidates: list[FactorExplanation] = []
        for feature, (label, shap_field) in FEATURES.items():
            contribution = getattr(score.payload, shap_field)
            unsafe_positive_risk = (
                feature in RISK_FEATURES
                and contribution > 0
                and self._risk_is_present(score, feature)
            )
            if unsafe_positive_risk:
                continue
            raw_value = self._raw_value(score, feature)
            if raw_value.startswith("код "):
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
            f"Автомобиль: {score.display_name}",
            f"VIN: {score.masked_vin}",
            (
                f"Оценка на {payload.report_dt:%d.%m.%Y}: "
                f"примерно {format_rubles(payload.market_price)}"
            ),
            (
                "Максимальный зафиксированный пробег: "
                f"{format_integer(payload.max_recorded_mileage)} км"
            ),
            f"Мощность двигателя: {format_integer(payload.engine_power)} л.с.",
            f"Объём двигателя: {format_integer(payload.engine_volume)} см³",
            f"ДТП в рыночных данных: {payload.market_prices_accidents_count}",
            f"Регистрационные действия: {payload.registration_actions_count}",
            f"Дубликат ПТС: {'есть' if payload.has_pts_duplicate else 'нет'}",
            f"Использование в такси: {'да' if payload.used_in_taxi else 'нет'}",
        ]
        if score.body_style_name:
            facts.append(f"Тип кузова: {score.body_style_name}")
        if score.drive_type_name:
            facts.append(f"Привод: {score.drive_type_name}")
        return ExplanationContext(
            display_name=score.display_name,
            masked_vin=score.masked_vin,
            score_date=payload.report_dt,
            price=payload.market_price,
            price_text=f"примерно {format_rubles(payload.market_price)}",
            positive_factors=positives,
            negative_factors=negatives,
            vehicle_facts=facts,
            allowed_actions=UPDATE_ACTIONS,
            warnings=score.warnings,
        )

    @staticmethod
    def actions_for(intent: Intent) -> list[Action]:
        if intent in {Intent.EXPLAIN, Intent.DISAGREE, Intent.UPDATE_DATA}:
            return list(UPDATE_ACTIONS)
        return []

    def fallback_text(self, intent: Intent, context: ExplanationContext) -> str:
        if intent is Intent.VEHICLE_FACTS:
            return "Данные, использованные в оценке:\n" + "\n".join(
                f"• {fact}" for fact in context.vehicle_facts
            )
        if intent is Intent.UPDATE_DATA:
            return (
                "В оценке использованы данные об автомобиле, доступные на дату расчёта. "
                "В прототипе изменение данных не выполняется, но можно запустить "
                "демонстрацию обновления пробега, технического состояния или сведений о ДТП."
            )
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
            "доказательством причинной связи. Техническое состояние в текущей выгрузке отсутствует."
        )
        return "\n".join(lines)

from __future__ import annotations

import csv
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from dependency_injector.wiring import Provide, inject

from auto_value_agent.clock import Clock
from auto_value_agent.domain import (
    DataValidationReport,
    SampleSummary,
    ScorePayload,
    VehicleScore,
)
from auto_value_agent.mappings import FeatureMappingRepository

DEMO_ROW_INDEXES = (369, 960, 401, 492, 114, 397, 281, 171)


def mask_vin(vin: str) -> str:
    if len(vin) < 8:
        return "***"
    return f"{vin[:3]}***{vin[-4:]}"


class CsvScoreRepository:
    @inject
    def __init__(
        self,
        csv_path: Path = Provide["config.score_csv_path"],
        mappings: FeatureMappingRepository = Provide["feature_mapping"],
        clock: Clock = Provide["clock"],
    ) -> None:
        self._csv_path = Path(csv_path)
        self._mappings = mappings
        self._clock = clock
        self._payloads: list[ScorePayload] | None = None

    @staticmethod
    def _clean_row(row: dict[str, str | None]) -> dict[str, Any]:
        return {
            key: (None if value is None or value.strip() == "" else value)
            for key, value in row.items()
        }

    def _load(self) -> list[ScorePayload]:
        if self._payloads is not None:
            return self._payloads
        if not self._csv_path.exists():
            raise FileNotFoundError(f"Score CSV not found: {self._csv_path}")
        with self._csv_path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            expected = list(ScorePayload.model_fields)
            if reader.fieldnames != expected:
                raise ValueError("CSV columns do not exactly match ScorePayload")
            self._payloads = [ScorePayload.model_validate(self._clean_row(row)) for row in reader]
        return self._payloads

    def all_payloads(self) -> list[ScorePayload]:
        return list(self._load())

    def from_payload(self, payload: ScorePayload, sample_id: str = "external") -> VehicleScore:
        warnings: list[str] = []
        residual = payload.market_price - (payload.expected_value + payload.shap_sum)
        if abs(residual) > Decimal("1"):
            warnings.append("baseline_mismatch")
        marker_differs = payload.decimal_value is not None and abs(
            payload.decimal_value - payload.market_price
        ) > Decimal("0.01")
        if marker_differs:
            warnings.append("marker_price_mismatch")
        if payload.datetime_active_until < self._clock.today():
            warnings.append("score_expired")

        brand_name = self._mappings.brand(payload.brand) or f"Марка {payload.brand}"
        model_name = self._mappings.model(payload.brand, payload.model) or f"Модель {payload.model}"
        return VehicleScore(
            sample_id=sample_id,
            payload=payload,
            masked_vin=mask_vin(payload.vin),
            brand_name=brand_name,
            model_name=model_name,
            engine_model_name=self._mappings.engine_model(payload.engine_model),
            body_style_name=self._mappings.body_style(payload.body_style),
            body_color_name=self._mappings.body_color(payload.body_color),
            drive_type_name=self._mappings.drive_type(payload.drive_type),
            warnings=tuple(warnings),
        )

    def get(self, sample_id: str) -> VehicleScore:
        try:
            demo_number = int(sample_id.removeprefix("demo-"))
            row_index = DEMO_ROW_INDEXES[demo_number - 1]
        except (ValueError, IndexError) as error:
            raise KeyError(f"Unknown demo sample: {sample_id}") from error
        payloads = self._load()
        return self.from_payload(payloads[row_index], sample_id)

    def list_samples(self) -> list[SampleSummary]:
        samples: list[SampleSummary] = []
        for number, row_index in enumerate(DEMO_ROW_INDEXES, start=1):
            score = self.from_payload(self._load()[row_index], f"demo-{number:02d}")
            rounded_price = score.payload.market_price.quantize(
                Decimal("1E3"), rounding=ROUND_HALF_UP
            )
            samples.append(
                SampleSummary(
                    sample_id=score.sample_id,
                    label=(
                        f"{score.display_name} — "
                        f"{int(rounded_price):,} ₽"
                    ).replace(",", " "),
                    masked_vin=score.masked_vin,
                    model_name=score.model_name,
                    year=score.payload.year_production,
                    market_price=score.payload.market_price,
                )
            )
        return samples

    def validate(self) -> DataValidationReport:
        payloads = self._load()
        warnings: Counter[str] = Counter()
        for index, payload in enumerate(payloads):
            warnings.update(self.from_payload(payload, f"row-{index}").warnings)
        return DataValidationReport(
            row_count=len(payloads),
            column_count=len(ScorePayload.model_fields),
            demo_count=len(DEMO_ROW_INDEXES),
            warning_counts=dict(warnings),
        )

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScorePayload(BaseModel):
    """Flat score payload matching the 51 columns of the supplied model export."""

    model_config = ConfigDict(extra="forbid")

    vin: str = Field(min_length=5)
    model_version_id: int
    marker_name: str
    int_value: int | None = None
    decimal_value: Decimal | None = None
    text_value: str | None = None
    datetime_active_from: date
    datetime_active_until: date
    report_dt: date
    ctl_loading: int
    market_price: Decimal
    year_production: int
    engine_power: Decimal
    max_recorded_mileage: Decimal
    market_prices_accidents_count: int
    registration_actions_count: int
    brand: int
    weight_max: int
    model: int
    engine_volume: Decimal
    weight_netto: int
    engine_model: int
    has_pts_duplicate: int
    body_style: int
    owner_types_count: int
    body_color: int
    drive_type: int
    reg_action_types_count: int
    used_in_taxi: int
    shap_year_production: Decimal
    shap_engine_power: Decimal
    shap_max_recorded_mileage: Decimal
    shap_market_prices_accidents_count: Decimal
    shap_registration_actions_count: Decimal
    shap_brand: Decimal
    shap_weight_max: Decimal
    shap_model: Decimal
    shap_engine_volume: Decimal
    shap_weight_netto: Decimal
    shap_engine_model: Decimal
    shap_has_pts_duplicate: Decimal
    shap_body_style: Decimal
    shap_owner_types_count: Decimal
    shap_body_color: Decimal
    shap_drive_type: Decimal
    shap_reg_action_types_count: Decimal
    shap_used_in_taxi: Decimal
    shap_sum: Decimal
    expected_value: Decimal
    shap_diff: Decimal
    datetime_published: date | datetime


class VehicleScore(BaseModel):
    """Internal normalized view; the raw score remains available in memory only."""

    sample_id: str
    payload: ScorePayload
    masked_vin: str
    brand_name: str
    model_name: str
    body_style_name: str | None = None
    body_color_name: str | None = None
    drive_type_name: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def display_name(self) -> str:
        return f"{self.brand_name} {self.model_name}, {self.payload.year_production}"


class SampleSummary(BaseModel):
    sample_id: str
    label: str
    masked_vin: str
    model_name: str
    year: int
    market_price: Decimal


class Intent(StrEnum):
    EXPLAIN = "explain"
    VEHICLE_FACTS = "vehicle_facts"
    DISAGREE = "disagree"
    UPDATE_DATA = "update_data"
    PRESERVE_VALUE = "preserve_value"
    UNSUPPORTED = "unsupported"


class ActionId(StrEnum):
    UPDATE_MILEAGE = "update_mileage"
    UPDATE_CONDITION = "update_condition"
    UPDATE_ACCIDENTS = "update_accidents"


class Action(BaseModel):
    id: ActionId
    label: str
    kind: str = "callback"


class FactorExplanation(BaseModel):
    feature: str
    label: str
    raw_value: str
    contribution: Decimal
    contribution_text: str


class ExplanationContext(BaseModel):
    display_name: str
    masked_vin: str
    score_date: date
    price: Decimal
    price_text: str
    positive_factors: list[FactorExplanation]
    negative_factors: list[FactorExplanation]
    vehicle_facts: list[str]
    allowed_actions: list[Action]
    warnings: tuple[str, ...]

    def prompt_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"price", "warnings"})


class AgentReplyDraft(BaseModel):
    """Validated response returned by the consultation agent adapter."""

    intent: Intent
    text: str = Field(min_length=1, max_length=3500)
    action_ids: list[ActionId] = Field(default_factory=list, max_length=3)


class ConsultationRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=2000)
    score: ScorePayload


class ConsultationResponse(BaseModel):
    text: str
    actions: list[Action] = Field(default_factory=list)
    score_date: date
    fallback_used: bool = False
    intent: Intent


class Session(BaseModel):
    channel: str
    external_id: str
    thread_id: str
    sample_id: str | None = None


class DataValidationReport(BaseModel):
    row_count: int
    column_count: int
    demo_count: int
    warning_counts: dict[str, int]

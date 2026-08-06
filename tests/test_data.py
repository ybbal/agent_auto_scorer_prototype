from __future__ import annotations

from conftest import FixedClock

from auto_value_agent.config import Settings
from auto_value_agent.mappings import FeatureMappingRepository
from auto_value_agent.repositories import CsvScoreRepository


def build_repository(settings: Settings) -> CsvScoreRepository:
    mappings = FeatureMappingRepository(path=settings.feature_mapping_path)
    return CsvScoreRepository(
        csv_path=settings.score_csv_path,
        mappings=mappings,
        clock=FixedClock(),
    )


def test_csv_contract_and_demo_catalog(settings: Settings) -> None:
    repository = build_repository(settings)
    report = repository.validate()

    assert report.row_count == 1000
    assert report.column_count == 51
    assert report.demo_count == 8
    assert report.warning_counts["baseline_mismatch"] == 1000
    assert report.warning_counts["score_expired"] == 1000

    samples = repository.list_samples()
    assert [sample.model_name for sample in samples] == [
        "GALANT",
        "LANCER CLASSIC",
        "ASX",
        "PAJERO",
        "MONTERO SPORT",
        "OUTLANDER",
        "L 200",
        "L 200",
    ]
    assert all("***" in sample.masked_vin for sample in samples)
    assert [sample.label.rsplit(" — ", 1)[1] for sample in samples[:3]] == [
        "278 000 ₽",
        "845 000 ₽",
        "1 318 000 ₽",
    ]


def test_mapping_and_selected_score(settings: Settings) -> None:
    repository = build_repository(settings)
    score = repository.get("demo-03")

    assert score.brand_name == "MITSUBISHI"
    assert score.model_name == "ASX"
    assert score.masked_vin == "JMB***3212"
    assert "baseline_mismatch" in score.warnings
    assert score.body_style_name == "Универсал"
    assert score.drive_type_name == "Передний"

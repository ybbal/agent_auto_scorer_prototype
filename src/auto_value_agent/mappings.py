from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dependency_injector.wiring import Provide, inject


class FeatureMappingRepository:
    @inject
    def __init__(self, path: Path = Provide["config.feature_mapping_path"]) -> None:
        self._path = Path(path)
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            raise FileNotFoundError(
                f"Feature mapping JSON not found: {self._path}. "
                "Run scripts/export_feature_mappings.py first."
            )
        value = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("Feature mapping root must be an object")
        return value

    @staticmethod
    def _decode_list(values: list[str], code: int) -> str | None:
        index = code - 1
        if index < 0 or index >= len(values):
            return None
        return values[index]

    def brand(self, code: int) -> str | None:
        return self._decode_list(self._data["marka"], code)

    def model(self, brand_code: int, model_code: int) -> str | None:
        brand_models = self._data["model_by_marka"].get(str(brand_code), {})
        local_code = model_code - brand_code * 10_000
        for name, code in brand_models.items():
            if code == local_code:
                return name
        return None

    def body_style(self, code: int) -> str | None:
        return self._decode_list(self._data["kuzov"], code)

    def body_color(self, code: int) -> str | None:
        return self._decode_list(self._data["body_color"], code)

    def drive_type(self, code: int) -> str | None:
        return self._decode_list(self._data["privod"], code)


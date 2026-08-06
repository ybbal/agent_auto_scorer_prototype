from __future__ import annotations

import argparse
import json
import pickle
import pickletools
from pathlib import Path
from typing import Any

DANGEROUS_OPCODES = {
    "BUILD",
    "EXT1",
    "EXT2",
    "EXT4",
    "GLOBAL",
    "INST",
    "NEWOBJ",
    "NEWOBJ_EX",
    "OBJ",
    "PERSID",
    "BINPERSID",
    "REDUCE",
    "STACK_GLOBAL",
}


def validate_pickle(data: bytes) -> None:
    """Reject pickles that can construct or call arbitrary Python objects."""

    found = sorted({op.name for op, _arg, _pos in pickletools.genops(data)} & DANGEROUS_OPCODES)
    if found:
        raise ValueError(f"Unsafe pickle opcodes found: {', '.join(found)}")


def load_mapping(source: Path) -> dict[str, Any]:
    data = source.read_bytes()
    validate_pickle(data)
    value = pickle.loads(data)  # noqa: S301 - guarded by opcode validation above
    if not isinstance(value, dict):
        raise TypeError("Expected a dictionary at the pickle root")
    required = {"kuzov", "privod", "engine_model", "body_color", "marka", "model_by_marka"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"Missing mapping sections: {', '.join(sorted(missing))}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safely convert the supplied mapping pickle to JSON"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    mapping = load_mapping(args.source)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Regenerate checked-in JSON Schemas from the Pydantic source models."""

from __future__ import annotations

import json
from pathlib import Path

from models import SCHEMA_MODELS


def main() -> int:
    schema_dir = Path(__file__).resolve().parent
    for filename, model in SCHEMA_MODELS.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = filename
        path = schema_dir / filename
        path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

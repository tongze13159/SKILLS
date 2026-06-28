#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from common import atomic_write_json
from validate_artifact import validate_file


def extract_json(text: str) -> dict:
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I | re.S)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(stripped[start : end + 1])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Perform safe local JSON extraction, then validate the result."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    args = parser.parse_args()
    data = extract_json(args.input.read_text(encoding="utf-8"))
    atomic_write_json(args.output, data)
    errors = validate_file(args.output, args.schema)
    if errors:
        for error in errors:
            print(f"INVALID: {error}")
        return 1
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import load_json


def estimate_seedance_cost(duration_ms: int, rate_rmb_per_second: float) -> float:
    return round(duration_ms / 1000 * rate_rmb_per_second, 4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate Seedance generation cost.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--duration-ms", type=int)
    parser.add_argument("--seedance-tasks", type=Path)
    args = parser.parse_args()
    if (args.duration_ms is None) == (args.seedance_tasks is None):
        parser.error("provide exactly one of --duration-ms or --seedance-tasks")
    config = load_json(args.config)
    rate = config["cost_rules"]["seedance_cost_rmb_per_second"]
    duration_ms = args.duration_ms
    if args.seedance_tasks:
        tasks = load_json(args.seedance_tasks)["seedance_tasks"]
        duration_ms = sum(task["duration_ms"] for task in tasks)
    cost = estimate_seedance_cost(int(duration_ms), rate)
    print(json.dumps({"duration_ms": duration_ms, "estimated_cost_rmb": cost}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

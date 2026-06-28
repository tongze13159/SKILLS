#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from pathlib import Path

from common import atomic_write_json, load_json

MIN_SEEDANCE_MS = 4000
MAX_SEEDANCE_MS = 15000


def normalize_plan(plan_artifact: dict, target_ms: int) -> dict:
    shots = plan_artifact["new_video_plan"]["shots"]
    if not shots:
        raise ValueError("new_video_plan has no shots")
    current = sum(shot["duration_ms"] for shot in shots)
    difference = target_ms - current
    base_delta, remainder = divmod(abs(difference), len(shots))
    sign = 1 if difference >= 0 else -1
    for index, shot in enumerate(shots):
        delta = base_delta + (1 if index < remainder else 0)
        new_duration = shot["duration_ms"] + sign * delta
        if new_duration <= 0:
            raise ValueError("normalization would create a non-positive shot duration")
        shot["duration_ms"] = new_duration
    cursor = 0
    for shot in shots:
        shot["start_ms"] = cursor
        cursor += shot["duration_ms"]
        shot["end_ms"] = cursor
    plan_artifact["new_video_plan"]["duration_ms"] = cursor
    plan_artifact["new_video_plan"]["shot_count"] = len(shots)
    return plan_artifact


def _split_long_shots(shots: list[dict]) -> list[dict]:
    expanded: list[dict] = []
    for shot in shots:
        duration_ms = int(shot["duration_ms"])
        if duration_ms <= MAX_SEEDANCE_MS:
            expanded.append(dict(shot))
            continue
        part_count = int(math.ceil(duration_ms / MAX_SEEDANCE_MS))
        base = duration_ms // part_count
        remainder = duration_ms % part_count
        cursor = int(shot["start_ms"])
        for index in range(part_count):
            part_duration_ms = base + (1 if index < remainder else 0)
            part_end_ms = cursor + part_duration_ms
            part = dict(shot)
            part["start_ms"] = cursor
            part["end_ms"] = part_end_ms
            part["duration_ms"] = part_duration_ms
            part["_split_index"] = index + 1
            part["_split_total"] = part_count
            part["_generation_strategy"] = "shot_split"
            expanded.append(part)
            cursor = part_end_ms
    return expanded


def _group_duration_ms(group: list[dict]) -> int:
    return sum(int(shot["duration_ms"]) for shot in group)


def _group_contains_short(group: list[dict]) -> bool:
    return any(int(shot["duration_ms"]) < MIN_SEEDANCE_MS for shot in group)


def _build_generation_groups(shots: list[dict]) -> list[list[dict]]:
    shots = _split_long_shots(shots)
    if not shots:
        return []
    total_duration_ms = sum(int(shot["duration_ms"]) for shot in shots)
    if total_duration_ms <= MIN_SEEDANCE_MS:
        return [shots]

    n = len(shots)
    best: list[tuple[int, int, int, int] | None] = [None] * (n + 1)
    choice: list[int | None] = [None] * (n + 1)
    best[n] = (0, 0, 0, 0)

    for start in range(n - 1, -1, -1):
        group: list[dict] = []
        duration_ms = 0
        for end in range(start, n):
            shot = shots[end]
            group.append(shot)
            duration_ms += int(shot["duration_ms"])
            if duration_ms > MAX_SEEDANCE_MS:
                break
            is_single = len(group) == 1
            if is_single:
                valid = int(group[0]["duration_ms"]) >= MIN_SEEDANCE_MS
            else:
                valid = duration_ms >= MIN_SEEDANCE_MS and _group_contains_short(group)
            if not valid or best[end + 1] is None:
                continue
            merge_footprint = len(group) - 1
            split_footprint = sum(1 for item in group if item.get("_generation_strategy") == "shot_split")
            added_ms = (max(4, min(15, int(math.floor((duration_ms + 500) / 1000)))) * 1000) - duration_ms
            tail = best[end + 1]
            score = (
                merge_footprint + tail[0],
                split_footprint + tail[1],
                duration_ms + tail[2],
                added_ms + tail[3],
            )
            if best[start] is None or score < best[start]:
                best[start] = score
                choice[start] = end + 1

    if choice[0] is None:
        raise ValueError("Could not build a valid generation-ready plan under Seedance duration constraints")

    groups: list[list[dict]] = []
    cursor = 0
    while cursor < n:
        next_cursor = choice[cursor]
        if next_cursor is None or next_cursor <= cursor:
            raise ValueError("Invalid generation-ready grouping state")
        groups.append(shots[cursor:next_cursor])
        cursor = next_cursor
    return groups


def prepare_plan_for_generation(plan_artifact: dict, target_ms: int | None = None) -> dict:
    if target_ms is not None:
        plan_artifact = normalize_plan(plan_artifact, target_ms)
    shots = plan_artifact["new_video_plan"]["shots"]
    groups = _build_generation_groups(shots)
    prepared_shots: list[dict] = []
    cursor = 0
    for index, group in enumerate(groups, start=1):
        first = group[0]
        last = group[-1]
        duration_ms = _group_duration_ms(group)
        product_focus: list[str] = []
        must_keep: list[str] = []
        must_change: list[str] = []
        risks: list[str] = []
        for shot in group:
            for field_name, bucket in (
                ("product_focus", product_focus),
                ("must_keep_from_reference", must_keep),
                ("must_change_from_reference", must_change),
                ("generation_risks", risks),
            ):
                for item in shot.get(field_name, []):
                    if item not in bucket:
                        bucket.append(item)
        strategy = (
            "adjacent_merge"
            if len(group) > 1
            else group[0].get("_generation_strategy", "standalone")
        )
        prepared_shots.append(
            {
                "new_shot_id": f"new_{index:03d}",
                "reference_shot_id": first["reference_shot_id"],
                "duration_ms": duration_ms,
                "start_ms": cursor,
                "end_ms": cursor + duration_ms,
                "shot_function": first["shot_function"],
                "commercial_purpose": first["commercial_purpose"],
                "selected_action_id": first["selected_action_id"],
                "visual_action": first["visual_action"] if len(group) == 1 else " | ".join(item["visual_action"] for item in group),
                "camera": first["camera"],
                "scene": first["scene"],
                "product_focus": product_focus or list(first.get("product_focus", [])),
                "subtitle_intent": first["subtitle_intent"],
                "voiceover_intent": first["voiceover_intent"],
                "must_keep_from_reference": must_keep or list(first.get("must_keep_from_reference", [])),
                "must_change_from_reference": must_change or list(first.get("must_change_from_reference", [])),
                "generation_risks": risks or list(first.get("generation_risks", [])),
                "source_new_shot_ids": [item["new_shot_id"] for item in group],
                "source_reference_shot_ids": [item["reference_shot_id"] for item in group],
                "generation_strategy": strategy,
            }
        )
        cursor += duration_ms
    plan_artifact["new_video_plan"]["shots"] = prepared_shots
    plan_artifact["new_video_plan"]["shot_count"] = len(prepared_shots)
    plan_artifact["new_video_plan"]["duration_ms"] = cursor
    plan_artifact["new_video_plan"]["source_reference_shot_count"] = len(shots)
    return plan_artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a new video plan duration.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--target-ms", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = prepare_plan_for_generation(load_json(args.input), args.target_ms)
    output = args.output or args.input
    atomic_write_json(output, data)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

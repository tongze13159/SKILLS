#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from common import load_json, schema_for_artifact


def _seedance_duration_sec(duration_ms: int) -> int:
    seconds = int(math.floor((duration_ms + 500) / 1000))
    return max(4, min(15, seconds))


def _format_jsonschema_errors(schema: dict[str, Any], data: dict[str, Any]) -> list[str]:
    errors = []
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{location}: {error.message}")
    return errors


def _check_timeline(shots: list[dict[str, Any]], target_ms: int | None) -> list[str]:
    errors: list[str] = []
    cursor = 0
    ids: set[str] = set()
    for index, shot in enumerate(shots):
        shot_id = shot.get("new_shot_id") or shot.get("reference_shot_id") or str(index)
        if shot_id in ids:
            errors.append(f"duplicate shot id: {shot_id}")
        ids.add(shot_id)
        if shot.get("start_ms") != cursor:
            errors.append(f"{shot_id}: start_ms must be {cursor}")
        duration = shot.get("duration_ms", 0)
        if shot.get("end_ms") != shot.get("start_ms", 0) + duration:
            errors.append(f"{shot_id}: end_ms must equal start_ms + duration_ms")
        cursor = shot.get("end_ms", cursor)
    if target_ms is not None and cursor != target_ms:
        errors.append(f"timeline ends at {cursor}ms, expected {target_ms}ms")
    return errors


def _load_if_exists(path: Path) -> dict[str, Any] | None:
    return load_json(path) if path.exists() else None


def _custom_checks(
    artifact_path: Path,
    data: dict[str, Any],
    *,
    config_path: Path | None,
    project_dir: Path | None,
) -> list[str]:
    errors: list[str] = []
    name = artifact_path.name
    config = _load_if_exists(config_path) if config_path else None

    if name == "raw_shots.json":
        errors.extend(_check_timeline(data["raw_shots"], data["video_meta"]["duration_ms"]))

    if name == "new_video_plan.json":
        plan = data["new_video_plan"]
        expected = plan["duration_ms"]
        errors.extend(_check_timeline(plan["shots"], expected))
        if plan["shot_count"] != len(plan["shots"]):
            errors.append("new_video_plan.shot_count does not match shots length")

        if project_dir:
            raw = _load_if_exists(project_dir / "output/artifacts/raw_shots.json")
            matrix = _load_if_exists(project_dir / "output/artifacts/product_action_matrix.json")
            if raw:
                ref_ids = {shot["reference_shot_id"] for shot in raw["raw_shots"]}
                for shot in plan["shots"]:
                    if shot["reference_shot_id"] not in ref_ids:
                        errors.append(f"unknown reference_shot_id: {shot['reference_shot_id']}")
            if matrix:
                action_ids = {
                    action["action_id"] for action in matrix["product_action_matrix"]
                }
                for shot in plan["shots"]:
                    if shot["selected_action_id"] not in action_ids:
                        errors.append(f"unknown selected_action_id: {shot['selected_action_id']}")

    if name == "seedance_tasks.json":
        rate = (
            config["cost_rules"]["seedance_cost_rmb_per_second"]
            if config
            else 1.0
        )
        calculated_total = 0.0
        for task in data["seedance_tasks"]:
            provider_duration_sec = task.get("seedance_duration_sec")
            if provider_duration_sec is None:
                errors.append(f"{task['task_id']}: missing seedance_duration_sec")
                continue
            expected = provider_duration_sec * rate
            if not math.isclose(task["estimated_cost_rmb"], expected, abs_tol=0.001):
                errors.append(f"{task['task_id']}: estimated cost mismatch")
            source_new_shot_ids = task.get("source_new_shot_ids") or []
            if task.get("merge_strategy") == "standalone" and len(source_new_shot_ids) != 1:
                errors.append(f"{task['task_id']}: standalone task must cover exactly one shot")
            if task.get("merge_strategy") == "adjacent_merge" and len(source_new_shot_ids) < 2:
                errors.append(f"{task['task_id']}: adjacent_merge must cover at least two shots")
            if task.get("merge_strategy") == "shot_split" and len(source_new_shot_ids) != 1:
                errors.append(f"{task['task_id']}: shot_split must cover exactly one shot")
            segments = task.get("source_segments") or []
            if task.get("merge_strategy") != "shot_split" and len(segments) != len(source_new_shot_ids):
                errors.append(f"{task['task_id']}: source_segments length mismatch")
            if task.get("merge_strategy") == "shot_split" and len(segments) != 1:
                errors.append(f"{task['task_id']}: shot_split must contain exactly one source segment")
            segment_target_total = 0
            segment_provider_cursor = 0
            for index, segment in enumerate(segments):
                trim_start = segment.get("provider_trim_start_ms", 0)
                trim_end = segment.get("provider_trim_end_ms", 0)
                if trim_start != segment_provider_cursor:
                    errors.append(f"{task['task_id']}: source_segments must be contiguous")
                if trim_end <= trim_start:
                    errors.append(f"{task['task_id']}: invalid provider trim range")
                segment_provider_cursor = trim_end
                segment_target_total += int(segment.get("target_duration_ms", 0))
                if index < len(source_new_shot_ids) and segment.get("new_shot_id") != source_new_shot_ids[index]:
                    errors.append(f"{task['task_id']}: source_segments shot order mismatch")
            if segment_target_total != task["duration_ms"]:
                errors.append(f"{task['task_id']}: source_segments target duration mismatch")
            if segment_provider_cursor != provider_duration_sec * 1000:
                errors.append(f"{task['task_id']}: provider trim timeline mismatch")
            calculated_total += task["estimated_cost_rmb"]
            image = Path(task["input_image"])
            if not image.is_absolute() and project_dir:
                image = project_dir / image
            if not image.exists():
                errors.append(f"{task['task_id']}: input image does not exist: {image}")
            input_images = task.get("input_images") or []
            if len(input_images) != len(source_new_shot_ids):
                errors.append(f"{task['task_id']}: input_images length mismatch")
            for raw_image in input_images:
                image_path = Path(raw_image)
                if not image_path.is_absolute() and project_dir:
                    image_path = project_dir / image_path
                if not image_path.exists():
                    errors.append(f"{task['task_id']}: input_images path does not exist: {image_path}")
        if not math.isclose(
            data["estimated_total_cost_rmb"], calculated_total, abs_tol=0.001
        ):
            errors.append("estimated_total_cost_rmb does not equal task sum")
        if calculated_total > data["budget_rmb"] and data["budget_status"] != "blocked":
            errors.append("budget_status must be blocked when estimate exceeds budget")

    return errors


def validate_file(
    input_path: Path | str,
    schema_path: Path | str | None = None,
    *,
    config_path: Path | str | None = None,
    project_dir: Path | str | None = None,
) -> list[str]:
    artifact_path = Path(input_path).resolve()
    schema = Path(schema_path).resolve() if schema_path else schema_for_artifact(artifact_path.name)
    data = load_json(artifact_path)
    schema_data = load_json(schema)
    errors = _format_jsonschema_errors(schema_data, data)
    errors.extend(
        _custom_checks(
            artifact_path,
            data,
            config_path=Path(config_path).resolve() if config_path else None,
            project_dir=Path(project_dir).resolve() if project_dir else None,
        )
    )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a pipeline JSON artifact.")
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--project-dir", type=Path)
    args = parser.parse_args()
    try:
        errors = validate_file(
            args.input,
            args.schema,
            config_path=args.config,
            project_dir=args.project_dir,
        )
    except Exception as exc:
        print(f"VALIDATION ERROR: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1
    print(f"VALID: {args.input}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

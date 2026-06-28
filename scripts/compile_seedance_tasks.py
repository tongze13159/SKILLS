#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from common import artifact_header, atomic_write_json, load_json, relative_to_project


PROMPT_TEMPLATE = """Generate a {duration_sec:g}-second realistic TikTok-style ecommerce product demo clip.
Start from the provided storyboard image.
Action: {start_state} -> {main_motion} -> {end_state}.
Camera: {camera_angle}, {camera_distance}, {camera_movement}.
Scene: {scene_type}, {background}.
Product must keep: {must_keep_visual_details}.
Avoid: {avoid_deformation}.
Keep reference logic: {must_keep_from_reference}.
Change from reference: {must_change_from_reference}.
Do not show a visible face, watermark, logo, unrelated objects, or original brand elements."""

MERGED_PROMPT_TEMPLATE = """Generate a {duration_sec:g}-second realistic TikTok-style ecommerce product demo clip.
Use the provided storyboard references and preserve product identity across consecutive beats.
Sequence plan:
{sequence_plan}
Keep the beats in this exact order with clean visual continuity.
Product must keep: {must_keep_visual_details}.
Avoid: {avoid_deformation}.
Keep reference logic: {must_keep_from_reference}.
Change from reference: {must_change_from_reference}.
Do not show a visible face, watermark, logo, unrelated objects, or original brand elements."""

MIN_SEEDANCE_MS = 4000
MAX_SEEDANCE_MS = 15000


def _profile_body(profile_artifact: dict[str, Any]) -> dict[str, Any]:
    product = profile_artifact["product_profile"]
    if "product_id" in product and "must_keep_visual_details" in product:
        return product
    visual_identity = product.get("visual_identity", {})
    colors = visual_identity.get("colors") if isinstance(visual_identity, dict) else []
    return {
        "product_id": product.get("product_id", "prod_001"),
        "category": "portable_pet_water_bottle",
        "shape": product.get("physical_shape", "portable_product"),
        "colors": colors,
        "materials": product.get("materials", []),
        "visible_features": product.get("visible_features", []),
        "main_selling_points": product.get("usable_actions", []),
        "usable_actions": product.get("usable_actions", []),
        "unsuitable_actions": product.get("unsuitable_actions", []),
        "must_keep_visual_details": product.get("must_keep_visual_details", product.get("visible_features", [])),
        "avoid_deformation": product.get("avoid_deformation_rules", product.get("avoid_deformation", [])),
        "physical_constraints": product.get("physical_constraints", []),
    }


def _resolve_storyboard_path(project_dir: Path, relative_path: str) -> Path:
    candidate = project_dir / relative_path
    if candidate.exists():
        return candidate
    direct = Path(relative_path)
    if direct.exists():
        return direct
    for root in (project_dir, project_dir.parent, project_dir.parent.parent):
        try:
            for match in root.rglob(Path(relative_path).name):
                if str(match).endswith(relative_path) and match.exists():
                    return match
        except StopIteration:
            continue
    raise FileNotFoundError(f"Storyboard does not exist: {candidate}")


def _seedance_duration_sec(duration_ms: int) -> int:
    seconds = int(math.floor((duration_ms + 500) / 1000))
    return max(4, min(15, seconds))


def _group_duration_ms(group: list[dict[str, Any]]) -> int:
    return sum(int(shot["duration_ms"]) for shot in group)


def _group_contains_short(group: list[dict[str, Any]]) -> bool:
    return any(int(shot["duration_ms"]) < MIN_SEEDANCE_MS for shot in group)


def _split_long_shots(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
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
            part["_split_from_long_shot"] = True
            expanded.append(part)
            cursor = part_end_ms
    return expanded


def _build_task_groups(shots: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    shots = _split_long_shots(shots)
    total_duration_ms = sum(int(shot["duration_ms"]) for shot in shots)
    if not shots:
        return []
    if total_duration_ms <= MIN_SEEDANCE_MS:
        return [shots]

    n = len(shots)
    best: list[tuple[int, int, int, int] | None] = [None] * (n + 1)
    choice: list[int | None] = [None] * (n + 1)
    best[n] = (0, 0, 0, 0)

    for start in range(n - 1, -1, -1):
        group: list[dict[str, Any]] = []
        duration_ms = 0
        for end in range(start, n):
            shot = shots[end]
            group.append(shot)
            duration_ms += int(shot["duration_ms"])
            if duration_ms > MAX_SEEDANCE_MS:
                break

            is_single = len(group) == 1
            valid = False
            if is_single:
                valid = int(group[0]["duration_ms"]) >= MIN_SEEDANCE_MS
            else:
                valid = duration_ms >= MIN_SEEDANCE_MS and _group_contains_short(group)

            if not valid:
                continue
            if best[end + 1] is None:
                continue

            merge_footprint = len(group) - 1
            absorbed_long = sum(
                1
                for candidate in group
                if int(candidate["duration_ms"]) >= MIN_SEEDANCE_MS
            ) if len(group) > 1 else 0
            provider_sec = _seedance_duration_sec(duration_ms)
            added_ms = provider_sec * 1000 - duration_ms
            tail = best[end + 1]
            score = (
                merge_footprint + tail[0],
                absorbed_long + tail[1],
                provider_sec + tail[2],
                added_ms + tail[3],
            )
            if best[start] is None or score < best[start]:
                best[start] = score
                choice[start] = end + 1

    if choice[0] is None:
        raise ValueError("Could not build a valid contiguous Seedance merge plan under duration constraints")

    groups: list[list[dict[str, Any]]] = []
    cursor = 0
    while cursor < n:
        next_cursor = choice[cursor]
        if next_cursor is None or next_cursor <= cursor:
            raise ValueError("Invalid Seedance merge plan state")
        groups.append(shots[cursor:next_cursor])
        cursor = next_cursor
    return groups


def _sequence_plan(group: list[dict[str, Any]], actions: dict[str, dict[str, Any]]) -> str:
    lines = []
    for index, shot in enumerate(group, start=1):
        action = actions[shot["selected_action_id"]]
        lines.append(
            f"Beat {index} (@Image{index}): {action['start_state']} -> {action['main_motion']} -> {action['end_state']}; "
            f"camera {shot['camera']['angle']}, {shot['camera']['distance']}, {shot['camera']['movement']}; "
            f"scene {shot['scene']['type']}, {shot['scene']['background']}."
        )
    return "\n".join(lines)


def _segment_timeline(group: list[dict[str, Any]], provider_duration_sec: int) -> list[dict[str, Any]]:
    provider_total_ms = provider_duration_sec * 1000
    original_total_ms = _group_duration_ms(group)
    scale = provider_total_ms / original_total_ms if original_total_ms else 1.0
    provider_cursor = 0
    segments: list[dict[str, Any]] = []
    for index, shot in enumerate(group):
        target_duration_ms = int(shot["duration_ms"])
        if index == len(group) - 1:
            provider_duration_ms = provider_total_ms - provider_cursor
        else:
            provider_duration_ms = max(
                1, int(round(target_duration_ms * scale))
            )
        segment = {
            "new_shot_id": shot["new_shot_id"],
            "reference_shot_id": shot["reference_shot_id"],
            "target_start_ms": int(shot["start_ms"]),
            "target_end_ms": int(shot["end_ms"]),
            "target_duration_ms": target_duration_ms,
            "provider_trim_start_ms": provider_cursor,
            "provider_trim_end_ms": provider_cursor + provider_duration_ms,
        }
        if shot.get("_split_from_long_shot"):
            segment["split_index"] = int(shot["_split_index"])
            segment["split_total"] = int(shot["_split_total"])
            segment["source_long_shot"] = True
        provider_cursor += provider_duration_ms
        segments.append(segment)
    segments[-1]["provider_trim_end_ms"] = provider_total_ms
    return segments


def compile_tasks(
    *,
    config: dict[str, Any],
    plan_artifact: dict[str, Any],
    profile_artifact: dict[str, Any],
    matrix_artifact: dict[str, Any],
    storyboard_artifact: dict[str, Any],
    project_dir: Path,
) -> dict[str, Any]:
    product = _profile_body(profile_artifact)
    actions = {
        action["action_id"]: action
        for action in matrix_artifact["product_action_matrix"]
    }
    storyboards = {
        item["new_shot_id"]: item
        for item in storyboard_artifact["storyboards"]
        if item["selected"]
    }
    rate = config["cost_rules"]["seedance_cost_rmb_per_second"]
    tasks = []
    groups = _build_task_groups(plan_artifact["new_video_plan"]["shots"])
    for group_index, group in enumerate(groups, start=1):
        first_shot = group[0]
        first_action = actions[first_shot["selected_action_id"]]
        group_storyboards = []
        for item in group:
            storyboard = storyboards.get(item["new_shot_id"])
            if storyboard is None:
                raise ValueError(f"No selected storyboard for {item['new_shot_id']}")
            group_storyboards.append(storyboard)
        image_paths = [
            _resolve_storyboard_path(project_dir, storyboard["image_path"])
            for storyboard in group_storyboards
        ]
        image_path = image_paths[0]
        merged_duration_ms = _group_duration_ms(group)
        provider_duration_sec = _seedance_duration_sec(merged_duration_ms)
        estimated = round(provider_duration_sec * rate, 4)
        fallback_ids = [
            actions[item["selected_action_id"]].get("fallback_action_id")
            for item in group
            if actions[item["selected_action_id"]].get("fallback_action_id")
        ]
        split_only = len(group) == 1 and bool(group[0].get("_split_from_long_shot"))
        merged = len(group) > 1
        source_new_shot_ids = [item["new_shot_id"] for item in group]
        source_reference_shot_ids = [item["reference_shot_id"] for item in group]
        source_action_ids = [item["selected_action_id"] for item in group]
        keep_logic = []
        change_logic = []
        for item in group:
            for text in item["must_keep_from_reference"]:
                if text not in keep_logic:
                    keep_logic.append(text)
            for text in item["must_change_from_reference"]:
                if text not in change_logic:
                    change_logic.append(text)
        negative_tokens: list[str] = []
        for item in group:
            for token in actions[item["selected_action_id"]]["avoid"]:
                if token not in negative_tokens:
                    negative_tokens.append(token)
        if merged:
            prompt = MERGED_PROMPT_TEMPLATE.format(
                duration_sec=provider_duration_sec,
                sequence_plan=_sequence_plan(group, actions),
                must_keep_visual_details=", ".join(product["must_keep_visual_details"]),
                avoid_deformation=", ".join(product["avoid_deformation"]),
                must_keep_from_reference=", ".join(keep_logic),
                must_change_from_reference=", ".join(change_logic),
            )
        else:
            prompt = PROMPT_TEMPLATE.format(
                duration_sec=provider_duration_sec,
                start_state=first_action["start_state"],
                main_motion=first_action["main_motion"],
                end_state=first_action["end_state"],
                camera_angle=first_shot["camera"]["angle"],
                camera_distance=first_shot["camera"]["distance"],
                camera_movement=first_shot["camera"]["movement"],
                scene_type=first_shot["scene"]["type"],
                background=first_shot["scene"]["background"],
                must_keep_visual_details=", ".join(product["must_keep_visual_details"]),
                avoid_deformation=", ".join(product["avoid_deformation"]),
                must_keep_from_reference=", ".join(keep_logic),
                must_change_from_reference=", ".join(change_logic),
            )
        tasks.append(
            {
                "task_id": f"sd_grp_{group_index:03d}",
                "project_id": config["project_id"],
                "new_shot_id": first_shot["new_shot_id"],
                "reference_shot_id": first_shot["reference_shot_id"],
                "product_id": product["product_id"],
                "action_id": first_action["action_id"],
                "duration_ms": merged_duration_ms,
                "resolution": config["video_specs"]["target_resolution"],
                "aspect_ratio": config["video_specs"]["aspect_ratio"],
                "fps": config["video_specs"]["fps"],
                "input_image": str(image_path),
                "input_images": [str(path) for path in image_paths],
                "prompt": prompt,
                "negative_prompt": (
                    "no visible face, no watermark, no logo, no copied brand elements, "
                    + ", ".join(product["avoid_deformation"] + negative_tokens)
                ),
                "camera": first_shot["camera"],
                "motion": {
                    "start_state": first_action["start_state"],
                    "main_motion": first_action["main_motion"],
                    "end_state": actions[group[-1]["selected_action_id"]]["end_state"],
                },
                "product_consistency_rules": product["must_keep_visual_details"],
                "difference_rules": change_logic,
                "seedance_duration_sec": provider_duration_sec,
                "merge_strategy": "adjacent_merge" if merged else "shot_split" if split_only else "standalone",
                "source_new_shot_ids": source_new_shot_ids,
                "source_reference_shot_ids": source_reference_shot_ids,
                "source_action_ids": source_action_ids,
                "source_segments": _segment_timeline(group, provider_duration_sec),
                "fallback": {
                    "fallback_action_id": fallback_ids[0] if fallback_ids else None,
                    "fallback_action_ids": fallback_ids,
                    "fallback_prompt_patch": (
                        "Use the declared low-risk fallback action sequence."
                        if fallback_ids
                        else "No further fallback is available; stop for human review."
                    ),
                },
                "estimated_cost_rmb": estimated,
            }
        )
    total = round(sum(item["estimated_cost_rmb"] for item in tasks), 4)
    maximum = config["cost_rules"]["max_total_cost_rmb"]
    warning = config["cost_rules"]["warn_total_cost_rmb"]
    status = "blocked" if total > maximum else "warning" if total > warning else "ok"
    return {
        **artifact_header(
            config["project_id"],
            "seedance_tasks",
            [
                "new_video_plan.json",
                "product_profile.json",
                "product_action_matrix.json",
                "storyboard_manifest.json",
                "storyboard_precheck.json",
            ],
        ),
        "seedance_tasks": tasks,
        "estimated_total_cost_rmb": total,
        "budget_rmb": maximum,
        "budget_status": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile deterministic Seedance tasks.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--product-profile", type=Path, required=True)
    parser.add_argument("--action-matrix", type=Path, required=True)
    parser.add_argument("--storyboards", type=Path, required=True)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = compile_tasks(
        config=load_json(args.config),
        plan_artifact=load_json(args.plan),
        profile_artifact=load_json(args.product_profile),
        matrix_artifact=load_json(args.action_matrix),
        storyboard_artifact=load_json(args.storyboards),
        project_dir=args.project_dir.resolve(),
    )
    atomic_write_json(args.output, data)
    print(args.output)
    if data["budget_status"] == "blocked":
        print("BLOCKED: estimated cost exceeds budget")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

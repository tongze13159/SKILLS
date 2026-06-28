#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from adapters import MockAdapter
from adapters.real_api import (
    byteplus_seedance_run,
    elevenlabs_tts,
    fal_run_json,
    gemini_generate_json,
    gemini_video_json,
    load_prompt,
    openai_chat_json,
    openai_edit_image,
    openai_generate_image,
    openai_vision_json,
    openai_transcribe,
)
from common import (
    artifact_header,
    atomic_write_json,
    load_json,
    missing_api_keys,
    output_path,
    schema_for_artifact,
    relative_to_project,
    runtime_dirs,
    stable_hash,
)
from compile_seedance_tasks import compile_tasks
from dry_run_fixture import (
    build_action_matrix,
    build_audio,
    build_final_manifest,
    build_input_manifest,
    build_new_video_plan,
    build_precheck,
    build_render_plan,
    build_scripts,
    build_storyboard_prompts,
    build_storyboards,
    build_strategy,
    build_transfer,
    build_video_clips,
    build_voiceover_assets,
    read_artifact,
    write_artifact,
)
from local_analysis import (
    build_real_raw_shots,
    build_real_reference_visual_analysis,
    infer_product_profile,
)
from normalize_duration import prepare_plan_for_generation
from validate_artifact import validate_file


STEPS = [
    "01_ingest_inputs",
    "02_preprocess_video",
    "03_extract_subtitles",
    "04_transcribe_voice",
    "05_reference_visual_analysis",
    "06_reference_shot_strategy",
    "07_product_profile",
    "08_product_action_matrix",
    "09_action_transfer",
    "10_new_video_plan",
    "11_subtitle_voiceover",
    "12_audio_asset_manifest",
    "13_storyboard_prompts",
    "14_generate_storyboards",
    "15_storyboard_precheck",
    "16_compile_seedance_tasks",
    "17_generate_video_clips",
    "18_generate_voiceover",
    "19_render_final_video",
]

STEP_OUTPUTS = {
    "01_ingest_inputs": ["input_manifest.json"],
    "02_preprocess_video": ["raw_shots.json"],
    "03_extract_subtitles": ["ocr_subtitles.json"],
    "04_transcribe_voice": ["voice_transcript.json"],
    "05_reference_visual_analysis": ["reference_visual_analysis.json"],
    "06_reference_shot_strategy": ["reference_shot_strategy.json"],
    "07_product_profile": ["product_profile.json"],
    "08_product_action_matrix": ["product_action_matrix.json"],
    "09_action_transfer": ["action_transfer_plan.json"],
    "10_new_video_plan": ["new_video_plan.json"],
    "11_subtitle_voiceover": ["subtitle_script.json", "voiceover_script.json"],
    "12_audio_asset_manifest": ["audio_asset_manifest.json"],
    "13_storyboard_prompts": ["storyboard_prompts.json"],
    "14_generate_storyboards": ["storyboard_manifest.json"],
    "15_storyboard_precheck": ["storyboard_precheck.json"],
    "16_compile_seedance_tasks": ["seedance_tasks.json"],
    "17_generate_video_clips": ["video_clips_manifest.json"],
    "18_generate_voiceover": ["voiceover_asset_manifest.json"],
    "19_render_final_video": ["render_plan.json", "final_video_manifest.json"],
}

DEFAULT_API_UNIT_PRICES = {
    "openai_stt_rmb_per_minute": 0.045,
    "gemini_video_rmb_per_call": 0.9,
    "openai_text_rmb_per_call": 0.12,
    "openai_vision_rmb_per_image": 0.08,
    "openai_image_generate_rmb_per_call": 0.35,
    "openai_image_edit_rmb_per_call": 0.4,
    "flux_image_rmb_per_call": 0.6,
    "elevenlabs_tts_rmb_per_1k_chars": 0.08,
}


def _initial_state(config: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    return {
        **artifact_header(config["project_id"], "pipeline_state"),
        "status": "pending",
        "dry_run": dry_run,
        "current_step": None,
        "steps": {},
        "total_cost_rmb": 0.0,
        "max_budget_rmb": config["cost_rules"]["max_total_cost_rmb"],
        "error": None,
    }


def _initial_ledger(config: dict[str, Any]) -> dict[str, Any]:
    return {
        **artifact_header(config["project_id"], "cost_ledger"),
        "budget_rmb": config["cost_rules"]["max_total_cost_rmb"],
        "warn_budget_rmb": config["cost_rules"]["warn_total_cost_rmb"],
        "spent_rmb": 0.0,
        "estimated_rmb": 0.0,
        "items": [],
    }


def _strict_real_mode(config: dict[str, Any]) -> bool:
    return bool(config.get("generation_constraints", {}).get("strict_real_mode", True))


def _unit_price(config: dict[str, Any], key: str, default: float) -> float:
    prices = config.get("cost_rules", {}).get("api_unit_prices", {})
    if isinstance(prices, dict):
        value = prices.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return float(default)


def _ensure_call_budget(
    config: dict[str, Any],
    ledger: dict[str, Any],
    estimated_cost_rmb: float,
    label: str,
) -> None:
    if not config["cost_rules"].get("stop_on_budget_exceeded", True):
        return
    next_total = round(float(ledger.get("spent_rmb", 0.0)) + float(estimated_cost_rmb), 4)
    max_budget = float(config["cost_rules"]["max_total_cost_rmb"])
    if next_total > max_budget:
        raise RuntimeError(
            f"{label} would exceed budget: next_total_rmb={next_total}, budget_rmb={max_budget}"
        )


def _tracked_api_call(
    *,
    config: dict[str, Any],
    ledger: dict[str, Any],
    step: str,
    provider: str,
    model: str,
    operation: str,
    unit_label: str,
    unit_price_rmb: float,
    quantity: float,
    call: Callable[[], Any],
) -> tuple[Any, float]:
    estimated_cost = round(max(quantity, 0.0) * max(unit_price_rmb, 0.0), 4)
    label = f"{step} | {provider}/{model} | {operation}"
    _ensure_call_budget(config, ledger, estimated_cost, label)
    print(
        f"API BEFORE | step={step} | provider={provider} | model={model} | operation={operation} | "
        f"unit={unit_label} | unit_price_rmb={unit_price_rmb:.4f} | quantity={quantity:.4f} | "
        f"estimated_cost_rmb={estimated_cost:.4f} | spent_before_rmb={float(ledger.get('spent_rmb', 0.0)):.4f}"
    )
    try:
        result = call()
    except Exception:
        print(
            f"API FAILED | step={step} | provider={provider} | model={model} | operation={operation} | "
            f"estimated_cost_rmb={estimated_cost:.4f} | spent_after_rmb={float(ledger.get('spent_rmb', 0.0)):.4f}",
            file=sys.stderr,
        )
        raise
    actual_cost = estimated_cost
    ledger["spent_rmb"] = round(float(ledger.get("spent_rmb", 0.0)) + actual_cost, 4)
    print(
        f"API AFTER | step={step} | provider={provider} | model={model} | operation={operation} | "
        f"actual_cost_rmb={actual_cost:.4f} | spent_after_rmb={float(ledger.get('spent_rmb', 0.0)):.4f}"
    )
    return result, actual_cost


def _dump_debug_json(project_dir: Path, step: str, name: str, data: Any) -> Path:
    debug_dir = runtime_dirs(project_dir)["logs"] / "debug_api"
    debug_dir.mkdir(parents=True, exist_ok=True)
    target = debug_dir / f"{step}_{name}.json"
    atomic_write_json(target, data)
    return target


def _schema(name: str) -> dict[str, Any]:
    return load_json(schema_for_artifact(name))


def _prompt(name: str) -> str:
    return load_prompt(name)


def _json_payload(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _extract_audio(reference_video: Path, project_dir: Path) -> Path:
    audio_dir = runtime_dirs(project_dir)["audio"]
    audio_path = audio_dir / "reference_audio.mp3"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(reference_video),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-q:a",
        "2",
        str(audio_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return audio_path


def _download_to(url: str, target: Path) -> Path:
    import requests

    target.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=300)
            response.raise_for_status()
            target.write_bytes(response.content)
            return target
        except Exception as exc:
            last_error = exc
            if attempt == 2:
                raise
    raise RuntimeError(f"download failed for {url}: {last_error}")


def _file_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _resolve_input_image(project_dir: Path, image_value: str) -> Path:
    image_path = Path(image_value)
    if image_path.is_absolute():
        return image_path
    candidate = (project_dir / image_path).resolve()
    if candidate.exists():
        return candidate
    return image_path.resolve()


def _seedance_duration_sec(duration_ms: int) -> int:
    seconds = int((duration_ms + 500) // 1000)
    return max(4, min(15, seconds))


def _video_clips_manifest_data(
    config: dict[str, Any],
    model_id: str,
    clips: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        **artifact_header(
            config["project_id"],
            "video_clips_manifest",
            ["seedance_tasks.json"],
            provider="volcengine",
            model=model_id,
            temperature=0.0,
        ),
        "video_clips": clips,
    }


def _resolve_model(model: str, *, provider: str) -> str:
    if provider == "gemini" and model == "gemini-video":
        return os.environ.get("GEMINI_VIDEO_MODEL", "gemini-2.5-flash")
    if provider == "fal":
        mapping = {
            "flux-2-pro": "fal-ai/flux-pro/v1.1",
            "flux-2-klein": "fal-ai/flux/dev",
        }
        return mapping.get(model, model)
    return model


def _fal_image_size(aspect_ratio: str) -> str:
    mapping = {
        "9:16": "portrait_16_9",
        "16:9": "landscape_16_9",
        "1:1": "square",
    }
    return mapping.get(aspect_ratio, "portrait_16_9")


def _openai_image_size(aspect_ratio: str) -> str:
    mapping = {
        "9:16": "1024x1536",
        "16:9": "1536x1024",
        "1:1": "1024x1024",
    }
    return mapping.get(aspect_ratio, "1024x1536")


def _openai_json(config: dict[str, Any], model_key: str, prompt_name: str, payload: dict[str, Any], schema_name: str) -> dict[str, Any]:
    model = config["model_defaults"][model_key]
    return openai_chat_json(
        model=model,
        system_prompt=_prompt(prompt_name),
        user_prompt=_json_payload(payload),
        schema=_schema(schema_name),
        temperature=0.2,
    )


def _openai_vision(config: dict[str, Any], model_key: str, prompt_name: str, payload: dict[str, Any], image_paths: list[Path], schema_name: str) -> dict[str, Any]:
    model = config["model_defaults"][model_key]
    return openai_vision_json(
        model=model,
        system_prompt=_prompt(prompt_name),
        user_prompt=_json_payload(payload),
        image_paths=image_paths,
        schema=_schema(schema_name),
        temperature=0.2,
    )


def _normalize_reference_strategy_payload(
    strategy: dict[str, Any] | list[dict[str, Any]],
    raw_artifact: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if isinstance(strategy, list):
        items = strategy
        overall_structure = None
    else:
        items = (
            strategy.get("reference_shots")
            or strategy.get("reference_shot_strategies")
            or strategy.get("reference_shot_strategy")
            or strategy.get("shots")
            or strategy.get("shot_strategies")
            or []
        )
        overall_structure = strategy.get("overall_structure")
    if not isinstance(items, list):
        items = []
    raw_ids = [shot["reference_shot_id"] for shot in raw_artifact["raw_shots"]]
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        shot_id = item.get("reference_shot_id") or item.get("shot_id") or item.get("id")
        if not shot_id and index < len(raw_ids):
            shot_id = raw_ids[index]
        normalized.append(
            {
                "reference_shot_id": shot_id,
                "shot_function": item.get("shot_function") or item.get("function") or item.get("shot_role") or "function_demo",
                "commercial_purpose": item.get("commercial_purpose") or item.get("purpose") or "Demonstrate a truthful product benefit.",
                "viewer_psychology": item.get("viewer_psychology") or item.get("psychology") or "confidence",
                "why_it_works": item.get("why_it_works") or item.get("reason") or item.get("why") or "Clear product action reduces ambiguity.",
                "remake_value": item.get("remake_value") or item.get("priority") or "high",
                "must_keep_logic": item.get("must_keep_logic") or item.get("keep_logic") or item.get("must_keep") or ["single clear action"],
                "must_change": item.get("must_change") or item.get("change_rules") or item.get("must_change_from_reference") or ["exact wording", "background", "brand elements"],
            }
        )
    normalized = [item for item in normalized if item.get("reference_shot_id")]
    return normalized, overall_structure


def _normalize_action_matrix_payload(matrix: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(matrix, list):
        items = matrix
    else:
        items = (
            matrix.get("product_action_matrix")
            or matrix.get("action_matrix")
            or matrix.get("actions")
            or matrix.get("matrix")
            or []
        )
    if not isinstance(items, list):
        items = []
    id_map: dict[str, str] = {}
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("action_id") or item.get("id") or item.get("action_name") or item.get("name") or f"raw_{index}")
        suffix = "_fallback" if "fallback" in raw_id.lower() else ""
        id_map[raw_id] = f"act_{index:03d}{suffix}"
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        camera = item.get("best_camera") or item.get("camera") or {}
        if not isinstance(camera, dict):
            camera = {}
        raw_id = str(item.get("action_id") or item.get("id") or item.get("action_name") or item.get("name") or f"raw_{index}")
        visual_clarity = str(item.get("visual_clarity") or item.get("clarity") or "high").lower()
        if visual_clarity in {"very_high", "medium_high"}:
            visual_clarity = "high" if visual_clarity == "very_high" else "medium"
        if visual_clarity not in {"low", "medium", "high"}:
            visual_clarity = "high"
        fallback_raw = item.get("fallback_action_id")
        suitable_functions = item.get("suitable_shot_functions") or item.get("shot_functions") or ["function_demo"]
        if not isinstance(suitable_functions, list):
            suitable_functions = [suitable_functions]
        normalized_functions: list[str] = []
        for func in suitable_functions:
            if isinstance(func, dict):
                value = func.get("shot_function") or func.get("function") or func.get("reference_shot_id")
            else:
                value = func
            if value:
                normalized_functions.append(str(value))
        if not normalized_functions:
            normalized_functions = ["function_demo"]
        normalized.append(
            {
                "action_id": id_map.get(raw_id, f"act_{index:03d}"),
                "action_name": item.get("action_name") or item.get("name") or f"action_{index:03d}",
                "difficulty": item.get("difficulty") or item.get("execution_difficulty") or "medium",
                "video_generation_risk": item.get("video_generation_risk") or item.get("generation_risk") or item.get("risk") or "medium",
                "visual_clarity": visual_clarity,
                "suitable_shot_functions": normalized_functions,
                "required_props": item.get("required_props") or item.get("props") or ["product", "hand"],
                "best_camera": {
                    "angle": camera.get("angle", "top_down_45"),
                    "distance": camera.get("distance", "close_up"),
                },
                "start_state": item.get("start_state") or item.get("initial_state") or "product is clearly visible",
                "main_motion": item.get("main_motion") or item.get("motion") or item.get("action") or "show a clear product motion",
                "end_state": item.get("end_state") or item.get("result_state") or "product remains readable",
                "avoid": item.get("avoid") or item.get("negative_rules") or ["no visible face"],
                "fallback_action_id": id_map.get(str(fallback_raw), None) if fallback_raw else None,
            }
        )
    return normalized


def _normalize_action_transfer_payload(transfer: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(transfer, list):
        items = transfer
    else:
        items = (
            transfer.get("action_transfer_plan")
            or transfer.get("transfer_plan")
            or transfer.get("action_transfers")
            or transfer.get("transfers")
            or transfer.get("shot_mappings")
            or transfer.get("items")
            or []
        )
    if not isinstance(items, list):
        items = []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        def _normalize_risks(raw_risks: Any) -> list[str]:
            if isinstance(raw_risks, dict):
                normalized_risks: list[str] = []
                matrix_risk = str(raw_risks.get("matrix_risk") or "").strip()
                if matrix_risk:
                    normalized_risks.append(f"matrix_risk: {matrix_risk}")
                for note in raw_risks.get("risk_notes") or []:
                    if note:
                        normalized_risks.append(str(note))
                mitigations = [str(m).strip() for m in (raw_risks.get("mitigation") or []) if str(m).strip()]
                if mitigations:
                    normalized_risks.append("Mitigation: " + " | ".join(mitigations))
                return normalized_risks or ["no visible face"]
            if isinstance(raw_risks, list):
                normalized_risks = []
                for risk in raw_risks:
                    if isinstance(risk, dict):
                        risk_text = str(risk.get("risk") or "").strip()
                        mitigation_text = str(risk.get("mitigation") or "").strip()
                        if risk_text and mitigation_text:
                            normalized_risks.append(f"{risk_text} Mitigation: {mitigation_text}")
                        elif risk_text:
                            normalized_risks.append(risk_text)
                        elif mitigation_text:
                            normalized_risks.append(f"Mitigation: {mitigation_text}")
                    elif risk:
                        normalized_risks.append(str(risk))
                return normalized_risks or ["no visible face"]
            if raw_risks:
                return [str(raw_risks)]
            return ["no visible face"]

        reference_shot_id = item.get("reference_shot_id") or item.get("shot_id")
        reference_action = item.get("reference_action") or item.get("source_action") or item.get("reference_function") or item.get("reference_action_summary") or "demonstrate reference product function"
        keep = item.get("keep") or item.get("must_keep") or item.get("what_to_keep") or ["close product focus"]
        change = item.get("change") or item.get("must_change") or item.get("what_to_change") or ["mechanics", "background", "wording"]
        physical_reason = item.get("physical_reason") or item.get("reason") or item.get("physical_reasoning") or "Action must stay physically valid for the new product."
        negative_prompt_rules = item.get("negative_prompt_rules") or item.get("negative_rules") or ["no visible face"]
        risks = _normalize_risks(item.get("video_generation_risk") or item.get("risks") or item.get("generation_risks"))

        mapped_actions = item.get("mapped_actions")
        if isinstance(mapped_actions, list) and mapped_actions:
            for mapped_action in mapped_actions:
                if not isinstance(mapped_action, dict):
                    continue
                sub_reference_action = mapped_action.get("reference_sub_action")
                normalized.append(
                    {
                        "reference_shot_id": reference_shot_id,
                        "reference_action": (
                            f"{reference_action} / {sub_reference_action}"
                            if sub_reference_action
                            else reference_action
                        ),
                        "new_action_id": mapped_action.get("mapped_action_id") or mapped_action.get("new_action_id") or mapped_action.get("target_action_id") or mapped_action.get("action_id"),
                        "new_product_action": mapped_action.get("mapped_action_name") or mapped_action.get("new_product_action") or mapped_action.get("target_action") or mapped_action.get("action_description") or "show a physically valid product action",
                        "action_type": mapped_action.get("physical_legal_status") or mapped_action.get("legal_status") or item.get("action_type") or item.get("transfer_type") or "functionally_equivalent",
                        "keep": keep,
                        "change": change,
                        "physical_reason": physical_reason,
                        "video_generation_risk": risks,
                        "negative_prompt_rules": negative_prompt_rules,
                        "fallback_action_id": mapped_action.get("fallback_action_id"),
                    }
                )
            continue

        normalized.append(
            {
                "reference_shot_id": reference_shot_id,
                "reference_action": reference_action,
                "new_action_id": item.get("new_action_id") or item.get("target_action_id") or item.get("action_id") or item.get("mapped_action_id"),
                "new_product_action": item.get("new_product_action") or item.get("target_action") or item.get("action_description") or item.get("mapped_action_name") or "show a physically valid product action",
                "action_type": item.get("action_type") or item.get("transfer_type") or item.get("legal_status") or "functionally_equivalent",
                "keep": keep,
                "change": change,
                "physical_reason": physical_reason,
                "video_generation_risk": risks,
                "negative_prompt_rules": negative_prompt_rules,
            }
        )
    return [item for item in normalized if item.get("reference_shot_id") and item.get("new_action_id")]


def _normalize_new_video_plan_payload(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    new_video_plan = plan.get("new_video_plan") if isinstance(plan.get("new_video_plan"), dict) else plan
    if not isinstance(new_video_plan, dict):
        return {}
    normalized = dict(new_video_plan)
    video_meta = normalized.get("video_meta")
    video_spec = normalized.get("video_spec")
    deliverable = normalized.get("deliverable")
    if not isinstance(normalized.get("shots"), list) and isinstance(normalized.get("timeline"), list):
        normalized["shots"] = normalized["timeline"]
    if not isinstance(normalized.get("shots"), list) and isinstance(normalized.get("shot_plan"), list):
        normalized["shots"] = normalized["shot_plan"]
    if "duration_ms" not in normalized and isinstance(video_meta, dict) and "duration_ms" in video_meta:
        normalized["duration_ms"] = video_meta["duration_ms"]
    if "duration_ms" not in normalized and isinstance(video_spec, dict) and "duration_ms" in video_spec:
        normalized["duration_ms"] = video_spec["duration_ms"]
    if "duration_ms" not in normalized and isinstance(deliverable, dict) and "duration_ms" in deliverable:
        normalized["duration_ms"] = deliverable["duration_ms"]
    if "shot_count" not in normalized and isinstance(video_meta, dict) and "shot_count" in video_meta:
        normalized["shot_count"] = video_meta["shot_count"]
    if "shot_count" not in normalized and isinstance(normalized.get("shots"), list):
        normalized["shot_count"] = len(normalized["shots"])
    if "source_reference_shot_count" not in normalized and isinstance(video_meta, dict) and "shot_count" in video_meta:
        normalized["source_reference_shot_count"] = video_meta["shot_count"]
    if "source_reference_shot_count" not in normalized and isinstance(normalized.get("shots"), list):
        reference_shot_ids = {
            item.get("reference_shot_id")
            for item in normalized["shots"]
            if isinstance(item, dict) and item.get("reference_shot_id")
        }
        normalized["source_reference_shot_count"] = len(reference_shot_ids)
    if isinstance(normalized.get("shots"), list):
        def _map_shot_function(raw_value: Any) -> str:
            text = str(raw_value or "").lower()
            if any(token in text for token in ("hook", "opening")):
                return "hook"
            if any(token in text for token in ("pain", "problem")):
                return "pain_point"
            if any(token in text for token in ("reveal", "display")):
                return "product_reveal"
            if any(token in text for token in ("proof", "leak", "trust")):
                return "proof"
            if "compare" in text:
                return "comparison"
            if any(token in text for token in ("scenario", "walk", "outdoor", "travel")):
                return "scenario"
            if "transition" in text:
                return "transition"
            if any(token in text for token in ("cta", "call to action", "shop", "buy")):
                return "cta"
            return "function_demo"

        normalized_shots: list[dict[str, Any]] = []
        for index, shot in enumerate(normalized["shots"], start=1):
            if not isinstance(shot, dict):
                continue
            product_focus = shot.get("product_focus")
            product_focus_dict = product_focus if isinstance(product_focus, dict) else {}
            if isinstance(product_focus, dict):
                focus_items: list[str] = []
                primary_feature = product_focus.get("primary_feature")
                if primary_feature:
                    focus_items.append(str(primary_feature))
                for key in ("must_show_details", "start_state", "main_motion", "end_state"):
                    value = product_focus.get(key)
                    if isinstance(value, list):
                        focus_items.extend(str(item) for item in value if item)
                    elif value:
                        focus_items.append(str(value))
                product_focus = focus_items
            elif isinstance(product_focus, list):
                product_focus = [str(item) for item in product_focus if item]
            elif product_focus:
                product_focus = [str(product_focus)]
            else:
                product_focus = []
            if not product_focus:
                product_focus = ["product action clarity"]

            risk = shot.get("risk")
            generation_risks: list[str] = []
            if isinstance(risk, dict):
                for key in ("video_generation_risk", "claim_risk", "product_deformation_risk"):
                    value = risk.get(key)
                    if value:
                        generation_risks.append(f"{key}: {value}")
                for key in ("risks", "risk_factors"):
                    value = risk.get(key)
                    if isinstance(value, list):
                        generation_risks.extend(str(item) for item in value if item)
                    elif value:
                        generation_risks.append(str(value))
                for key in ("mitigation", "negative_prompt_rules"):
                    value = risk.get(key)
                    if isinstance(value, list):
                        generation_risks.extend(str(item) for item in value if item)
                    elif value:
                        generation_risks.append(str(value))
            elif isinstance(risk, list):
                generation_risks = [str(item) for item in risk if item]
            elif risk:
                generation_risks = [str(risk)]

            onscreen_text = shot.get("on_screen_text")
            if not isinstance(onscreen_text, dict):
                onscreen_text = shot.get("onscreen_text") if isinstance(shot.get("onscreen_text"), dict) else {}
            if not isinstance(onscreen_text, dict) or not onscreen_text:
                onscreen_text = shot.get("text_overlay") if isinstance(shot.get("text_overlay"), dict) else onscreen_text
            copy_block = shot.get("copy") if isinstance(shot.get("copy"), dict) else {}
            action_block = shot.get("action") if isinstance(shot.get("action"), dict) else {}
            voiceover = shot.get("voiceover") if isinstance(shot.get("voiceover"), dict) else {}
            originality = shot.get("originality") if isinstance(shot.get("originality"), dict) else {}
            scene = shot.get("scene") if isinstance(shot.get("scene"), dict) else {}
            camera = shot.get("camera") if isinstance(shot.get("camera"), dict) else {}
            selected_action_id = (
                shot.get("selected_action_id")
                or shot.get("new_action_id")
                or shot.get("action_id")
                or product_focus_dict.get("action_id")
            )
            shot_function = _map_shot_function(
                shot.get("shot_function")
                or shot.get("commercial_function")
                or shot.get("structure_role")
                or shot.get("structure_phase")
            )

            normalized_shots.append(
                {
                    "new_shot_id": shot.get("new_shot_id") or shot.get("shot_id") or f"new_{index:03d}",
                    "reference_shot_id": shot.get("reference_shot_id") or shot.get("source_reference_shot_id") or f"ref_{index:03d}",
                    "duration_ms": int(shot.get("duration_ms") or 1000),
                    "start_ms": int(shot.get("start_ms") or 0),
                    "end_ms": int(shot.get("end_ms") or ((shot.get("start_ms") or 0) + (shot.get("duration_ms") or 1000))),
                    "shot_function": shot_function,
                    "commercial_purpose": shot.get("commercial_purpose") or shot.get("commercial_function") or shot.get("structure_phase") or "Create an original ecommerce product demonstration shot.",
                    "selected_action_id": str(selected_action_id or "act_001"),
                    "visual_action": shot.get("visual_action")
                    or product_focus_dict.get("main_motion")
                    or product_focus_dict.get("action_detail")
                    or action_block.get("motion")
                    or shot.get("action_summary")
                    or "show the product action clearly",
                    "camera": {
                        "angle": str(camera.get("angle") or "eye_level"),
                        "distance": str(camera.get("distance") or camera.get("framing") or "close_up"),
                        "movement": str(camera.get("movement") or "static"),
                    },
                    "scene": {
                        "type": str(scene.get("type") or scene.get("location") or scene.get("location_id") or "product_demo_scene"),
                        "background": str(scene.get("background") or "clean product-focused background"),
                    },
                    "product_focus": product_focus,
                    "subtitle_intent": shot.get("subtitle_intent") or onscreen_text.get("text") or copy_block.get("on_screen_text") or "short original benefit caption",
                    "voiceover_intent": shot.get("voiceover_intent") or voiceover.get("text") or copy_block.get("voiceover") or "natural product-selling narration",
                    "must_keep_from_reference": shot.get("must_keep_from_reference")
                    or (plan.get("remake_directive") or {}).get("preserve")
                    or ["fast pacing", "clear product action"],
                    "must_change_from_reference": shot.get("must_change_from_reference")
                    or (plan.get("remake_directive") or {}).get("change")
                    or originality.get("changed_elements")
                    or ["exact wording", "brand marks", "background"],
                    "generation_risks": shot.get("generation_risks") or generation_risks or ["avoid product deformation"],
                }
            )
        normalized["shots"] = normalized_shots
    return {
        "project_id": normalized.get("project_id") or plan.get("project_id") or "remake_campaign_001",
        "duration_ms": int(normalized.get("duration_ms") or 1000),
        "shot_count": int(normalized.get("shot_count") or len(normalized.get("shots") or [])),
        "target_language": (
            (normalized.get("localization_intent") or {}).get("target_locale")
            if isinstance(normalized.get("localization_intent"), dict)
            else None
        )
        or (deliverable.get("target_locale") if isinstance(deliverable, dict) else None)
        or (deliverable.get("language") if isinstance(deliverable, dict) else None)
        or (video_spec.get("language") if isinstance(video_spec, dict) else None)
        or "ms-MY",
        "voice_gender": "female",
        "shots": normalized.get("shots") or [],
        "source_reference_shot_count": int(normalized.get("source_reference_shot_count") or len({
            item.get("reference_shot_id")
            for item in (normalized.get("shots") or [])
            if isinstance(item, dict) and item.get("reference_shot_id")
        }) or 1),
    }


def _normalize_subtitle_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("subtitle_script") or payload.get("subtitles")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    shots = payload.get("shots")
    if isinstance(shots, list):
        normalized: list[dict[str, Any]] = []
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            text = shot.get("subtitle") or shot.get("text")
            if not text:
                continue
            normalized.append(
                {
                    "new_shot_id": shot.get("new_shot_id"),
                    "start_ms": shot.get("start_ms"),
                    "end_ms": shot.get("end_ms"),
                    "duration_ms": shot.get("duration_ms"),
                    "subtitle": text,
                }
            )
        return normalized
    return []


def _normalize_voiceover_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("voiceover_script") or payload.get("voiceovers")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    shots = payload.get("shots")
    if isinstance(shots, list):
        normalized: list[dict[str, Any]] = []
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            text = shot.get("voiceover") or shot.get("text")
            if not text:
                continue
            normalized.append(
                {
                    "new_shot_id": shot.get("new_shot_id"),
                    "start_ms": shot.get("start_ms"),
                    "end_ms": shot.get("end_ms"),
                    "duration_ms": shot.get("duration_ms"),
                    "voiceover": text,
                }
            )
        return normalized
    return []


def _normalize_storyboard_prompts_payload(payload: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("storyboard_prompts") or payload.get("prompts")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    shots = payload.get("shots")
    if isinstance(shots, list):
        image_model = config["model_defaults"].get("storyboard_image_model", "gpt-image-1")
        aspect_ratio = config.get("video_specs", {}).get("aspect_ratio", "9:16")
        resolution = config.get("video_specs", {}).get("resolution", "720x1280")
        normalized: list[dict[str, Any]] = []
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            prompt = shot.get("prompt") or shot.get("first_frame_prompt")
            negative_prompt = shot.get("negative_prompt")
            action_start_state = shot.get("action_start_state") or shot.get("first_frame_action_start_state")
            if not prompt or not negative_prompt or not action_start_state:
                continue
            normalized.append(
                {
                    "new_shot_id": shot.get("new_shot_id"),
                    "image_model": image_model,
                    "prompt": prompt,
                    "negative_prompt": negative_prompt,
                    "reference_image_ids": ["product_image_001"],
                    "aspect_ratio": aspect_ratio,
                    "resolution": resolution,
                    "action_start_state": action_start_state,
                    "purpose": "first_frame_for_seedance",
                }
            )
        return normalized
    return []


def _run_step(
    step: str,
    config: dict[str, Any],
    project_dir: Path,
    reference_video: str,
    product_images: str,
    mock_adapter: MockAdapter,
    real_mode: bool,
    ledger: dict[str, Any],
) -> list[Path]:
    if step == "01_ingest_inputs":
        data = build_input_manifest(config, reference_video, product_images)
        return [write_artifact(project_dir, "input_manifest.json", data)]
    reference_video_path = Path(reference_video) if reference_video else None
    product_images_path = Path(product_images) if product_images else None
    use_real_reference = bool(reference_video_path and reference_video_path.exists())
    use_real_products = bool(product_images_path and product_images_path.exists())
    if step == "02_preprocess_video":
        if use_real_reference:
            return [
                write_artifact(
                    project_dir,
                    "raw_shots.json",
                    build_real_raw_shots(config, reference_video_path, project_dir),
                )
            ]
        return [write_artifact(project_dir, "raw_shots.json", mock_adapter.fixture("raw_shots.json"))]
    raw = lambda: read_artifact(project_dir, "raw_shots.json")
    if step == "03_extract_subtitles":
        return [write_artifact(project_dir, "ocr_subtitles.json", mock_adapter.fixture("ocr_subtitles.json"))]
    if step == "04_transcribe_voice":
        if real_mode and reference_video_path and reference_video_path.exists():
            audio_path = _extract_audio(reference_video_path, project_dir)
            stt_model = config["model_defaults"].get("speech_model", "gpt-4o-transcribe")
            duration_minutes = raw()["video_meta"]["duration_ms"] / 60000
            transcript_text, api_cost = _tracked_api_call(
                config=config,
                ledger=ledger,
                step=step,
                provider="openai",
                model=stt_model,
                operation="transcribe_reference_audio",
                unit_label="rmb/minute",
                unit_price_rmb=_unit_price(config, "openai_stt_rmb_per_minute", DEFAULT_API_UNIT_PRICES["openai_stt_rmb_per_minute"]),
                quantity=duration_minutes,
                call=lambda: openai_transcribe(
                    audio_path,
                    model=stt_model,
                ),
            )
            data = {
                **artifact_header(
                    config["project_id"],
                    "voice_transcript",
                    [str(Path(reference_video).name)],
                    provider="openai",
                    model=stt_model,
                    temperature=0.0,
                    cost_rmb=api_cost,
                ),
                "voice_segments": [
                    {
                        "voice_segment_id": "v_001",
                        "reference_shot_ids": [shot["reference_shot_id"] for shot in raw()["raw_shots"]],
                        "start_ms": 0,
                        "end_ms": raw()["video_meta"]["duration_ms"],
                        "text": transcript_text,
                        "language": config["target_market"]["primary_language"],
                        "confidence": 0.95,
                    }
                ],
            }
            return [write_artifact(project_dir, "voice_transcript.json", data)]
        return [write_artifact(project_dir, "voice_transcript.json", mock_adapter.fixture("voice_transcript.json"))]
    if step == "05_reference_visual_analysis":
        if real_mode and use_real_reference and reference_video_path:
            gemini_model = _resolve_model(config["model_defaults"].get("video_understanding_model", "gemini-video"), provider="gemini")
            analysis, api_cost = _tracked_api_call(
                config=config,
                ledger=ledger,
                step=step,
                provider="gemini",
                model=gemini_model,
                operation="reference_video_understanding",
                unit_label="rmb/call",
                unit_price_rmb=_unit_price(config, "gemini_video_rmb_per_call", DEFAULT_API_UNIT_PRICES["gemini_video_rmb_per_call"]),
                quantity=1.0,
                call=lambda: gemini_video_json(
                    model=_resolve_model(config["model_defaults"].get("video_understanding_model", "gemini-video"), provider="gemini"),
                    prompt=_prompt("reference_visual_analysis.prompt.md")
                    + "\n\nINPUT:\n"
                    + _json_payload(
                        {
                            "raw_shots": raw()["raw_shots"],
                            "video_meta": raw()["video_meta"],
                        }
                    ),
                    video_path=reference_video_path,
                    schema=_schema("reference_visual_analysis.json"),
                ),
            )
            reference_shots = analysis if isinstance(analysis, list) else analysis["reference_shots"]
            data = {
                **artifact_header(
                    config["project_id"],
                    "reference_visual_analysis",
                    ["raw_shots.json", Path(reference_video).name],
                    provider="gemini",
                    model=gemini_model,
                    temperature=0.2,
                    cost_rmb=api_cost,
                ),
                "reference_shots": reference_shots,
            }
            return [write_artifact(project_dir, "reference_visual_analysis.json", data)]
        if use_real_reference or use_real_products:
            source_images = product_images_path if use_real_products else reference_video_path
            return [
                write_artifact(
                    project_dir,
                    "reference_visual_analysis.json",
                    build_real_reference_visual_analysis(config, raw(), source_images),
                )
            ]
        return [write_artifact(project_dir, "reference_visual_analysis.json", mock_adapter.fixture("reference_visual_analysis.json"))]
    if step == "06_reference_shot_strategy":
        if real_mode:
            strategy, api_cost = _tracked_api_call(
                config=config,
                ledger=ledger,
                step=step,
                provider="openai",
                model=config["model_defaults"]["main_reasoning_model"],
                operation="reference_shot_strategy",
                unit_label="rmb/call",
                unit_price_rmb=_unit_price(config, "openai_text_rmb_per_call", DEFAULT_API_UNIT_PRICES["openai_text_rmb_per_call"]),
                quantity=1.0,
                call=lambda: _openai_json(
                config,
                "main_reasoning_model",
                "reference_shot_strategy.prompt.md",
                {
                    "reference_visual_analysis": read_artifact(project_dir, "reference_visual_analysis.json"),
                    "ocr_subtitles": read_artifact(project_dir, "ocr_subtitles.json"),
                    "voice_transcript": read_artifact(project_dir, "voice_transcript.json"),
                    "raw_shots": raw(),
                },
                "reference_shot_strategy.json",
                ),
            )
            _dump_debug_json(project_dir, step, "raw_response", strategy)
            reference_shots, overall_structure = _normalize_reference_strategy_payload(strategy, raw())
            if not reference_shots:
                raise RuntimeError("reference_shot_strategy missing expected shot list in strict real mode")
            if not overall_structure:
                duration = raw()["video_meta"]["duration_ms"]
                hook_end = max(1000, int(duration * 0.15))
                problem_end = max(hook_end + 1, int(duration * 0.4))
                proof_end = max(problem_end + 1, int(duration * 0.7))
                scenario_end = max(proof_end + 1, int(duration * 0.9))
                overall_structure = {
                    "hook_ms": [0, hook_end],
                    "problem_ms": [hook_end, problem_end],
                    "proof_ms": [problem_end, proof_end],
                    "scenario_ms": [proof_end, scenario_end],
                    "cta_ms": [scenario_end, duration],
                }
            data = {
                **artifact_header(
                    config["project_id"],
                    "reference_shot_strategy",
                    ["reference_visual_analysis.json", "ocr_subtitles.json", "voice_transcript.json"],
                    provider="openai",
                    model=config["model_defaults"]["main_reasoning_model"],
                    temperature=0.2,
                    cost_rmb=api_cost,
                ),
                "reference_shots": reference_shots,
                "overall_structure": overall_structure,
            }
        else:
            data = mock_adapter.simulate(
                "reference_shot_strategy.json", lambda: build_strategy(config, raw())
            )
        return [write_artifact(project_dir, "reference_shot_strategy.json", data)]
    if step == "07_product_profile":
        if real_mode and use_real_products and product_images_path:
            image_paths = sorted(
                [item for item in product_images_path.iterdir() if item.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}]
            )
            profile, api_cost = _tracked_api_call(
                config=config,
                ledger=ledger,
                step=step,
                provider="openai",
                model=config["model_defaults"]["vision_model"],
                operation="product_profile_vision",
                unit_label="rmb/image",
                unit_price_rmb=_unit_price(config, "openai_vision_rmb_per_image", DEFAULT_API_UNIT_PRICES["openai_vision_rmb_per_image"]),
                quantity=float(len(image_paths)),
                call=lambda: _openai_vision(
                    config,
                    "vision_model",
                    "product_profile.prompt.md",
                    {
                        "project_id": config["project_id"],
                        "target_market": config["target_market"],
                    },
                    image_paths,
                    "product_profile.json",
                ),
            )
            _dump_debug_json(project_dir, step, "raw_response", profile)
            normalized_profile = profile.get("product_profile") if isinstance(profile, dict) else None
            if not isinstance(normalized_profile, dict):
                normalized_profile = profile if isinstance(profile, dict) else None
            if not isinstance(normalized_profile, dict):
                raise RuntimeError("product_profile missing in strict real mode")
            data = {
                **artifact_header(
                    config["project_id"],
                    "product_profile",
                    [path.name for path in image_paths],
                    provider="openai",
                    model=config["model_defaults"]["vision_model"],
                    temperature=0.2,
                    cost_rmb=api_cost,
                ),
                "product_profile": normalized_profile,
            }
            return [write_artifact(project_dir, "product_profile.json", data)]
        if use_real_products:
            return [
                write_artifact(
                    project_dir,
                    "product_profile.json",
                    infer_product_profile(config, product_images_path),
                )
            ]
        return [write_artifact(project_dir, "product_profile.json", mock_adapter.fixture("product_profile.json"))]
    if step == "08_product_action_matrix":
        if real_mode:
            matrix, api_cost = _tracked_api_call(
                config=config,
                ledger=ledger,
                step=step,
                provider="openai",
                model=config["model_defaults"]["main_reasoning_model"],
                operation="product_action_matrix",
                unit_label="rmb/call",
                unit_price_rmb=_unit_price(config, "openai_text_rmb_per_call", DEFAULT_API_UNIT_PRICES["openai_text_rmb_per_call"]),
                quantity=1.0,
                call=lambda: _openai_json(
                config,
                "main_reasoning_model",
                "product_action_matrix.prompt.md",
                {
                    "product_profile": read_artifact(project_dir, "product_profile.json"),
                    "reference_shot_strategy": read_artifact(project_dir, "reference_shot_strategy.json"),
                },
                "product_action_matrix.json",
                ),
            )
            _dump_debug_json(project_dir, step, "raw_response", matrix)
            action_matrix = _normalize_action_matrix_payload(matrix)
            if not action_matrix or any(
                not isinstance(item, dict)
                or "video_generation_risk" not in item
                or "required_props" not in item
                or "best_camera" not in item
                or "avoid" not in item
                for item in action_matrix
            ):
                raise RuntimeError("product_action_matrix missing expected fields in strict real mode")
            data = {
                **artifact_header(
                    config["project_id"],
                    "product_action_matrix",
                    ["product_profile.json", "reference_shot_strategy.json"],
                    provider="openai",
                    model=config["model_defaults"]["main_reasoning_model"],
                    temperature=0.2,
                    cost_rmb=api_cost,
                ),
                "product_action_matrix": action_matrix,
            }
        else:
            data = mock_adapter.simulate(
                "product_action_matrix.json",
                lambda: build_action_matrix(config, read_artifact(project_dir, "product_profile.json")),
            )
        return [write_artifact(project_dir, "product_action_matrix.json", data)]
    if step == "09_action_transfer":
        if real_mode:
            transfer, api_cost = _tracked_api_call(
                config=config,
                ledger=ledger,
                step=step,
                provider="openai",
                model=config["model_defaults"]["main_reasoning_model"],
                operation="action_transfer",
                unit_label="rmb/call",
                unit_price_rmb=_unit_price(config, "openai_text_rmb_per_call", DEFAULT_API_UNIT_PRICES["openai_text_rmb_per_call"]),
                quantity=1.0,
                call=lambda: _openai_json(
                    config,
                    "main_reasoning_model",
                    "action_transfer.prompt.md",
                    {
                        "raw_shots": raw(),
                        "reference_shot_strategy": read_artifact(project_dir, "reference_shot_strategy.json"),
                        "product_profile": read_artifact(project_dir, "product_profile.json"),
                        "product_action_matrix": read_artifact(project_dir, "product_action_matrix.json"),
                    },
                    "action_transfer_plan.json",
                ),
            )
            _dump_debug_json(project_dir, step, "raw_response", transfer)
            action_transfer_plan = _normalize_action_transfer_payload(transfer)
            _dump_debug_json(
                project_dir,
                step,
                "normalized_response",
                {
                    "count": len(action_transfer_plan),
                    "items": action_transfer_plan[:20],
                },
            )
            if not action_transfer_plan:
                raise RuntimeError("action_transfer_plan missing in strict real mode")
            data = {
                **artifact_header(
                    config["project_id"],
                    "action_transfer_plan",
                    ["reference_shot_strategy.json", "product_action_matrix.json", "product_profile.json"],
                    provider="openai",
                    model=config["model_defaults"]["main_reasoning_model"],
                    temperature=0.2,
                    cost_rmb=api_cost,
                ),
                "action_transfer_plan": action_transfer_plan,
            }
        else:
            data = mock_adapter.simulate(
                "action_transfer_plan.json",
                lambda: build_transfer(
                    config,
                    raw(),
                    read_artifact(project_dir, "reference_shot_strategy.json"),
                    read_artifact(project_dir, "product_profile.json"),
                ),
            )
        return [write_artifact(project_dir, "action_transfer_plan.json", data)]
    if step == "10_new_video_plan":
        if real_mode:
            plan, api_cost = _tracked_api_call(
                config=config,
                ledger=ledger,
                step=step,
                provider="openai",
                model=config["model_defaults"]["main_reasoning_model"],
                operation="new_video_plan",
                unit_label="rmb/call",
                unit_price_rmb=_unit_price(config, "openai_text_rmb_per_call", DEFAULT_API_UNIT_PRICES["openai_text_rmb_per_call"]),
                quantity=1.0,
                call=lambda: _openai_json(
                    config,
                    "main_reasoning_model",
                    "new_video_plan.prompt.md",
                    {
                        "raw_shots": raw(),
                        "reference_shot_strategy": read_artifact(project_dir, "reference_shot_strategy.json"),
                        "product_profile": read_artifact(project_dir, "product_profile.json"),
                        "product_action_matrix": read_artifact(project_dir, "product_action_matrix.json"),
                        "action_transfer_plan": read_artifact(project_dir, "action_transfer_plan.json"),
                    },
                    "new_video_plan.json",
                ),
            )
            _dump_debug_json(project_dir, step, "raw_response", plan)
            new_video_plan = _normalize_new_video_plan_payload(plan)
            _dump_debug_json(project_dir, step, "normalized_response", new_video_plan)
            if not isinstance(new_video_plan, dict) or "duration_ms" not in new_video_plan or "shots" not in new_video_plan:
                raise RuntimeError("new_video_plan missing duration_ms or shots in strict real mode")
            data = {
                **artifact_header(
                    config["project_id"],
                    "new_video_plan",
                    ["action_transfer_plan.json", "reference_shot_strategy.json", "product_profile.json"],
                    provider="openai",
                    model=config["model_defaults"]["main_reasoning_model"],
                    temperature=0.2,
                    cost_rmb=api_cost,
                ),
                "new_video_plan": new_video_plan,
            }
            data = prepare_plan_for_generation(data, raw()["video_meta"]["duration_ms"])
        else:
            generated = mock_adapter.simulate(
                "new_video_plan.json",
                lambda: build_new_video_plan(
                    config,
                    raw(),
                    read_artifact(project_dir, "reference_shot_strategy.json"),
                    read_artifact(project_dir, "product_profile.json"),
                ),
            )
            data = prepare_plan_for_generation(generated, raw()["video_meta"]["duration_ms"])
        return [write_artifact(project_dir, "new_video_plan.json", data)]
    plan = lambda: read_artifact(project_dir, "new_video_plan.json")
    if step == "11_subtitle_voiceover":
        if real_mode:
            subtitle_path = output_path(project_dir, "subtitle_script.json")
            if subtitle_path.exists():
                subtitle = read_artifact(project_dir, "subtitle_script.json")
            else:
                subtitle_body, subtitle_cost = _tracked_api_call(
                    config=config,
                    ledger=ledger,
                    step=step,
                    provider="openai",
                    model=config["model_defaults"]["main_reasoning_model"],
                    operation="subtitle_script",
                    unit_label="rmb/call",
                    unit_price_rmb=_unit_price(config, "openai_text_rmb_per_call", DEFAULT_API_UNIT_PRICES["openai_text_rmb_per_call"]),
                    quantity=1.0,
                    call=lambda: _openai_json(
                        config,
                        "main_reasoning_model",
                        "subtitle_voiceover.prompt.md",
                        {
                            "new_video_plan": plan(),
                            "product_profile": read_artifact(project_dir, "product_profile.json"),
                            "output_kind": "subtitle_script",
                        },
                        "subtitle_script.json",
                    ),
                )
                _dump_debug_json(project_dir, step, "subtitle_raw_response", subtitle_body)
                subtitle_list = _normalize_subtitle_payload(subtitle_body)
                _dump_debug_json(project_dir, step, "subtitle_normalized_response", subtitle_list)
                if not subtitle_list:
                    raise RuntimeError("subtitle_script missing in strict real mode")
                subtitle = {
                    **artifact_header(
                        config["project_id"],
                        "subtitle_script",
                        ["new_video_plan.json"],
                        provider="openai",
                        model=config["model_defaults"]["main_reasoning_model"],
                        temperature=0.2,
                        cost_rmb=subtitle_cost,
                    ),
                    "subtitle_script": subtitle_list,
                }
                write_artifact(project_dir, "subtitle_script.json", subtitle)
            voiceover_body, voiceover_cost = _tracked_api_call(
                config=config,
                ledger=ledger,
                step=step,
                provider="openai",
                model=config["model_defaults"]["main_reasoning_model"],
                operation="voiceover_script",
                unit_label="rmb/call",
                unit_price_rmb=_unit_price(config, "openai_text_rmb_per_call", DEFAULT_API_UNIT_PRICES["openai_text_rmb_per_call"]),
                quantity=1.0,
                call=lambda: _openai_json(
                    config,
                    "main_reasoning_model",
                    "subtitle_voiceover.prompt.md",
                    {
                        "new_video_plan": plan(),
                        "product_profile": read_artifact(project_dir, "product_profile.json"),
                        "output_kind": "voiceover_script",
                    },
                    "voiceover_script.json",
                ),
            )
            _dump_debug_json(project_dir, step, "voiceover_raw_response", voiceover_body)
            voiceover_list = _normalize_voiceover_payload(voiceover_body)
            _dump_debug_json(project_dir, step, "voiceover_normalized_response", voiceover_list)
            if not voiceover_list:
                raise RuntimeError("voiceover_script missing in strict real mode")
            voiceover = {
                **artifact_header(
                    config["project_id"],
                    "voiceover_script",
                    ["new_video_plan.json"],
                    provider="openai",
                    model=config["model_defaults"]["main_reasoning_model"],
                    temperature=0.2,
                    cost_rmb=voiceover_cost,
                ),
                "voiceover_script": voiceover_list,
            }
        else:
            subtitle, voiceover = build_scripts(config, plan(), read_artifact(project_dir, "product_profile.json"))
            subtitle = mock_adapter.simulate("subtitle_script.json", lambda: subtitle)
            voiceover = mock_adapter.simulate("voiceover_script.json", lambda: voiceover)
        return [
            write_artifact(project_dir, "subtitle_script.json", subtitle),
            write_artifact(project_dir, "voiceover_script.json", voiceover),
        ]
    if step == "12_audio_asset_manifest":
        data = mock_adapter.simulate(
            "audio_asset_manifest.json",
            lambda: build_audio(config, plan(), read_artifact(project_dir, "product_profile.json")),
        )
        return [write_artifact(project_dir, "audio_asset_manifest.json", data)]
    profile = lambda: read_artifact(project_dir, "product_profile.json")
    matrix = lambda: read_artifact(project_dir, "product_action_matrix.json")
    if step == "13_storyboard_prompts":
        if real_mode:
            prompts_path = output_path(project_dir, "storyboard_prompts.json")
            if prompts_path.exists():
                data = read_artifact(project_dir, "storyboard_prompts.json")
            else:
                prompts, api_cost = _tracked_api_call(
                    config=config,
                    ledger=ledger,
                    step=step,
                    provider="openai",
                    model=config["model_defaults"]["main_reasoning_model"],
                    operation="storyboard_prompts",
                    unit_label="rmb/call",
                    unit_price_rmb=_unit_price(config, "openai_text_rmb_per_call", DEFAULT_API_UNIT_PRICES["openai_text_rmb_per_call"]),
                    quantity=1.0,
                    call=lambda: _openai_json(
                        config,
                        "main_reasoning_model",
                        "storyboard_prompt.prompt.md",
                        {
                            "new_video_plan": plan(),
                            "product_profile": profile(),
                            "product_action_matrix": matrix(),
                        },
                        "storyboard_prompts.json",
                    ),
                )
                _dump_debug_json(project_dir, step, "raw_response", prompts)
                prompt_list = _normalize_storyboard_prompts_payload(prompts, config)
                _dump_debug_json(project_dir, step, "normalized_response", prompt_list)
                if not prompt_list or any(
                    not isinstance(item, dict)
                    or "image_model" not in item
                    or "negative_prompt" not in item
                    or "reference_image_ids" not in item
                    or "aspect_ratio" not in item
                    or "resolution" not in item
                    or "action_start_state" not in item
                    or "purpose" not in item
                    for item in prompt_list
                ):
                    raise RuntimeError("storyboard_prompts missing expected fields in strict real mode")
                data = {
                    **artifact_header(
                        config["project_id"],
                        "storyboard_prompts",
                        ["new_video_plan.json", "product_profile.json", "product_action_matrix.json"],
                        provider="openai",
                        model=config["model_defaults"]["main_reasoning_model"],
                        temperature=0.2,
                        cost_rmb=api_cost,
                    ),
                    "storyboard_prompts": prompt_list,
                }
                write_artifact(project_dir, "storyboard_prompts.json", data)
        else:
            data = mock_adapter.simulate(
                "storyboard_prompts.json",
                lambda: build_storyboard_prompts(config, plan(), profile(), matrix()),
            )
        return [write_artifact(project_dir, "storyboard_prompts.json", data)]
    if step == "14_generate_storyboards":
        if real_mode:
            prompts_data = read_artifact(project_dir, "storyboard_prompts.json")
            boards = []
            storyboard_provider = config["model_defaults"].get("storyboard_image_provider", "openai")
            storyboard_model = config["model_defaults"].get("storyboard_image_model", "gpt-image-1")
            product_image_paths: list[Path] = []
            if product_images_path and product_images_path.exists():
                product_image_paths = sorted(
                    [
                        item
                        for item in product_images_path.iterdir()
                        if item.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
                    ]
                )
            for index, prompt in enumerate(prompts_data["storyboard_prompts"]):
                image_path = runtime_dirs(project_dir)["storyboards"] / f"sb_{index + 1:03d}.png"
                if storyboard_provider == "openai":
                    full_prompt = (
                        f"{prompt['prompt']}\n\n"
                        f"Negative constraints: {prompt['negative_prompt']}\n"
                        "Use the attached product reference image(s) to keep product identity accurate when provided. "
                        "Create a realistic ecommerce storyboard first frame. "
                        "Do not add text overlays, watermarks, logos, or faces."
                    )
                    if product_image_paths:
                        image_bytes, _ = _tracked_api_call(
                            config=config,
                            ledger=ledger,
                            step=step,
                            provider="openai",
                            model=storyboard_model,
                            operation=f"storyboard_edit_{index + 1:03d}",
                            unit_label="rmb/call",
                            unit_price_rmb=_unit_price(config, "openai_image_edit_rmb_per_call", DEFAULT_API_UNIT_PRICES["openai_image_edit_rmb_per_call"]),
                            quantity=1.0,
                            call=lambda prompt_text=full_prompt, ar=prompt["aspect_ratio"]: openai_edit_image(
                                model=storyboard_model,
                                prompt=prompt_text,
                                image_paths=product_image_paths[:1],
                                size=_openai_image_size(ar),
                            ),
                        )
                    else:
                        image_bytes, _ = _tracked_api_call(
                            config=config,
                            ledger=ledger,
                            step=step,
                            provider="openai",
                            model=storyboard_model,
                            operation=f"storyboard_generate_{index + 1:03d}",
                            unit_label="rmb/call",
                            unit_price_rmb=_unit_price(config, "openai_image_generate_rmb_per_call", DEFAULT_API_UNIT_PRICES["openai_image_generate_rmb_per_call"]),
                            quantity=1.0,
                            call=lambda prompt_text=full_prompt, ar=prompt["aspect_ratio"]: openai_generate_image(
                                model=storyboard_model,
                                prompt=prompt_text,
                                size=_openai_image_size(ar),
                            ),
                        )
                    image_path.write_bytes(image_bytes)
                elif storyboard_provider == "fal":
                    endpoint_id = os.environ.get("FLUX_ENDPOINT_ID") or _resolve_model(
                        config["model_defaults"]["storyboard_key_model"],
                        provider="fal",
                    )
                    result, _ = _tracked_api_call(
                        config=config,
                        ledger=ledger,
                        step=step,
                        provider="fal",
                        model=endpoint_id,
                        operation=f"storyboard_generate_{index + 1:03d}",
                        unit_label="rmb/call",
                        unit_price_rmb=_unit_price(config, "flux_image_rmb_per_call", DEFAULT_API_UNIT_PRICES["flux_image_rmb_per_call"]),
                        quantity=1.0,
                        call=lambda: fal_run_json(
                            endpoint_id=endpoint_id,
                            payload={
                                "prompt": prompt["prompt"],
                                "negative_prompt": prompt["negative_prompt"],
                                "image_size": _fal_image_size(prompt["aspect_ratio"]),
                            },
                        ),
                    )
                    image_url = None
                    if isinstance(result, dict):
                        if "images" in result and result["images"]:
                            image_url = result["images"][0].get("url")
                        elif "image" in result and isinstance(result["image"], dict):
                            image_url = result["image"].get("url")
                        elif "image_url" in result:
                            image_url = result["image_url"]
                    if not image_url:
                        raise RuntimeError(f"FLUX did not return an image URL: {result}")
                    _download_to(image_url, image_path)
                else:
                    raise RuntimeError(f"Unsupported storyboard_image_provider: {storyboard_provider}")
                boards.append(
                    {
                        "new_shot_id": prompt["new_shot_id"],
                        "image_id": f"sb_{index + 1:03d}",
                        "image_path": relative_to_project(image_path, project_dir),
                        "model": storyboard_model if storyboard_provider == "openai" else prompt["image_model"],
                        "source_prompt_id": prompt["new_shot_id"],
                        "selected": True,
                    }
                )
            data = {
                **artifact_header(
                    config["project_id"],
                    "storyboard_manifest",
                    ["storyboard_prompts.json"],
                    provider=storyboard_provider,
                    model=storyboard_model if storyboard_provider == "openai" else config["model_defaults"]["storyboard_key_model"],
                    temperature=0.0,
                ),
                "storyboards": boards,
            }
        else:
            data = mock_adapter.simulate(
                "storyboard_manifest.json",
                lambda: build_storyboards(
                    config,
                    read_artifact(project_dir, "storyboard_prompts.json"),
                    project_dir,
                ),
            )
        return [write_artifact(project_dir, "storyboard_manifest.json", data)]
    if step == "15_storyboard_precheck":
        if real_mode:
            data = build_precheck(config, read_artifact(project_dir, "storyboard_manifest.json"), profile())
        else:
            data = mock_adapter.simulate(
                "storyboard_precheck.json",
                lambda: build_precheck(config, read_artifact(project_dir, "storyboard_manifest.json"), profile()),
            )
        return [write_artifact(project_dir, "storyboard_precheck.json", data)]
    if step == "16_compile_seedance_tasks":
        tasks = compile_tasks(config=config, plan_artifact=plan(), profile_artifact=profile(), matrix_artifact=matrix(), storyboard_artifact=read_artifact(project_dir, "storyboard_manifest.json"), project_dir=project_dir)
        return [write_artifact(project_dir, "seedance_tasks.json", tasks)]
    if step == "17_generate_video_clips":
        if real_mode:
            tasks = read_artifact(project_dir, "seedance_tasks.json")
            existing_manifest_path = output_path(project_dir, "video_clips_manifest.json")
            clips = []
            if existing_manifest_path.exists():
                existing_manifest = load_json(existing_manifest_path)
                clips = list(existing_manifest.get("video_clips", []))
            completed_task_ids = {
                clip["task_id"]
                for clip in clips
                if clip.get("status") == "generated"
            }
            model_id = (
                os.environ.get("SEEDANCE_MODEL_ID")
                or os.environ.get("SEEDANCE_MODEL")
                or os.environ.get("ARK_SEEDANCE_MODEL_ID")
                or "doubao-seedance-2-0-260128"
            )
            for task in tasks["seedance_tasks"]:
                if task["task_id"] in completed_task_ids:
                    continue
                provider_duration_sec = task.get("seedance_duration_sec", _seedance_duration_sec(task["duration_ms"]))
                input_images = task.get("input_images") or [task["input_image"]]
                prompt_text = (
                    f"{task['prompt']}\n\n"
                    f"Negative constraints: {task['negative_prompt']}\n"
                    "Keep the product identity and mechanical structure consistent with the reference image(s)."
                )
                data_urls = [
                    _file_data_url(_resolve_input_image(project_dir, image_value))
                    for image_value in input_images
                ]
                last_error: Exception | None = None
                result: dict[str, Any] | None = None
                actual_cost = 0.0
                for attempt in range(3):
                    try:
                        result, actual_cost = _tracked_api_call(
                            config=config,
                            ledger=ledger,
                            step=step,
                            provider="seedance",
                            model=model_id,
                            operation=f"generate_clip_{task['task_id']}",
                            unit_label="rmb/second",
                            unit_price_rmb=float(config["cost_rules"]["seedance_cost_rmb_per_second"]),
                            quantity=float(provider_duration_sec),
                            call=lambda: byteplus_seedance_run(
                                model=model_id,
                                prompt=prompt_text,
                                image_urls=data_urls,
                                duration=provider_duration_sec,
                                aspect_ratio=task["aspect_ratio"],
                                resolution=task["resolution"],
                                api_key=os.environ.get("ARK_API_KEY") or os.environ.get("SEEDANCE_API_KEY"),
                            ),
                        )
                        break
                    except Exception as exc:
                        last_error = exc
                        if attempt == 2:
                            raise
                if last_error and result is None:
                    raise last_error
                video_url = None
                if isinstance(result, dict):
                    if "video" in result and isinstance(result["video"], dict):
                        video_url = result["video"].get("url")
                    elif "videos" in result and result["videos"]:
                        video_url = result["videos"][0].get("url")
                    elif "video_url" in result:
                        video_url = result["video_url"]
                if not video_url:
                    content = result.get("content") if isinstance(result, dict) else None
                    if isinstance(content, dict):
                        video_url = content.get("video_url")
                if not video_url:
                    raise RuntimeError(f"Seedance did not return a video URL: {result}")
                clip_path = runtime_dirs(project_dir)["clips"] / f"{task['task_id']}.mp4"
                _download_to(video_url, clip_path)
                clip_entry = (
                    {
                        "task_id": task["task_id"],
                        "new_shot_id": task["new_shot_id"],
                        "source_new_shot_ids": task.get("source_new_shot_ids", [task["new_shot_id"]]),
                        "merge_strategy": task.get("merge_strategy", "standalone"),
                        "status": "generated",
                        "clip_path": relative_to_project(clip_path, project_dir),
                        "duration_ms": task["duration_ms"],
                        "seedance_duration_sec": provider_duration_sec,
                        "input_images": input_images,
                        "seedance_model_id": model_id,
                        "provider_task_id": result.get("id") if isinstance(result, dict) else None,
                        "source_segments": task.get("source_segments", []),
                        "actual_cost_rmb": actual_cost,
                    }
                )
                clips.append(clip_entry)
                atomic_write_json(existing_manifest_path, _video_clips_manifest_data(config, model_id, clips))
            data = _video_clips_manifest_data(config, model_id, clips)
        else:
            data = mock_adapter.simulate(
                "video_clips_manifest.json",
                lambda: build_video_clips(
                    config, read_artifact(project_dir, "seedance_tasks.json"), project_dir
                ),
            )
        return [write_artifact(project_dir, "video_clips_manifest.json", data)]
    if step == "18_generate_voiceover":
        if real_mode:
            voiceover_script = read_artifact(project_dir, "voiceover_script.json")
            voice_text = "\n".join(item["text"] for item in voiceover_script["voiceover_script"])
            tts_model = os.environ.get("ELEVENLABS_TTS_MODEL") or "eleven_multilingual_v2"
            audio, api_cost = _tracked_api_call(
                config=config,
                ledger=ledger,
                step=step,
                provider="elevenlabs",
                model=tts_model,
                operation="voiceover_tts",
                unit_label="rmb/1k_chars",
                unit_price_rmb=_unit_price(config, "elevenlabs_tts_rmb_per_1k_chars", DEFAULT_API_UNIT_PRICES["elevenlabs_tts_rmb_per_1k_chars"]),
                quantity=max(len(voice_text), 1) / 1000,
                call=lambda: elevenlabs_tts(
                    voice_text,
                    voice_id=os.environ.get("ELEVENLABS_VOICE_ID"),
                    model_id=os.environ.get("ELEVENLABS_TTS_MODEL"),
                ),
            )
            audio_path = runtime_dirs(project_dir)["audio"] / "voiceover.mp3"
            audio_path.write_bytes(audio)
            data = {
                **artifact_header(
                    config["project_id"],
                    "voiceover_asset_manifest",
                    ["voiceover_script.json"],
                    provider="elevenlabs",
                    model=tts_model,
                    temperature=0.0,
                    cost_rmb=api_cost,
                ),
                "voiceover": {
                    "status": "generated",
                    "path": relative_to_project(audio_path, project_dir),
                    "language": config["target_market"]["primary_language"],
                    "actual_cost_rmb": api_cost,
                },
                "segments": [
                    {
                        "new_shot_id": item["new_shot_id"],
                        "max_duration_ms": item["max_duration_ms"],
                        "status": "generated",
                    }
                    for item in voiceover_script["voiceover_script"]
                ],
            }
        else:
            data = mock_adapter.simulate(
                "voiceover_asset_manifest.json",
                lambda: build_voiceover_assets(
                    config,
                    read_artifact(project_dir, "voiceover_script.json"),
                    project_dir,
                ),
            )
        return [write_artifact(project_dir, "voiceover_asset_manifest.json", data)]
    if step == "19_render_final_video":
        plan_data = read_artifact(project_dir, "new_video_plan.json")
        render_plan = mock_adapter.simulate(
            "render_plan.json", lambda: build_render_plan(config, plan_data["new_video_plan"]["duration_ms"])
        )
        final_manifest = mock_adapter.simulate(
            "final_video_manifest.json",
            lambda: build_final_manifest(config, project_dir),
        )
        return [
            write_artifact(project_dir, "render_plan.json", render_plan),
            write_artifact(project_dir, "final_video_manifest.json", final_manifest),
        ]
    raise ValueError(f"Unknown step: {step}")


def run(
    *,
    project_dir: Path,
    config_path: Path,
    reference_video: str = "",
    product_images: str = "",
    resume: bool = False,
    selected_step: str | None = None,
    until_step: str | None = None,
    dry_run: bool = True,
    mock_input_dir: Path | None = None,
) -> int:
    project_dir = project_dir.resolve()
    runtime_dirs(project_dir)
    config = load_json(config_path)
    schema = load_json(Path(__file__).resolve().parents[1] / "config/project_config.schema.json")
    Draft202012Validator(schema).validate(config)
    atomic_write_json(project_dir / "project_config.json", config)
    state_path = output_path(project_dir, "pipeline_state.json")
    ledger_path = output_path(project_dir, "cost_ledger.json")
    state = load_json(state_path) if resume and state_path.exists() else _initial_state(config, dry_run)
    ledger = load_json(ledger_path) if resume and ledger_path.exists() else _initial_ledger(config)
    mock_adapter = MockAdapter(
        mock_input_dir or SKILL_ROOT / "tests/mock_input",
        load_json,
    )
    if selected_step and until_step:
        raise ValueError("selected_step and until_step cannot be used together")
    if selected_step:
        steps = [selected_step]
    elif until_step:
        steps = STEPS[: STEPS.index(until_step) + 1]
    else:
        steps = STEPS
    for step in steps:
        if step not in STEPS:
            raise ValueError(f"Unknown step: {step}")
        existing = state["steps"].get(step, {})
        outputs_exist = all(output_path(project_dir, name).exists() for name in STEP_OUTPUTS[step])
        if resume and existing.get("status") == "done" and outputs_exist:
            print(f"SKIP {step}")
            continue
        state.update(status="running", current_step=step, error=None)
        state["steps"][step] = {"status": "running", "retry_count": existing.get("retry_count", 0)}
        atomic_write_json(state_path, state)
        spent_before = float(ledger.get("spent_rmb", 0.0))
        try:
            outputs = _run_step(
                step,
                config,
                project_dir,
                reference_video,
                product_images,
                mock_adapter,
                real_mode=not dry_run,
                ledger=ledger,
            )
            for artifact in outputs:
                errors = validate_file(artifact, config_path=config_path, project_dir=project_dir)
                if errors:
                    raise ValueError(f"{artifact.name}: " + "; ".join(errors))
            estimated = 0.0
            actual_step_cost = round(float(ledger.get("spent_rmb", 0.0)) - spent_before, 4)
            if step == "16_compile_seedance_tasks":
                tasks = load_json(outputs[0])
                estimated = tasks["estimated_total_cost_rmb"]
                if tasks["budget_status"] == "blocked":
                    raise RuntimeError("Seedance estimate exceeds configured budget")
                ledger["estimated_rmb"] = estimated
            state["steps"][step] = {
                "status": "done",
                "outputs": [relative_to_project(path, project_dir) for path in outputs],
                "input_hash": stable_hash(step, config, reference_video, product_images),
                "cost_rmb": actual_step_cost,
            }
            state["total_cost_rmb"] = float(ledger.get("spent_rmb", 0.0))
            ledger["items"].append({
                "step": step,
                "artifacts": [path.name for path in outputs],
                "estimated_cost_rmb": estimated,
                "actual_cost_rmb": actual_step_cost,
                "dry_run": dry_run,
            })
            atomic_write_json(ledger_path, ledger)
            atomic_write_json(state_path, state)
            for system_artifact in (ledger_path, state_path):
                system_errors = validate_file(
                    system_artifact,
                    config_path=config_path,
                    project_dir=project_dir,
                )
                if system_errors:
                    raise ValueError(
                        f"{system_artifact.name}: " + "; ".join(system_errors)
                    )
            print(f"DONE {step}")
        except Exception as exc:
            state.update(status="failed", current_step=step, error=str(exc))
            state["steps"][step] = {"status": "failed", "error": str(exc), "retry_count": existing.get("retry_count", 0) + 1}
            atomic_write_json(state_path, state)
            atomic_write_json(ledger_path, ledger)
            raise
    if not selected_step:
        state.update(status="completed", current_step=None, error=None)
        atomic_write_json(state_path, state)
    if dry_run:
        mock_adapter.assert_offline()
    for path in (state_path, ledger_path):
        errors = validate_file(path, config_path=config_path, project_dir=project_dir)
        if errors:
            raise ValueError(f"{path.name}: " + "; ".join(errors))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the resumable shot-remake pipeline.")
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=SKILL_ROOT / "tests/mock_run",
    )
    parser.add_argument(
        "--mock-input-dir",
        type=Path,
        default=SKILL_ROOT / "tests/mock_input",
    )
    parser.add_argument("--reference-video", default="")
    parser.add_argument("--product-images", default="")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--step", choices=STEPS)
    parser.add_argument("--until-step", choices=STEPS)
    args = parser.parse_args()
    if args.dry_run and args.real:
        parser.error("--dry-run and --real are mutually exclusive")
    config = args.config
    if config is None:
        saved = args.project_dir / "project_config.json"
        config = saved if saved.exists() else Path(__file__).resolve().parents[1] / "config/default_project_config.json"
    if args.real:
        missing = missing_api_keys()
        if missing:
            print("Missing required API keys: " + ", ".join(missing), file=sys.stderr)
            return 2
    try:
        return run(
            project_dir=args.project_dir,
            config_path=config,
            reference_video=args.reference_video,
            product_images=args.product_images,
            resume=args.resume,
            selected_step=args.step,
            until_step=args.until_step,
            dry_run=not args.real,
            mock_input_dir=args.mock_input_dir,
        )
    except Exception as exc:
        print(f"PIPELINE FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

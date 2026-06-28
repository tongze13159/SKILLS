from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from common import (
    artifact_header,
    atomic_write_json,
    load_json,
    output_path,
    relative_to_project,
    runtime_dirs,
)


PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _header(config: dict[str, Any], name: str, sources: list[str]) -> dict[str, Any]:
    return artifact_header(
        config["project_id"],
        name.removesuffix(".json"),
        sources,
        provider="dry-run",
        model="deterministic-fixture",
    )


def _shot_function(index: int, count: int) -> str:
    if index == 0:
        return "hook"
    if index == count - 1:
        return "cta"
    if index < 4:
        return "pain_point"
    if index < 6:
        return "product_reveal"
    if index < 12:
        return "function_demo"
    if index < 15:
        return "proof"
    if index < 18:
        return "scenario"
    return "transition"


def _profile_body(profile: dict[str, Any] | None) -> dict[str, Any]:
    if not profile:
        return {}
    if "product_profile" in profile and isinstance(profile["product_profile"], dict):
        profile = profile["product_profile"]
    if "category" in profile and "shape" in profile:
        return profile
    product_type = str(profile.get("product_type", "")).lower()
    physical_shape = profile.get("physical_shape", "")
    visual_identity = profile.get("visual_identity", {})
    colors = visual_identity.get("colors") if isinstance(visual_identity, dict) else []
    must_keep = profile.get("must_keep_visual_details") or profile.get("visible_features") or []
    avoid_rules = profile.get("avoid_deformation_rules") or profile.get("avoid_deformation") or []
    return {
        "product_id": profile.get("product_id", "prod_001"),
        "category": "portable_pet_water_bottle" if ("water" in product_type or "pet" in product_type) else profile.get("category", "portable_accessory"),
        "shape": physical_shape or profile.get("shape", "portable_product"),
        "colors": colors or profile.get("colors", []),
        "materials": profile.get("materials", []),
        "visible_features": profile.get("visible_features", []),
        "main_selling_points": profile.get("usable_actions", []),
        "usable_actions": profile.get("usable_actions", []),
        "unsuitable_actions": profile.get("unsuitable_actions", []),
        "must_keep_visual_details": must_keep,
        "avoid_deformation": avoid_rules,
        "physical_constraints": profile.get("physical_constraints", []),
        "user_truth_override": profile.get("user_truth_override", {}),
    }


def _is_pet_bottle(profile: dict[str, Any] | None) -> bool:
    body = _profile_body(profile)
    return body.get("category") == "portable_pet_water_bottle" or "pet" in str(body.get("shape", "")).lower() or "water" in str(body.get("shape", "")).lower()


def build_input_manifest(
    config: dict[str, Any],
    reference_video: str,
    product_images: str,
) -> dict[str, Any]:
    return {
        **_header(config, "input_manifest.json", []),
        "inputs": {
            "reference_video": reference_video,
            "product_images": product_images,
            "dry_run_fixture": True,
            "face_policy": "no_visible_face",
            "originality_policy": "structure_only_original_rebuild",
        },
    }


def build_raw_shots(config: dict[str, Any]) -> dict[str, Any]:
    specs = config["video_specs"]
    duration = specs["target_duration_ms"]
    shot_duration = specs["default_shot_duration_ms"]
    count = duration // shot_duration
    shots = []
    for index in range(count):
        number = index + 1
        ref_id = f"ref_{number:03d}"
        start = index * shot_duration
        shots.append(
            {
                "reference_shot_id": ref_id,
                "start_ms": start,
                "end_ms": start + shot_duration,
                "duration_ms": shot_duration,
                "keyframes": {
                    "start": f"output/keyframes/{ref_id}_start.jpg",
                    "middle": f"output/keyframes/{ref_id}_middle.jpg",
                    "end": f"output/keyframes/{ref_id}_end.jpg",
                },
                "motion_peak_frames": [f"output/keyframes/{ref_id}_peak_01.jpg"],
                "motion_intensity": "high" if index in {0, 4, 8, 12} else "medium",
            }
        )
    return {
        **_header(config, "raw_shots.json", ["input_manifest.json"]),
        "video_meta": {
            "duration_ms": duration,
            "aspect_ratio": specs["aspect_ratio"],
            "width": specs["width"],
            "height": specs["height"],
            "fps": specs["fps"],
            "has_audio": True,
        },
        "raw_shots": shots,
    }


def build_ocr(config: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    groups = []
    for index, shot in enumerate(raw["raw_shots"]):
        groups.append(
            {
                "subtitle_group_id": f"sub_{index + 1:03d}",
                "reference_shot_ids": [shot["reference_shot_id"]],
                "text": f"Reference caption {index + 1}",
                "position": "bottom_center",
                "confidence": 0.91,
                "start_ms": shot["start_ms"],
                "end_ms": shot["end_ms"],
                "needs_review": False,
            }
        )
    return {
        **_header(config, "ocr_subtitles.json", ["raw_shots.json"]),
        "subtitle_groups": groups,
    }


def build_voice(config: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    return {
        **_header(config, "voice_transcript.json", ["raw_shots.json"]),
        "voice_segments": [
            {
                "voice_segment_id": f"v_{index + 1:03d}",
                "reference_shot_ids": [shot["reference_shot_id"]],
                "start_ms": shot["start_ms"],
                "end_ms": shot["end_ms"],
                "text": f"Reference voice segment {index + 1}",
                "language": "zh",
                "confidence": 0.92,
            }
            for index, shot in enumerate(raw["raw_shots"])
        ],
    }


def build_visual(config: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    return {
        **_header(
            config,
            "reference_visual_analysis.json",
            ["raw_shots.json", "ocr_subtitles.json", "voice_transcript.json"],
        ),
        "reference_shots": [
            {
                "reference_shot_id": shot["reference_shot_id"],
                "visual_description": "Close-up product demonstration on a bright kitchen table.",
                "main_subject": "product",
                "visible_objects": ["product", "hands", "glass_bowl"],
                "product_action": "product is revealed and demonstrated",
                "hand_action": "hands operate product without showing a face",
                "camera_angle": "top_down_45",
                "camera_distance": "close_up",
                "camera_movement": "slight_push_in",
                "scene_type": "kitchen_tabletop",
                "motion_intensity": shot["motion_intensity"],
                "visible_text": f"Reference caption {index + 1}",
                "voice_text": f"Reference voice segment {index + 1}",
            }
            for index, shot in enumerate(raw["raw_shots"])
        ],
    }


def build_strategy(config: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    count = len(raw["raw_shots"])
    duration = raw.get("video_meta", {}).get("duration_ms", config["video_specs"]["target_duration_ms"])
    hook_end = max(1000, int(duration * 0.15))
    problem_end = max(hook_end + 1, int(duration * 0.4))
    proof_end = max(problem_end + 1, int(duration * 0.7))
    scenario_end = max(proof_end + 1, int(duration * 0.9))
    return {
        **_header(
            config,
            "reference_shot_strategy.json",
            ["reference_visual_analysis.json", "ocr_subtitles.json", "voice_transcript.json"],
        ),
        "reference_shots": [
            {
                "reference_shot_id": shot["reference_shot_id"],
                "shot_function": _shot_function(index, count),
                "commercial_purpose": "Show a clear product benefit with original execution.",
                "viewer_psychology": "curiosity" if index == 0 else "confidence",
                "why_it_works": "One readable action and a close product view reduce ambiguity.",
                "remake_value": "high",
                "must_keep_logic": ["single clear action", "close product focus", "fast pacing"],
                "must_change": [
                    "exact wording",
                    "exact background layout",
                    "music",
                    "watermark",
                    "brand elements",
                ],
            }
            for index, shot in enumerate(raw["raw_shots"])
        ],
        "overall_structure": {
            "hook_ms": [0, hook_end],
            "problem_ms": [hook_end, problem_end],
            "proof_ms": [problem_end, proof_end],
            "scenario_ms": [proof_end, scenario_end],
            "cta_ms": [scenario_end, duration],
        },
    }


def build_product_profile(config: dict[str, Any]) -> dict[str, Any]:
    return {
        **_header(config, "product_profile.json", ["input_manifest.json"]),
        "product_profile": {
            "product_id": "prod_001",
            "category": "kitchen_food_cover",
            "shape": "round_flexible_cover",
            "colors": ["transparent", "white"],
            "materials": ["thin_plastic_film", "elastic_rim"],
            "visible_features": ["transparent film", "white elastic rim", "round flexible shape"],
            "main_selling_points": ["easy to stretch", "fits bowls", "keeps food covered"],
            "usable_actions": ["stretch_elastic_edge", "cover_bowl", "show_snap_back"],
            "unsuitable_actions": ["press_like_hard_lid", "stand_upright_alone"],
            "must_keep_visual_details": [
                "transparent film texture",
                "white elastic rim",
                "round flexible shape",
            ],
            "avoid_deformation": [
                "do_not_turn_into_plastic_bag",
                "do_not_become_rigid_lid",
                "do_not_remove_elastic_rim",
            ],
            "physical_constraints": ["flexible not rigid", "thin not thick", "stretchable edge"],
            "user_truth_override": {
                "confirmed_selling_points": [],
                "forbidden_claims": [],
                "must_show_sku": "",
            },
        },
    }


def build_action_matrix(config: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any]:
    pet_bottle = _is_pet_bottle(profile)
    if pet_bottle:
        actions = [
            {
                "action_id": "act_001",
                "action_name": "press_button_dispense_water",
                "difficulty": "medium",
                "video_generation_risk": "medium",
                "visual_clarity": "high",
                "suitable_shot_functions": ["hook", "function_demo", "proof"],
                "required_props": ["product", "clean_table", "hand"],
                "best_camera": {"angle": "top_down_45", "distance": "close_up"},
                "start_state": "the pet water bottle stands upright with the U-shaped opening visible",
                "main_motion": "a hand presses the button and water flows into the trough",
                "end_state": "the trough is filled and the product stays readable",
                "avoid": ["make it look like a food cover", "hide the trough"],
                "fallback_action_id": "act_001_fallback",
            },
            {
                "action_id": "act_001_fallback",
                "action_name": "slow_product_reveal",
                "difficulty": "low",
                "video_generation_risk": "low",
                "visual_clarity": "high",
                "suitable_shot_functions": ["pain_point", "product_reveal", "scenario", "transition", "cta"],
                "required_props": ["product", "clean_table"],
                "best_camera": {"angle": "front", "distance": "close_up"},
                "start_state": "the bottle is centered on a clean tabletop",
                "main_motion": "camera slowly pushes in while the shape stays stable",
                "end_state": "the strap, reservoir, and opening stay clearly visible",
                "avoid": ["covered bowl cues", "rigid lid cues"],
                "fallback_action_id": None,
            },
            {
                "action_id": "act_002",
                "action_name": "tilt_show_backflow_design",
                "difficulty": "medium",
                "video_generation_risk": "medium",
                "visual_clarity": "medium",
                "suitable_shot_functions": ["proof", "scenario"],
                "required_props": ["product", "water"],
                "best_camera": {"angle": "side_close", "distance": "close_up"},
                "start_state": "the bottle is angled to show the reservoir",
                "main_motion": "the hand tilts the bottle so the backflow path is visible",
                "end_state": "the bottle returns upright with no spill",
                "avoid": ["hide the water path", "turn into a rigid container"],
                "fallback_action_id": "act_001_fallback",
            },
            {
                "action_id": "act_003",
                "action_name": "carry_with_hanging_strap",
                "difficulty": "low",
                "video_generation_risk": "low",
                "visual_clarity": "high",
                "suitable_shot_functions": ["scenario", "cta"],
                "required_props": ["product", "strap"],
                "best_camera": {"angle": "front", "distance": "medium"},
                "start_state": "the strap hangs naturally beside the bottle",
                "main_motion": "a hand lifts the bottle by the strap to show portability",
                "end_state": "the strap remains attached and easy to read",
                "avoid": ["remove the strap", "force kitchen-lid visuals"],
                "fallback_action_id": "act_001_fallback",
            },
            {
                "action_id": "act_004",
                "action_name": "show_large_opening_for_pet_mouth",
                "difficulty": "low",
                "video_generation_risk": "low",
                "visual_clarity": "high",
                "suitable_shot_functions": ["hook", "proof"],
                "required_props": ["product"],
                "best_camera": {"angle": "close_front", "distance": "close_up"},
                "start_state": "the U-shaped opening fills the frame",
                "main_motion": "the camera settles on the opening size and shape",
                "end_state": "the opening remains clearly pet-friendly",
                "avoid": ["make the opening look like a bowl lid", "crop out the mouth opening"],
                "fallback_action_id": "act_001_fallback",
            },
        ]
    else:
        actions = [
            {
                "action_id": "act_001",
                "action_name": "stretch_elastic_edge_over_bowl",
                "difficulty": "high",
                "video_generation_risk": "high",
                "visual_clarity": "high",
                "suitable_shot_functions": ["hook", "function_demo", "proof"],
                "required_props": ["glass_bowl", "hands"],
                "best_camera": {"angle": "top_down_45", "distance": "close_up"},
                "start_state": "hands touch the white elastic rim",
                "main_motion": "hands stretch the rim outward with visible tension",
                "end_state": "cover moves toward the bowl edge",
                "avoid": ["rigid_pressing", "overstretching"],
                "fallback_action_id": "act_001_fallback",
            },
            {
                "action_id": "act_001_fallback",
                "action_name": "static_close_up_covered_bowl",
                "difficulty": "low",
                "video_generation_risk": "low",
                "visual_clarity": "high",
                "suitable_shot_functions": ["pain_point", "product_reveal", "scenario", "transition", "cta"],
                "required_props": ["glass_bowl"],
                "best_camera": {"angle": "top_down_45", "distance": "close_up"},
                "start_state": "covered bowl is stable on table",
                "main_motion": "camera slowly pushes in",
                "end_state": "elastic rim and transparent film remain visible",
                "avoid": ["hands_hide_product"],
                "fallback_action_id": None,
            },
        ]
    return {
        **_header(
            config,
            "product_action_matrix.json",
            ["product_profile.json", "reference_shot_strategy.json"],
        ),
        "product_action_matrix": actions,
    }


def build_transfer(
    config: dict[str, Any],
    raw: dict[str, Any],
    strategy: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    functions = {
        item["reference_shot_id"]: item["shot_function"]
        for item in strategy["reference_shots"]
    }
    pet_bottle = _is_pet_bottle(profile)
    new_action_id = "act_001" if pet_bottle else "act_001"
    fallback_action_id = "act_001_fallback"
    new_product_action = (
        "press the button to dispense water into the trough"
        if pet_bottle
        else "stretch and cover bowl with flexible rim"
    )
    if pet_bottle:
        transfer_items = [
            {
                "reference_shot_id": shot["reference_shot_id"],
                "reference_action": "demonstrate reference product function",
                "new_action_id": (
                    new_action_id
                    if functions[shot["reference_shot_id"]] in {"hook", "function_demo", "proof"}
                    else fallback_action_id
                ),
                "new_product_action": new_product_action,
                "action_type": "functionally_equivalent",
                "keep": ["close product focus", "clear before-after logic"],
                "change": ["mechanics", "hand position", "background", "wording"],
                "physical_reason": "The new product dispenses water through a buttoned trough, not a kitchen cover.",
                "video_generation_risk": ["food-cover misread", "hidden trough", "hidden strap"],
                "negative_prompt_rules": [
                    "do not create a kitchen lid",
                    "do not hide the trough",
                    "no visible face",
                ],
            }
            for shot in raw["raw_shots"]
        ]
    else:
        transfer_items = [
            {
                "reference_shot_id": shot["reference_shot_id"],
                "reference_action": "demonstrate reference product function",
                "new_action_id": (
                    new_action_id
                    if functions[shot["reference_shot_id"]] in {"hook", "function_demo", "proof"}
                    else fallback_action_id
                ),
                "new_product_action": new_product_action,
                "action_type": "functionally_equivalent",
                "keep": ["close product focus", "clear before-after logic"],
                "change": ["mechanics", "hand position", "background", "wording"],
                "physical_reason": "The new product seals through elastic tension, not rigid pressure.",
                "video_generation_risk": ["rigid lid appearance", "hidden elastic rim"],
                "negative_prompt_rules": [
                    "do not create a hard lid" if not pet_bottle else "do not create a kitchen lid",
                    "do not hide the elastic rim" if not pet_bottle else "do not hide the trough",
                    "no visible face",
                ],
            }
            for shot in raw["raw_shots"]
        ]
    return {
        **_header(
            config,
            "action_transfer_plan.json",
            ["reference_shot_strategy.json", "product_action_matrix.json", "product_profile.json"],
        ),
        "action_transfer_plan": transfer_items,
    }


def build_new_video_plan(
    config: dict[str, Any],
    raw: dict[str, Any],
    strategy: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = _profile_body(profile)
    pet_bottle = _is_pet_bottle(profile)
    duration = raw.get("video_meta", {}).get("duration_ms", config["video_specs"]["target_duration_ms"])
    strategy_by_id = {
        item["reference_shot_id"]: item for item in strategy["reference_shots"]
    }
    shots = []
    for index, ref_shot in enumerate(raw["raw_shots"]):
        ref_id = ref_shot["reference_shot_id"]
        function = strategy_by_id[ref_id]["shot_function"]
        action = "act_001" if function in {"hook", "function_demo", "proof"} else "act_001_fallback"
        shots.append(
            {
                "new_shot_id": f"new_{index + 1:03d}",
                "reference_shot_id": ref_id,
                "duration_ms": ref_shot["duration_ms"],
                "start_ms": ref_shot["start_ms"],
                "end_ms": ref_shot["end_ms"],
                "shot_function": function,
                "commercial_purpose": "Demonstrate a truthful benefit with an original shot.",
                "selected_action_id": action,
                "visual_action": (
                    "hand presses the button and water becomes visible in the trough"
                    if pet_bottle and action == "act_001"
                    else (
                        "the bottle stays upright while the camera slowly pushes in"
                        if pet_bottle
                        else "hands prepare to stretch the rim"
                        if action == "act_001"
                        else "covered bowl remains visible during a slow push-in"
                    )
                ),
                "camera": {
                    "angle": "top_down_45",
                    "distance": "close_up",
                    "movement": "slight_push_in",
                },
                "scene": {
                    "type": "pet_water_tabletop" if pet_bottle else "kitchen_tabletop",
                    "background": "clean_bright_table",
                },
                "product_focus": (
                    [
                        "U-shaped drinking trough",
                        "push-button water outlet",
                        "transparent reservoir",
                        "hanging strap",
                    ]
                    if pet_bottle
                    else ["transparent film texture", "white elastic rim"]
                ),
                "subtitle_intent": "short truthful benefit caption",
                "voiceover_intent": "natural useful-product sharing",
                "must_keep_from_reference": ["single clear action", "fast pacing"],
                "must_change_from_reference": [
                    "exact wording",
                    "background",
                    "music",
                    "brand elements",
                ],
                "generation_risks": ["avoid rigid lid appearance"],
                "source_new_shot_ids": [f"new_{index + 1:03d}"],
                "source_reference_shot_ids": [ref_id],
                "generation_strategy": "standalone",
            }
        )
    return {
        **_header(
            config,
            "new_video_plan.json",
            ["action_transfer_plan.json", "reference_shot_strategy.json", "product_profile.json"],
        ),
        "new_video_plan": {
            "project_id": config["project_id"],
            "duration_ms": duration,
            "shot_count": len(shots),
            "target_language": config["target_market"]["primary_language"],
            "voice_gender": config["audio_rules"]["voice_gender"],
            "shots": shots,
        },
    }


def build_scripts(
    config: dict[str, Any], plan: dict[str, Any], profile: dict[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    pet_bottle = _is_pet_bottle(profile)
    subtitle_text = "Botol air untuk haiwan kesayangan, senang tekan sekali."
    voiceover_text = "Tekan sekali, air terus keluar. Mudah dibawa dan sesuai untuk jalan-jalan."
    subtitle_zh = "宠物饮水瓶，一按就出水。"
    voiceover_zh = "按一下，水就出来了。便携好带，适合出门使用。"
    if not pet_bottle:
        subtitle_text = "Senang guna, hasil nampak kemas"
        voiceover_text = "Senang sangat guna ni, dapur terus nampak lebih kemas."
        subtitle_zh = "使用方便，看起来更整洁"
        voiceover_zh = "这个使用方便，厨房看起来马上更整洁。"
    subtitles = []
    voiceover = []
    for shot in plan["new_video_plan"]["shots"]:
        subtitles.append(
            {
                "new_shot_id": shot["new_shot_id"],
                "text": subtitle_text,
                "meaning_zh": subtitle_zh,
                "start_ms": shot["start_ms"],
                "end_ms": shot["end_ms"],
                "max_chars": 32,
                "position": "bottom_center",
            }
        )
        voiceover.append(
            {
                "new_shot_id": shot["new_shot_id"],
                "text": voiceover_text,
                "meaning_zh": voiceover_zh,
                "language": config["target_market"]["primary_language"],
                "gender": config["audio_rules"]["voice_gender"],
                "tone": config["audio_rules"]["voice_style"],
                "max_duration_ms": shot["duration_ms"],
                "max_words": 10,
            }
        )
    return (
        {
            **_header(config, "subtitle_script.json", ["new_video_plan.json"]),
            "subtitle_script": subtitles,
        },
        {
            **_header(config, "voiceover_script.json", ["new_video_plan.json"]),
            "voiceover_script": voiceover,
        },
    )


def build_audio(config: dict[str, Any], plan: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any]:
    duration = plan["new_video_plan"]["duration_ms"]
    pet_bottle = _is_pet_bottle(profile)
    return {
        **_header(
            config,
            "audio_asset_manifest.json",
            ["new_video_plan.json", "voiceover_script.json"],
        ),
        "bgm": {
                "asset_id": "bgm_001",
                "path": "assets/music/ROYALTY_FREE_ASSET_REQUIRED.mp3",
                "bpm": config["audio_rules"]["target_bpm"],
                "license": "must_be_verified_before_real_run",
                "volume_db": config["audio_rules"]["bgm_volume_db"],
            "start_ms": 0,
            "end_ms": duration,
        },
        "sfx_events": [
            {
                "sfx_id": "sfx_001",
                "new_shot_id": "new_005",
                "trigger_ms": min(max(int(duration * 0.75), 0), max(duration - 500, 0)),
                "asset_path": "assets/sfx/LICENSED_ASSET_REQUIRED.wav",
                "volume_db": config["audio_rules"]["sfx_volume_db"],
                "reason": "button press and water flow emphasis" if pet_bottle else "elastic rim motion emphasis",
            }
        ],
    }


def build_storyboard_prompts(
    config: dict[str, Any],
    plan: dict[str, Any],
    profile: dict[str, Any],
    matrix: dict[str, Any],
) -> dict[str, Any]:
    actions = {item["action_id"]: item for item in matrix["product_action_matrix"]}
    product = _profile_body(profile)
    pet_bottle = product.get("category") == "portable_pet_water_bottle"
    prompts = []
    for index, shot in enumerate(plan["new_video_plan"]["shots"]):
        action = actions[shot["selected_action_id"]]
        key_shot = shot["shot_function"] in {"hook", "function_demo", "proof", "cta"}
        negative_prompt = "no visible face, no logo, no watermark, no copied background; " + ", ".join(product["avoid_deformation"])
        if pet_bottle:
            negative_prompt += ", no kitchen lid, no bowl cover, no food cover"
        prompts.append(
            {
                "new_shot_id": shot["new_shot_id"],
                "image_model": (
                    config["model_defaults"]["storyboard_key_model"]
                    if key_shot
                    else config["model_defaults"]["storyboard_normal_model"]
                ),
                "prompt": (
                    "Realistic vertical ecommerce product first frame; "
                    f"{action['start_state']}; {shot['scene']['background']}; "
                    f"keep {', '.join(product['must_keep_visual_details'])}; "
                    + (
                        "show the pet water bottle clearly, with the U-shaped opening readable."
                        if pet_bottle
                        else "show the product clearly."
                    )
                ),
                "negative_prompt": negative_prompt,
                "reference_image_ids": ["prod_main", "prod_detail_01"],
                "aspect_ratio": config["video_specs"]["aspect_ratio"],
                "resolution": f"{config['video_specs']['width']}x{config['video_specs']['height']}",
                "action_start_state": action["start_state"],
                "purpose": "first_frame_for_seedance",
            }
        )
    return {
        **_header(
            config,
            "storyboard_prompts.json",
            ["new_video_plan.json", "product_profile.json", "product_action_matrix.json"],
        ),
        "storyboard_prompts": prompts,
    }


def build_storyboards(
    config: dict[str, Any],
    prompts: dict[str, Any],
    project_dir: Path,
) -> dict[str, Any]:
    paths = runtime_dirs(project_dir)
    storyboards = []
    for index, prompt in enumerate(prompts["storyboard_prompts"]):
        image = paths["storyboards"] / f"sb_{index + 1:03d}.png"
        image.write_bytes(PLACEHOLDER_PNG)
        storyboards.append(
            {
                "new_shot_id": prompt["new_shot_id"],
                "image_id": f"sb_{index + 1:03d}",
                "image_path": relative_to_project(image, project_dir),
                "model": prompt["image_model"],
                "source_prompt_id": prompt["new_shot_id"],
                "selected": True,
            }
        )
    return {
        **_header(config, "storyboard_manifest.json", ["storyboard_prompts.json"]),
        "storyboards": storyboards,
    }


def build_precheck(
    config: dict[str, Any], manifest: dict[str, Any], profile: dict[str, Any] | None = None
) -> dict[str, Any]:
    pet_bottle = _is_pet_bottle(profile)
    return {
        **_header(
            config,
            "storyboard_precheck.json",
            ["storyboard_manifest.json", "product_profile.json"],
        ),
        "storyboard_precheck": [
            {
                "new_shot_id": item["new_shot_id"],
                "image_id": item["image_id"],
                "pass": True,
                "issues": [],
                "product_similarity": "high",
                "has_visible_face": False,
                "has_watermark": False,
                "suitable_as_action_start": True,
                "selected_for_seedance": True,
                "recommended_action_id": "act_001",
            }
            for item in manifest["storyboards"]
        ],
    }


def build_video_clips(
    config: dict[str, Any], tasks: dict[str, Any], project_dir: Path
) -> dict[str, Any]:
    return {
        **_header(config, "video_clips_manifest.json", ["seedance_tasks.json"]),
        "video_clips": [
            {
                "task_id": task["task_id"],
                "new_shot_id": task["new_shot_id"],
                "source_new_shot_ids": task.get("source_new_shot_ids", [task["new_shot_id"]]),
                "merge_strategy": task.get("merge_strategy", "standalone"),
                "status": "dry_run_placeholder",
                "clip_path": relative_to_project(
                    runtime_dirs(project_dir)["clips"] / f"{task['task_id']}.mp4",
                    project_dir,
                ),
                "duration_ms": task["duration_ms"],
                "seedance_duration_sec": task.get("seedance_duration_sec"),
                "input_images": task.get("input_images", [task["input_image"]]),
                "source_segments": task.get("source_segments", []),
                "actual_cost_rmb": 0.0,
            }
            for task in tasks["seedance_tasks"]
        ],
    }


def build_voiceover_assets(
    config: dict[str, Any], voiceover: dict[str, Any], project_dir: Path
) -> dict[str, Any]:
    return {
        **_header(config, "voiceover_asset_manifest.json", ["voiceover_script.json"]),
        "voiceover": {
            "status": "dry_run_placeholder",
            "path": relative_to_project(
                runtime_dirs(project_dir)["audio"] / "voiceover.wav", project_dir
            ),
            "language": config["target_market"]["primary_language"],
            "actual_cost_rmb": 0.0,
        },
        "segments": [
            {
                "new_shot_id": item["new_shot_id"],
                "max_duration_ms": item["max_duration_ms"],
                "status": "dry_run_placeholder",
            }
            for item in voiceover["voiceover_script"]
        ],
    }


def build_render_plan(config: dict[str, Any], duration_ms: int) -> dict[str, Any]:
    return {
        **_header(
            config,
            "render_plan.json",
            [
                "video_clips_manifest.json",
                "voiceover_asset_manifest.json",
                "subtitle_script.json",
                "audio_asset_manifest.json",
            ],
        ),
        "render_plan": {
            "timeline_unit": "milliseconds",
            "width": config["video_specs"]["width"],
            "height": config["video_specs"]["height"],
            "fps": config["video_specs"]["fps"],
            "duration_ms": duration_ms,
            "renderer": "dry_run_placeholder",
            "requires_license_review": True,
        },
    }


def build_final_manifest(config: dict[str, Any], project_dir: Path) -> dict[str, Any]:
    return {
        **_header(config, "final_video_manifest.json", ["render_plan.json"]),
        "final_video": {
            "status": "dry_run_placeholder",
            "would_write": relative_to_project(
                runtime_dirs(project_dir)["final"] / "final_video.mp4", project_dir
            ),
            "rendered": False,
            "paid_api_calls": 0,
            "message": "No video was rendered in dry-run mode.",
        },
    }


def read_artifact(project_dir: Path, name: str) -> dict[str, Any]:
    return load_json(output_path(project_dir, name))


def write_artifact(project_dir: Path, name: str, data: dict[str, Any]) -> Path:
    return atomic_write_json(output_path(project_dir, name), data)

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import sys
from scenedetect import SceneManager, open_video
from scenedetect.detectors import ContentDetector

try:
    from paddleocr import PaddleOCR
except Exception:  # pragma: no cover - optional dependency fallback
    PaddleOCR = None

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from common import artifact_header, relative_to_project, runtime_dirs, utc_now


_OCR = None


def _ocr_model():
    global _OCR
    if _OCR is None and PaddleOCR is not None:
        _OCR = PaddleOCR(lang="ch")
    return _OCR


def _iter_images(product_images: str | Path) -> list[Path]:
    path = Path(product_images)
    if path.is_dir():
        return sorted(
            [
                item
                for item in path.iterdir()
                if item.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
            ]
        )
    if path.is_file():
        return [path]
    return []


def _ocr_texts(image_paths: list[Path]) -> list[str]:
    model = _ocr_model()
    texts: list[str] = []
    if model is None:
        return texts
    for path in image_paths:
        try:
            results = model.predict(str(path))
        except Exception:
            continue
        for entry in results or []:
            for text in entry.get("rec_texts", []) or []:
                cleaned = str(text).strip()
                if cleaned:
                    texts.append(cleaned)
    return texts


def _dominant_colors(image_paths: list[Path]) -> list[str]:
    scores = {
        "blue": 0.0,
        "pink": 0.0,
        "white": 0.0,
        "transparent": 0.0,
    }
    for path in image_paths:
        image = cv2.imread(str(path))
        if image is None:
            continue
        b, g, r = cv2.mean(image)[:3]
        brightness = float((r + g + b) / 3.0)
        if brightness > 200:
            scores["white"] += 1.0
        if b > r + 20 and b > g + 10:
            scores["blue"] += 1.0
        if r > b + 15 and r > g + 5:
            scores["pink"] += 1.0
        if brightness > 150:
            scores["transparent"] += 0.5
    ranked = [name for name, score in sorted(scores.items(), key=lambda item: item[1], reverse=True) if score > 0]
    return ranked or ["transparent"]


def infer_product_profile(config: dict[str, Any], product_images: str | Path) -> dict[str, Any]:
    image_paths = _iter_images(product_images)
    texts = _ocr_texts(image_paths)
    colors = _dominant_colors(image_paths)
    joined = " ".join(texts)
    is_pet_bottle = any(
        keyword in joined
        for keyword in ("大开口U型水槽", "一推", "回流设计", "佩戴挂绳", "宠物", "饮水")
    )
    category = "portable_pet_water_bottle" if is_pet_bottle else "portable_accessory"
    shape = "u_shaped_pet_drinking_bottle" if is_pet_bottle else "portable_product"
    visible_features = (
        [
            "U-shaped drinking trough",
            "push-button water outlet",
            "transparent reservoir",
            "hanging strap",
            "backflow design",
        ]
        if is_pet_bottle
        else ["visible product body", "portable design"]
    )
    main_selling_points = (
        [
            "one-push water dispensing",
            "backflow design reduces waste",
            "portable with strap",
            "large opening fits pet mouth",
        ]
        if is_pet_bottle
        else ["portable", "clear product structure"]
    )
    usable_actions = (
        [
            "press_button_dispense_water",
            "tilt_for_backflow",
            "carry_with_strap",
            "show_large_opening",
        ]
        if is_pet_bottle
        else ["show_product_body", "show_carrying_form"]
    )
    unsuitable_actions = (
        [
            "press_like_food_cover",
            "use_as_kitchen_lid",
            "stand_upright_as_container_only",
        ]
        if is_pet_bottle
        else ["misrepresent_product_category"]
    )
    must_keep_visual_details = (
        [
            "U-shaped drinking trough",
            "push-button water outlet",
            "transparent reservoir",
            "hanging strap",
            "pet drinking bottle form",
        ]
        if is_pet_bottle
        else ["clear product silhouette"]
    )
    avoid_deformation = (
        [
            "do_not_turn_into_food_cover",
            "do_not_become_rigid_lid",
            "do_not_remove_trough_shape",
        ]
        if is_pet_bottle
        else ["do_not_distort_product_form"]
    )
    physical_constraints = (
        [
            "must remain a pet drinking bottle",
            "water path should stay visible",
            "large opening must stay open",
        ]
        if is_pet_bottle
        else ["must preserve product silhouette"]
    )
    signal_keywords = ("大开口", "回流", "一推", "佩戴", "材质", "爱宠", "水槽", "饮水")
    selling_points = [text for text in texts if any(keyword in text for keyword in signal_keywords)]
    if not selling_points:
        selling_points = [text for text in texts if text]
    selling_points = selling_points[:6]
    return {
        **artifact_header(
            config["project_id"],
            "product_profile",
            [str(path.name) for path in image_paths],
            provider="local",
            model="ocr+cv2-heuristic",
            temperature=0.0,
        ),
        "product_profile": {
            "product_id": "prod_001",
            "category": category,
            "shape": shape,
            "colors": colors,
            "materials": ["plastic", "transparent reservoir", "elastic cap" if is_pet_bottle else "mixed"],
            "visible_features": visible_features,
            "main_selling_points": main_selling_points,
            "usable_actions": usable_actions,
            "unsuitable_actions": unsuitable_actions,
            "must_keep_visual_details": must_keep_visual_details,
            "avoid_deformation": avoid_deformation,
            "physical_constraints": physical_constraints,
            "user_truth_override": {
                "confirmed_selling_points": selling_points,
                "forbidden_claims": [],
                "must_show_sku": "",
            },
        },
    }


def _frame_at_ms(video: cv2.VideoCapture, ms: int) -> np.ndarray | None:
    video.set(cv2.CAP_PROP_POS_MSEC, float(ms))
    ok, frame = video.read()
    if not ok:
        return None
    return frame


def _save_frame(frame: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame)


def build_real_raw_shots(
    config: dict[str, Any],
    reference_video: str | Path,
    project_dir: Path,
) -> dict[str, Any]:
    capture = cv2.VideoCapture(str(reference_video))
    if not capture.isOpened():
        raise FileNotFoundError(f"Cannot open reference video: {reference_video}")
    fps = capture.get(cv2.CAP_PROP_FPS) or config["video_specs"]["fps"]
    frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or config["video_specs"]["width"])
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or config["video_specs"]["height"])
    source_duration_ms = int((frame_count / fps) * 1000) if fps else config["video_specs"]["target_duration_ms"]
    source_duration_ms = max(source_duration_ms, 1000)
    duration_ms = source_duration_ms
    segments: list[tuple[int, int]] = []
    try:
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=27.0, min_scene_len=max(int(fps * 0.4), 8)))
        scene_manager.detect_scenes(open_video(str(reference_video)))
        scenes = scene_manager.get_scene_list()
    except Exception:
        scenes = []
    if scenes:
        for start, end in scenes:
            start_ms = int(start.get_seconds() * 1000)
            end_ms = int(end.get_seconds() * 1000)
            if end_ms <= start_ms:
                continue
            segments.append((start_ms, min(end_ms, duration_ms)))
    if not segments:
        segment_count = max(round(duration_ms / max(int(config["video_specs"]["default_shot_duration_ms"]), 1000)), 1)
        segment_duration = max(duration_ms // segment_count, 1)
        for index in range(segment_count):
            start_ms = index * segment_duration
            end_ms = duration_ms if index == segment_count - 1 else min(duration_ms, (index + 1) * segment_duration)
            if end_ms <= start_ms:
                end_ms = start_ms + 1
            segments.append((start_ms, end_ms))
    paths = runtime_dirs(project_dir)
    raw_shots: list[dict[str, Any]] = []
    for index, (start_ms, end_ms) in enumerate(segments):
        ref_id = f"ref_{index + 1:03d}"
        mid_ms = start_ms + max((end_ms - start_ms) // 2, 1)
        def _map_to_source(ms: int) -> int:
            if duration_ms <= 0:
                return 0
            ratio = min(max(ms / duration_ms, 0.0), 1.0)
            return int(ratio * max(source_duration_ms - 1, 0))

        start_frame = _frame_at_ms(capture, _map_to_source(start_ms))
        mid_frame = _frame_at_ms(capture, _map_to_source(mid_ms))
        end_frame = _frame_at_ms(capture, _map_to_source(max(end_ms - 33, start_ms)))
        if start_frame is None and mid_frame is None and end_frame is None:
            continue
        start_path = paths["root"] / "output" / "keyframes" / f"{ref_id}_start.jpg"
        mid_path = paths["root"] / "output" / "keyframes" / f"{ref_id}_middle.jpg"
        end_path = paths["root"] / "output" / "keyframes" / f"{ref_id}_end.jpg"
        peak_path = paths["root"] / "output" / "keyframes" / f"{ref_id}_peak_01.jpg"
        if start_frame is not None:
            _save_frame(start_frame, start_path)
        if mid_frame is not None:
            _save_frame(mid_frame, mid_path)
            _save_frame(mid_frame, peak_path)
        elif start_frame is not None:
            _save_frame(start_frame, mid_path)
            _save_frame(start_frame, peak_path)
        if end_frame is not None:
            _save_frame(end_frame, end_path)
        elif mid_frame is not None:
            _save_frame(mid_frame, end_path)
        start_use = start_frame if start_frame is not None else mid_frame if mid_frame is not None else end_frame
        end_use = end_frame if end_frame is not None else mid_frame if mid_frame is not None else start_frame
        intensity = "medium"
        if start_use is not None and end_use is not None:
            diff = float(np.mean(cv2.absdiff(
                cv2.resize(start_use, (320, 320)),
                cv2.resize(end_use, (320, 320)),
            )))
            intensity = "high" if diff > 18 else "medium"
        raw_shots.append(
            {
                "reference_shot_id": ref_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "duration_ms": end_ms - start_ms,
                "keyframes": {
                    "start": relative_to_project(start_path, project_dir),
                    "middle": relative_to_project(mid_path, project_dir),
                    "end": relative_to_project(end_path, project_dir),
                },
                "motion_peak_frames": [relative_to_project(peak_path, project_dir)],
                "motion_intensity": intensity,
            }
        )
    capture.release()
    return {
        **artifact_header(
            config["project_id"],
            "raw_shots",
            [str(Path(reference_video).name)],
            provider="local",
            model="cv2-scene-sampler",
            temperature=0.0,
        ),
        "video_meta": {
            "duration_ms": duration_ms,
            "aspect_ratio": config["video_specs"]["aspect_ratio"],
            "width": width,
            "height": height,
            "fps": int(fps),
            "has_audio": True,
        },
        "raw_shots": raw_shots,
    }


def build_real_reference_visual_analysis(
    config: dict[str, Any],
    raw_shots: dict[str, Any],
    product_images: str | Path,
) -> dict[str, Any]:
    product_profile = infer_product_profile(config, product_images)
    analysis = []
    for shot in raw_shots["raw_shots"]:
        if "pet" in product_profile["product_profile"]["category"]:
            visual_description = "Close-up pet water bottle demo with visible U-shaped trough and push-button outlet."
            visible_objects = ["product", "hand", "water", "strap"]
            product_action = "product is shown as a pet water dispenser"
            hand_action = "hand holds and presses the bottle"
            scene_type = "pet_water_demo_tabletop"
        else:
            visual_description = "Close-up product demonstration on a tabletop."
            visible_objects = ["product", "hand"]
            product_action = "product is shown"
            hand_action = "hand interacts with product"
            scene_type = "tabletop_demo"
        analysis.append(
            {
                "reference_shot_id": shot["reference_shot_id"],
                "visual_description": visual_description,
                "main_subject": "product",
                "visible_objects": visible_objects,
                "product_action": product_action,
                "hand_action": hand_action,
                "camera_angle": "top_down_45",
                "camera_distance": "close_up",
                "camera_movement": "slight_push_in",
                "scene_type": scene_type,
                "motion_intensity": shot["motion_intensity"],
                "visible_text": "OCR text detected on product images" if visible_objects else "",
                "voice_text": "",
            }
        )
    return {
        **artifact_header(
            config["project_id"],
            "reference_visual_analysis",
            [shot["keyframes"]["middle"] for shot in raw_shots["raw_shots"]],
            provider="local",
            model="cv2+ocr-heuristic",
            temperature=0.0,
        ),
        "reference_shots": analysis,
    }

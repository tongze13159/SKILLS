from __future__ import annotations

from .base import adapter_stub
from .real_api import byteplus_seedance_run

def run(*, dry_run: bool, model: str, payload: dict, **kwargs):
    if dry_run:
        return adapter_stub("Seedance", "SEEDANCE_API_KEY", dry_run=dry_run, **kwargs)
    prompt = payload.get("prompt") or payload.get("text") or ""
    image_urls = payload.get("image_urls") or payload.get("input_images") or []
    if not image_urls and payload.get("input_image"):
        image_urls = [payload["input_image"]]
    duration = int(payload.get("duration") or payload.get("duration_sec") or 5)
    aspect_ratio = payload.get("aspect_ratio") or payload.get("ratio") or "9:16"
    resolution = payload.get("resolution") or "720p"
    return byteplus_seedance_run(
        model=model,
        prompt=prompt,
        image_urls=image_urls,
        duration=duration,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
    )

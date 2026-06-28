from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import adapter_stub
from .real_api import gemini_generate_json, gemini_video_json

def run(
    *,
    dry_run: bool,
    model: str,
    prompt: str,
    video_path: Path | None = None,
    parts: list[dict[str, Any]] | None = None,
    schema: dict[str, Any] | None = None,
    **kwargs,
):
    if dry_run:
        return adapter_stub("Gemini Video", "GEMINI_API_KEY", dry_run=dry_run, **kwargs)
    if video_path is not None:
        return gemini_video_json(model=model, prompt=prompt, video_path=video_path, schema=schema)
    return gemini_generate_json(model=model, prompt=prompt, parts=parts or [], schema=schema)

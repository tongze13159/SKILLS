from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .base import adapter_stub
from .real_api import openai_vision_json

def run(
    *,
    dry_run: bool,
    model: str,
    system_prompt: str,
    user_prompt: str,
    image_paths: Iterable[Path],
    schema: dict[str, Any] | None = None,
    **kwargs,
):
    if dry_run:
        return adapter_stub("OpenAI Vision", "OPENAI_API_KEY", dry_run=dry_run, **kwargs)
    return openai_vision_json(
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        image_paths=image_paths,
        schema=schema,
    )

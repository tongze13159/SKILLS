from __future__ import annotations

from typing import Any

from .base import adapter_stub
from .real_api import openai_chat_json, load_prompt


def run(*, dry_run: bool, model: str, system_prompt: str, user_prompt: str, schema: dict[str, Any] | None = None, **kwargs):
    if dry_run:
        return adapter_stub("OpenAI LLM", "OPENAI_API_KEY", dry_run=dry_run, **kwargs)
    return openai_chat_json(model=model, system_prompt=system_prompt, user_prompt=user_prompt, schema=schema)

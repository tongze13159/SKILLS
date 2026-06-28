from __future__ import annotations

from pathlib import Path

from .base import adapter_stub
from .real_api import openai_transcribe

def run(*, dry_run: bool, audio_path: Path, model: str, **kwargs):
    if dry_run:
        return adapter_stub("OpenAI STT", "OPENAI_API_KEY", dry_run=dry_run, **kwargs)
    return {"text": openai_transcribe(audio_path, model=model)}

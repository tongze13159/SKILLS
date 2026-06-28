from __future__ import annotations

from pathlib import Path

from .base import adapter_stub
from .real_api import elevenlabs_tts

def run(*, dry_run: bool, text: str, output_path: Path, voice_id: str | None = None, model_id: str | None = None, **kwargs):
    if dry_run:
        return adapter_stub("ElevenLabs", "ELEVENLABS_API_KEY", dry_run=dry_run, **kwargs)
    audio = elevenlabs_tts(text, voice_id=voice_id, model_id=model_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio)
    return {"ok": True, "artifact_path": str(output_path), "raw_response_path": None, "cost_rmb": 0.0, "error": None, "retryable": False}

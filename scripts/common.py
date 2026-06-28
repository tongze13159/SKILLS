from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = SKILL_ROOT / "schemas"
DEFAULT_CONFIG = SKILL_ROOT / "config" / "default_project_config.json"
DEFAULT_ENV_FILE = SKILL_ROOT / ".env"

API_KEY_ALIASES = {
    "OPENAI_API_KEY": ("OPENAI_API_KEY",),
    "GEMINI_API_KEY": ("GEMINI_API_KEY",),
    "BFL_API_KEY": ("BFL_API_KEY", "FLUX_API_KEY"),
    "LAS_API_KEY": (
        "LAS_API_KEY",
        "VOLCENGINE_LAS_API_KEY",
    ),
    "ARK_API_KEY": (
        "ARK_API_KEY",
        "SEEDANCE_API_KEY",
        "BYTEPLUS_API_KEY",
        "VOLCENGINE_API_KEY",
    ),
    "SEEDANCE_API_KEY": (
        "SEEDANCE_API_KEY",
        "ARK_API_KEY",
        "BYTEPLUS_API_KEY",
        "VOLCENGINE_API_KEY",
    ),
    "ELEVENLABS_API_KEY": ("ELEVENLABS_API_KEY",),
}

MANIFEST_NAMES = {
    "pipeline_state.json",
    "cost_ledger.json",
    "seedance_tasks.json",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path | str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path: Path | str, data: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return target


def artifact_header(
    project_id: str,
    artifact_id: str,
    source_artifacts: Iterable[str] = (),
    *,
    provider: str = "local",
    model: str = "deterministic",
    temperature: float | None = 0.0,
    cost_rmb: float = 0.0,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "project_id": project_id,
        "artifact_id": artifact_id,
        "created_at": utc_now(),
        "source_artifacts": list(source_artifacts),
        "model_info": {
            "provider": provider,
            "model": model,
            "temperature": temperature,
        },
        "cost_rmb": round(cost_rmb, 4),
    }


def runtime_dirs(project_dir: Path | str) -> dict[str, Path]:
    root = Path(project_dir).resolve()
    paths = {
        "root": root,
        "artifacts": root / "output" / "artifacts",
        "manifests": root / "output" / "manifests",
        "storyboards": root / "output" / "storyboards",
        "clips": root / "output" / "clips",
        "audio": root / "output" / "audio",
        "final": root / "output" / "final",
        "logs": root / "logs",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def output_path(project_dir: Path | str, artifact_name: str) -> Path:
    paths = runtime_dirs(project_dir)
    if artifact_name in MANIFEST_NAMES:
        return paths["manifests"] / artifact_name
    if artifact_name in {"final_video_manifest.json", "final_video.mp4"}:
        return paths["final"] / artifact_name
    if artifact_name == "voiceover_asset_manifest.json":
        return paths["audio"] / artifact_name
    return paths["artifacts"] / artifact_name


def relative_to_project(path: Path | str, project_dir: Path | str) -> str:
    return Path(path).resolve().relative_to(Path(project_dir).resolve()).as_posix()


def stable_hash(*values: Any) -> str:
    payload = json.dumps(values, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def schema_for_artifact(artifact_name: str) -> Path:
    schema = SCHEMA_DIR / artifact_name.replace(".json", ".schema.json")
    if not schema.exists():
        raise FileNotFoundError(f"No Schema registered for {artifact_name}: {schema}")
    return schema


def load_env_file(path: Path | str = DEFAULT_ENV_FILE) -> Path:
    env_path = Path(path)
    if not env_path.exists():
        return env_path
    with env_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            os.environ.setdefault(key, value.strip())
    return env_path


def normalize_api_key_aliases() -> None:
    for primary_key, aliases in API_KEY_ALIASES.items():
        value = next((os.environ.get(alias) for alias in aliases if os.environ.get(alias)), None)
        if not value:
            continue
        for alias in aliases:
            os.environ.setdefault(alias, value)
        os.environ.setdefault(primary_key, value)


def ensure_runtime_env() -> None:
    load_env_file()
    normalize_api_key_aliases()


def required_api_keys() -> tuple[str, ...]:
    ensure_runtime_env()
    return (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "SEEDANCE_API_KEY",
        "ELEVENLABS_API_KEY",
    )


def missing_api_keys() -> list[str]:
    ensure_runtime_env()
    return [key for key in required_api_keys() if not os.environ.get(key)]

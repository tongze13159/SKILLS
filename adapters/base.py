from __future__ import annotations

import os
from typing import Any

from common import ensure_runtime_env

def adapter_stub(provider: str, key_name: str, *, dry_run: bool, **_: Any) -> dict:
    if dry_run:
        return {"ok": True, "artifact_path": None, "raw_response_path": None, "cost_rmb": 0.0, "error": None, "retryable": False}
    ensure_runtime_env()
    if not os.environ.get(key_name):
        return {"ok": False, "artifact_path": None, "raw_response_path": None, "cost_rmb": 0.0, "error": f"{key_name} is not configured", "retryable": False}
    return {"ok": False, "artifact_path": None, "raw_response_path": None, "cost_rmb": 0.0, "error": f"{provider} real adapter is not implemented in v1", "retryable": False}

from __future__ import annotations

from .base import adapter_stub
from .real_api import fal_run_json

def run(*, dry_run: bool, endpoint_id: str, payload: dict, **kwargs):
    if dry_run:
        return adapter_stub("FLUX", "BFL_API_KEY", dry_run=dry_run, **kwargs)
    return fal_run_json(endpoint_id=endpoint_id, payload=payload)

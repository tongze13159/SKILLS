from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable


class MockAdapter:
    """Return deterministic fixtures without reading credentials or calling providers."""

    BLOCKED_PROVIDERS = (
        "Gemini",
        "OpenAI",
        "FLUX",
        "Seedance",
        "ElevenLabs",
    )

    def __init__(self, mock_input_dir: Path, load_json: Callable[[Path], dict[str, Any]]):
        self.mock_input_dir = mock_input_dir.resolve()
        self._load_json = load_json
        self.calls: list[dict[str, str]] = []

    def fixture(self, artifact_name: str) -> dict[str, Any]:
        path = self.mock_input_dir / artifact_name
        if not path.is_file():
            raise FileNotFoundError(f"Mock fixture not found: {path}")
        data = self._load_json(path)
        self.calls.append({"mode": "fixture", "artifact": artifact_name})
        return deepcopy(data)

    def simulate(
        self,
        artifact_name: str,
        factory: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        data = factory()
        if "model_info" in data:
            data["model_info"] = {
                "provider": "mock",
                "model": "mock-adapter",
                "temperature": 0.0,
            }
        data["cost_rmb"] = 0.0
        self.calls.append({"mode": "simulated", "artifact": artifact_name})
        return data

    def assert_offline(self) -> None:
        """Document the invariant checked by the orchestrator before successful exit."""
        for call in self.calls:
            if call["mode"] not in {"fixture", "simulated"}:
                raise RuntimeError(f"Non-mock adapter call detected: {call}")

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from _support import ROOT
from run_pipeline import run


class MockValidationStopTests(unittest.TestCase):
    def test_invalid_mock_stops_before_next_step(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mock_input = root / "mock_input"
            shutil.copytree(ROOT / "tests/mock_input", mock_input)
            invalid_path = mock_input / "ocr_subtitles.json"
            invalid = json.loads(invalid_path.read_text(encoding="utf-8"))
            invalid.pop("subtitle_groups")
            invalid_path.write_text(
                json.dumps(invalid, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            project = root / "run"
            with self.assertRaisesRegex(ValueError, "subtitle_groups"):
                run(
                    project_dir=project,
                    config_path=ROOT / "config/default_project_config.json",
                    mock_input_dir=mock_input,
                    dry_run=True,
                )
            self.assertFalse(
                (project / "output/artifacts/voice_transcript.json").exists()
            )
            state = json.loads(
                (project / "output/manifests/pipeline_state.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["current_step"], "03_extract_subtitles")


if __name__ == "__main__":
    unittest.main()

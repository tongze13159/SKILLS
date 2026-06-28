import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import ROOT
from common import load_json
from run_pipeline import run


class DryRunIntegrationTests(unittest.TestCase):
    def test_full_pipeline_and_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            config = ROOT / "config/default_project_config.json"
            self.assertEqual(run(project_dir=project, config_path=config, reference_video="fake.mp4", product_images="product_images", dry_run=True), 0)
            state = load_json(project / "output/manifests/pipeline_state.json")
            self.assertEqual(state["status"], "completed")
            self.assertEqual(len(state["steps"]), 19)
            self.assertTrue((project / "output/manifests/seedance_tasks.json").exists())
            raw = load_json(project / "output/artifacts/raw_shots.json")
            self.assertEqual(raw["artifact_id"], "raw_shots_mock")
            self.assertEqual(len(raw["raw_shots"]), 3)
            for name in (
                "reference_shot_strategy.json",
                "product_action_matrix.json",
                "action_transfer_plan.json",
                "new_video_plan.json",
                "subtitle_script.json",
                "voiceover_script.json",
                "storyboard_prompts.json",
                "storyboard_manifest.json",
                "storyboard_precheck.json",
            ):
                artifact = load_json(project / "output/artifacts" / name)
                self.assertEqual(artifact["model_info"]["provider"], "mock")
            self.assertEqual(run(project_dir=project, config_path=config, resume=True, dry_run=True), 0)

    def test_dry_run_does_not_open_network_socket(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("socket.socket", side_effect=AssertionError("network forbidden")):
                self.assertEqual(
                    run(
                        project_dir=Path(temporary),
                        config_path=ROOT / "config/default_project_config.json",
                        dry_run=True,
                    ),
                    0,
                )


if __name__ == "__main__":
    unittest.main()

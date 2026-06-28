import tempfile
import unittest
from pathlib import Path

from _support import ROOT
from common import atomic_write_json, load_json
from estimate_cost import estimate_seedance_cost
from run_pipeline import run


class CostBudgetTests(unittest.TestCase):
    def test_sixty_seconds_cost_sixty_rmb(self):
        config = load_json(ROOT / "config/default_project_config.json")
        self.assertEqual(estimate_seedance_cost(60000, config["cost_rules"]["seedance_cost_rmb_per_second"]), 60.0)
        self.assertLess(60.0, config["cost_rules"]["max_total_cost_rmb"])

    def test_budget_blocks_before_video_generation(self):
        config = load_json(ROOT / "config/default_project_config.json")
        config["cost_rules"]["max_total_cost_rmb"] = 50
        config["cost_rules"]["warn_total_cost_rmb"] = 40
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "blocked_config.json"
            atomic_write_json(config_path, config)
            with self.assertRaisesRegex(RuntimeError, "budget"):
                run(project_dir=root / "project", config_path=config_path, dry_run=True)
            self.assertFalse(
                (root / "project/output/artifacts/video_clips_manifest.json").exists()
            )


if __name__ == "__main__":
    unittest.main()

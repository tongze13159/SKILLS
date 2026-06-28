import unittest

from _support import ROOT
from common import load_json
from dry_run_fixture import build_action_matrix, build_new_video_plan, build_raw_shots, build_strategy


class IdCompatibilityTests(unittest.TestCase):
    def test_plan_ids_exist_upstream(self):
        config = load_json(ROOT / "config/default_project_config.json")
        raw = build_raw_shots(config)
        plan = build_new_video_plan(config, raw, build_strategy(config, raw))
        refs = {x["reference_shot_id"] for x in raw["raw_shots"]}
        actions = {x["action_id"] for x in build_action_matrix(config)["product_action_matrix"]}
        for shot in plan["new_video_plan"]["shots"]:
            self.assertIn(shot["reference_shot_id"], refs)
            self.assertIn(shot["selected_action_id"], actions)


if __name__ == "__main__":
    unittest.main()

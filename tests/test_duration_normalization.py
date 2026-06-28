import unittest

from _support import ROOT
from common import load_json
from dry_run_fixture import build_new_video_plan, build_raw_shots, build_strategy
from normalize_duration import normalize_plan


class DurationTests(unittest.TestCase):
    def test_normalizes_to_60000(self):
        config = load_json(ROOT / "config/default_project_config.json")
        raw = build_raw_shots(config)
        plan = build_new_video_plan(config, raw, build_strategy(config, raw))
        plan["new_video_plan"]["shots"][0]["duration_ms"] -= 250
        normalized = normalize_plan(plan, 60000)
        self.assertEqual(sum(x["duration_ms"] for x in normalized["new_video_plan"]["shots"]), 60000)
        self.assertEqual(normalized["new_video_plan"]["shots"][-1]["end_ms"], 60000)


if __name__ == "__main__":
    unittest.main()

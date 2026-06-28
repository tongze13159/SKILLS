import tempfile
import unittest
from pathlib import Path

from _support import ROOT
from common import load_json
from compile_seedance_tasks import compile_tasks
from dry_run_fixture import build_action_matrix, build_new_video_plan, build_product_profile, build_raw_shots, build_storyboards, build_storyboard_prompts, build_strategy


class SeedanceCompilerTests(unittest.TestCase):
    def test_compiles_merged_tasks_for_short_default_shots(self):
        config = load_json(ROOT / "config/default_project_config.json")
        raw = build_raw_shots(config)
        plan = build_new_video_plan(config, raw, build_strategy(config, raw))
        profile = build_product_profile(config)
        matrix = build_action_matrix(config)
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            prompts = build_storyboard_prompts(config, plan, profile, matrix)
            storyboards = build_storyboards(config, prompts, project)
            result = compile_tasks(config=config, plan_artifact=plan, profile_artifact=profile, matrix_artifact=matrix, storyboard_artifact=storyboards, project_dir=project)
            self.assertEqual(len(result["seedance_tasks"]), 10)
            self.assertEqual(result["estimated_total_cost_rmb"], 60.0)
            self.assertEqual(result["budget_status"], "ok")
            self.assertTrue(all(task["merge_strategy"] == "adjacent_merge" for task in result["seedance_tasks"]))
            self.assertTrue(all(len(task["source_new_shot_ids"]) == 2 for task in result["seedance_tasks"]))

    def test_merges_adjacent_realistic_short_sequence_without_padding_every_shot(self):
        config = load_json(ROOT / "config/default_project_config.json")
        profile = build_product_profile(config)
        matrix = build_action_matrix(config)
        shots = [
            ("new_001", "ref_001", 0, 966, "act_001"),
            ("new_002", "ref_002", 966, 1700, "act_001"),
            ("new_003", "ref_003", 2666, 3034, "act_001"),
            ("new_004", "ref_004", 5700, 1900, "act_001"),
            ("new_005", "ref_005", 7600, 2100, "act_001"),
            ("new_006", "ref_006", 9700, 1000, "act_001"),
            ("new_007", "ref_007", 10700, 966, "act_001"),
            ("new_008", "ref_008", 11666, 2167, "act_001"),
            ("new_009", "ref_009", 13833, 3100, "act_001"),
        ]
        plan = {
            "new_video_plan": {
                "duration_ms": 16933,
                "shot_count": 9,
                "shots": [
                    {
                        "new_shot_id": new_id,
                        "reference_shot_id": ref_id,
                        "start_ms": start_ms,
                        "end_ms": start_ms + duration_ms,
                        "duration_ms": duration_ms,
                        "selected_action_id": action_id,
                        "camera": {
                            "angle": "eye-level",
                            "distance": "close-up",
                            "movement": "static",
                        },
                        "scene": {
                            "type": "indoor_pet_scene",
                            "background": "soft_home_background",
                        },
                        "must_keep_from_reference": ["single clear action", "fast pacing"],
                        "must_change_from_reference": ["exact wording", "brand elements"],
                    }
                    for new_id, ref_id, start_ms, duration_ms, action_id in shots
                ],
            }
        }
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            storyboard_root = project / "output" / "storyboards"
            storyboard_root.mkdir(parents=True, exist_ok=True)
            storyboards = {"storyboards": []}
            for index, (new_id, _, _, _, _) in enumerate(shots, start=1):
                image_path = storyboard_root / f"sb_{index:03d}.png"
                image_path.write_bytes(b"placeholder")
                storyboards["storyboards"].append(
                    {
                        "new_shot_id": new_id,
                        "image_id": f"sb_{index:03d}",
                        "image_path": f"output/storyboards/sb_{index:03d}.png",
                        "model": "flux-2-pro",
                        "source_prompt_id": new_id,
                        "selected": True,
                    }
                )
            result = compile_tasks(
                config=config,
                plan_artifact=plan,
                profile_artifact=profile,
                matrix_artifact=matrix,
                storyboard_artifact=storyboards,
                project_dir=project,
            )
            tasks = result["seedance_tasks"]
            self.assertEqual(len(tasks), 3)
            self.assertEqual([task["source_new_shot_ids"] for task in tasks], [
                ["new_001", "new_002", "new_003"],
                ["new_004", "new_005"],
                ["new_006", "new_007", "new_008", "new_009"],
            ])
            self.assertEqual([task["seedance_duration_sec"] for task in tasks], [6, 4, 7])
            self.assertEqual(result["estimated_total_cost_rmb"], 17.0)
            self.assertEqual(tasks[0]["merge_strategy"], "adjacent_merge")
            self.assertEqual(len(tasks[2]["source_segments"]), 4)


if __name__ == "__main__":
    unittest.main()

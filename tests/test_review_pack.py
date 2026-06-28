from __future__ import annotations

import re
import unittest
from pathlib import Path

from _support import ROOT


class ReviewPackTests(unittest.TestCase):
    def test_env_example_has_required_keys_without_secrets(self):
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        for key in (
            "OPENAI_API_KEY=",
            "GEMINI_API_KEY=",
            "FLUX_API_KEY=",
            "BFL_API_KEY=",
            "SEEDANCE_API_KEY=",
            "ELEVENLABS_API_KEY=",
        ):
            self.assertIn(key, env_example)
        self.assertNotRegex(env_example, r"sk-[A-Za-z0-9]{10,}")
        self.assertNotRegex(env_example, r"AIza[0-9A-Za-z_-]{10,}")

    def test_readme_mentions_install_run_and_test(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
        self.assertIn("quick start", readme)
        self.assertIn("installation", readme)
        self.assertIn("testing", readme)
        self.assertIn("run_pipeline.py", readme)

    def test_skill_description_triggers_review_use_cases(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertRegex(skill, r"viral-shot-remake-production")
        self.assertRegex(skill, r"no-face ecommerce")
        self.assertRegex(skill, r"仿拍|复刻|重构")


if __name__ == "__main__":
    unittest.main()

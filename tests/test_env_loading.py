import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import ROOT  # noqa: F401
from common import ensure_runtime_env, missing_api_keys


class EnvLoadingTests(unittest.TestCase):
    def test_env_file_is_loaded_and_flux_alias_populates_bfl(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_path = Path(temporary) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "OPENAI_API_KEY=openai-demo",
                        "GEMINI_API_KEY=gemini-demo",
                        "FLUX_API_KEY=flux-demo",
                        "SEEDANCE_API_KEY=seedance-demo",
                        "ELEVENLABS_API_KEY=eleven-demo",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            keys = [
                "OPENAI_API_KEY",
                "GEMINI_API_KEY",
                "FLUX_API_KEY",
                "BFL_API_KEY",
                "SEEDANCE_API_KEY",
                "ELEVENLABS_API_KEY",
            ]
            with patch.dict(os.environ, {}, clear=True):
                from common import load_env_file

                load_env_file(env_path)
                ensure_runtime_env()
                self.assertEqual(os.environ["FLUX_API_KEY"], "flux-demo")
                self.assertEqual(os.environ["BFL_API_KEY"], "flux-demo")
                self.assertEqual(missing_api_keys(), [])


if __name__ == "__main__":
    unittest.main()

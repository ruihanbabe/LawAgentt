from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lawagent_runtime.env import EnvFileError, load_project_env


class ProjectEnvTests(unittest.TestCase):
    def write_env(self, directory: str, content: str) -> Path:
        path = Path(directory) / ".env"
        path.write_text(content, encoding="utf-8")
        return path

    def test_loads_values_without_overriding_process_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_env(directory, "GLM_API_KEY=file-secret\nGLM_MODEL='file-model'\n")
            with patch.dict(os.environ, {"GLM_API_KEY": "process-secret"}, clear=True):
                loaded = load_project_env(path)
                self.assertEqual(os.environ["GLM_API_KEY"], "process-secret")
                self.assertEqual(os.environ["GLM_MODEL"], "file-model")
                self.assertEqual(loaded, {"GLM_MODEL"})

    def test_ignores_comments_and_empty_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_env(directory, "# comment\nOPENAI_API_KEY=\nexport GLM_MODEL=glm-test # local\n")
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_project_env(path)
                self.assertNotIn("OPENAI_API_KEY", os.environ)
                self.assertEqual(os.environ["GLM_MODEL"], "glm-test")
                self.assertEqual(loaded, {"GLM_MODEL"})

    def test_rejects_invalid_keys_and_unterminated_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid_key = self.write_env(directory, "bad-key=value\n")
            with self.assertRaises(EnvFileError):
                load_project_env(invalid_key)
            invalid_key.write_text('GLM_API_KEY="missing\n', encoding="utf-8")
            with self.assertRaises(EnvFileError):
                load_project_env(invalid_key)


if __name__ == "__main__":
    unittest.main()

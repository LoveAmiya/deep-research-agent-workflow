import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryPrivacyTests(unittest.TestCase):
    def test_git_excludes_private_runtime_data(self):
        rules = (ROOT / ".gitignore").read_text(encoding="utf-8")

        self.assertIn("data/", rules)
        self.assertIn("logs/", rules)
        self.assertIn("runs/", rules)
        self.assertIn(".env", rules)

    def test_docker_excludes_private_runtime_data(self):
        rules = (ROOT / ".dockerignore").read_text(encoding="utf-8")

        for pattern in (".env", "data/", "logs/", "runs/", ".venv/"):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, rules)


if __name__ == "__main__":
    unittest.main()

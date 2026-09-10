import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Settings


class DotenvTests(unittest.TestCase):
    def test_project_env_loads_literal_url_and_system_env_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                'WECOM_WEBHOOK_URL="https://example.com/send?key=${literal}&x=1"\n'
                'DRY_RUN=true\nPOLL_INTERVAL_SECONDS=123\n',
                encoding="utf-8-sig",
            )
            with patch("app.config.__file__", str(root / "app" / "config.py")):
                with patch.dict(os.environ, {}, clear=True):
                    settings = Settings.from_env()
                    self.assertEqual(settings.webhook_url, "https://example.com/send?key=${literal}&x=1")
                    self.assertTrue(settings.dry_run)
                    self.assertEqual(settings.poll_interval_seconds, 123)
                with patch.dict(os.environ, {"POLL_INTERVAL_SECONDS": "456"}, clear=True):
                    self.assertEqual(Settings.from_env().poll_interval_seconds, 456)

    def test_explicit_environment_does_not_load_file(self):
        with patch("app.config.dotenv_values") as read_file:
            self.assertTrue(Settings.from_env({"DRY_RUN": "true"}).dry_run)
            read_file.assert_not_called()

    def test_missing_file_uses_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("app.config.__file__", str(Path(directory) / "app" / "config.py")):
                with patch.dict(os.environ, {"DRY_RUN": "true"}, clear=True):
                    self.assertTrue(Settings.from_env().dry_run)

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import telegram_setup


class TelegramSetupTests(unittest.TestCase):
    def test_needs_setup_when_env_file_is_missing_or_placeholder(self):
        original_token = os.environ.pop("TELEGRAM_TOKEN", None)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                env_path = Path(tmp_dir) / ".env"
                self.assertTrue(telegram_setup.needs_telegram_setup(env_path))

                env_path.write_text(
                    "TELEGRAM_TOKEN=BURAYA_BOTFATHER_TOKEN_YAZ\n",
                    encoding="utf-8",
                )
                self.assertTrue(telegram_setup.needs_telegram_setup(env_path))
        finally:
            if original_token is not None:
                os.environ["TELEGRAM_TOKEN"] = original_token

    def test_needs_setup_accepts_real_file_or_process_token(self):
        original_token = os.environ.pop("TELEGRAM_TOKEN", None)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                env_path = Path(tmp_dir) / ".env"
                env_path.write_text(
                    "TELEGRAM_TOKEN=1234567890:abcdefghijklmnopqrstuvwxyz\n",
                    encoding="utf-8",
                )
                self.assertFalse(telegram_setup.needs_telegram_setup(env_path))

                env_path.write_text("", encoding="utf-8")
                os.environ["TELEGRAM_TOKEN"] = "1234567890:abcdefghijklmnopqrstuvwxyz"
                self.assertFalse(telegram_setup.needs_telegram_setup(env_path))
        finally:
            os.environ.pop("TELEGRAM_TOKEN", None)
            if original_token is not None:
                os.environ["TELEGRAM_TOKEN"] = original_token

    def test_upsert_env_values_preserves_unrelated_lines_and_removes_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_path = Path(tmp_dir) / ".env"
            env_path.write_text(
                "# comment\n"
                "TELEGRAM_TOKEN=old\n"
                "SOMETHING=else\n"
                "TELEGRAM_TOKEN=duplicate\n",
                encoding="utf-8",
            )

            telegram_setup._upsert_env_values(
                env_path,
                {
                    "TELEGRAM_TOKEN": "new-token",
                    "TELEGRAM_BOT_USERNAME": "agentcockpit_bot",
                },
            )

            self.assertEqual(
                env_path.read_text(encoding="utf-8").splitlines(),
                [
                    "# comment",
                    "TELEGRAM_TOKEN=new-token",
                    "SOMETHING=else",
                    "TELEGRAM_BOT_USERNAME=agentcockpit_bot",
                ],
            )

    def test_validate_telegram_token_reads_get_me_payload(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return (
                    b'{"ok": true, "result": {"id": 1, "username": "agentcockpit_bot"}}'
                )

        def fake_urlopen(request, timeout):
            self.assertIn("/bot1234567890:abcdefghijklmnopqrstuvwxyz/getMe", request.full_url)
            self.assertEqual(timeout, 10)
            return Response()

        ok, error, info = telegram_setup.validate_telegram_token(
            "1234567890:abcdefghijklmnopqrstuvwxyz",
            urlopen=fake_urlopen,
        )

        self.assertTrue(ok)
        self.assertEqual(error, "")
        self.assertEqual(info["username"], "agentcockpit_bot")

    def test_ensure_setup_returns_false_when_local_server_cannot_bind(self):
        original_token = os.environ.pop("TELEGRAM_TOKEN", None)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                env_path = Path(tmp_dir) / ".env"
                env_path.write_text(
                    "TELEGRAM_TOKEN=BURAYA_BOTFATHER_TOKEN_YAZ\n",
                    encoding="utf-8",
                )

                with patch.object(
                    telegram_setup,
                    "_TelegramSetupServer",
                    side_effect=PermissionError("bind denied"),
                ):
                    self.assertFalse(
                        telegram_setup.ensure_telegram_setup(tmp_dir, open_browser=False)
                    )
        finally:
            if original_token is not None:
                os.environ["TELEGRAM_TOKEN"] = original_token


if __name__ == "__main__":
    unittest.main()

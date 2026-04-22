import os
import unittest
from unittest.mock import patch

import telegram_ux
from core import bot_engine


class TelegramUxTests(unittest.TestCase):
    def test_claude_controls_accept_canonical_and_display_labels(self):
        control_labels = [
            "Session Sec",
            "Yeni Session",
            "Sekme",
            "Model",
            "Effort",
            "Izin Modu",
            "Thinking",
            "Durum",
            "Ekran Al",
            "Ana Menu",
        ]

        for label in control_labels:
            with self.subTest(label=label):
                self.assertTrue(telegram_ux._is_claude_control_message(label))
                self.assertTrue(
                    telegram_ux._is_claude_control_message(
                        bot_engine.button_label(label)
                    )
                )

    def test_codex_controls_accept_canonical_and_display_labels(self):
        control_labels = [
            "Session Sec",
            "Yeni Session",
            "Durum",
            "Ekran Al",
            "Ana Menu",
        ]

        for label in control_labels:
            with self.subTest(label=label):
                self.assertTrue(telegram_ux._is_codex_control_message(label))
                self.assertTrue(
                    telegram_ux._is_codex_control_message(
                        bot_engine.button_label(label)
                    )
                )

    def test_old_button_glyphs_still_match_controls(self):
        self.assertTrue(telegram_ux._is_claude_control_message("🆕 Yeni Session"))
        self.assertTrue(telegram_ux._is_claude_control_message("🔙 Ana Menu"))
        self.assertTrue(telegram_ux._is_codex_control_message("🆕 Yeni Session"))
        self.assertTrue(telegram_ux._is_codex_control_message("🔙 Ana Menu"))

    def test_phone_status_uses_runtime_admin_token(self):
        health = {
            "screen": "1080x1920",
            "session_unlimited": True,
            "wan_pwa_available": False,
            "public_tunnel_enabled": False,
        }
        with patch("telegram_ux.get_bridge_health", return_value=health), patch(
            "telegram_ux.get_shared_admin_token", return_value="secret-token"
        ), patch.dict(
            os.environ,
            {"PHONE_ADMIN_TOKEN": "", "PHONE_TOKEN": ""},
            clear=False,
        ):
            text = telegram_ux._phone_bridge_status_text()

        self.assertIn("Admin Token: Tanimli", text)
        self.assertNotIn("secret-token", text)


if __name__ == "__main__":
    unittest.main()

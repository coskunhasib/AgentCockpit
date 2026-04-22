import unittest
from unittest.mock import patch

from core import claude_platform_macos


class ClaudePlatformMacOSTests(unittest.TestCase):
    def test_session_text_matching_accepts_running_and_truncated_titles(self):
        self.assertTrue(
            claude_platform_macos._session_text_matches(
                "Running refactoring analizi yap", "refactoring analizi yap"
            )
        )
        self.assertTrue(
            claude_platform_macos._session_text_matches(
                "uzun baslik devam", "uzun baslik devam eden daha genis title"
            )
        )
        self.assertFalse(
            claude_platform_macos._session_text_matches(
                "baska session", "refactoring analizi yap"
            )
        )

    def test_focus_window_activates_detected_macos_app(self):
        with patch.object(
            claude_platform_macos, "_find_claude_process_name", return_value="Claude"
        ), patch.object(
            claude_platform_macos, "_run_applescript", return_value="true"
        ) as run_script, patch.object(claude_platform_macos.time, "sleep"):
            self.assertTrue(claude_platform_macos.focus_window("Claude"))

        run_script.assert_called_once()
        self.assertIn('tell application "Claude" to activate', run_script.call_args[0][0])

    def test_wait_and_read_response_collects_prompt_following_text(self):
        visible_items = [
            {"text": "onceki mesaj", "left": 500, "top": 100},
            {"text": "mac prompt", "left": 900, "top": 200},
            {"text": "· Max", "left": 500, "top": 230},
            {"text": "↓ 42 tokens", "left": 500, "top": 240},
            {"text": "Claude cevap satir 1", "left": 500, "top": 260},
            {"text": "Claude cevap satir 2", "left": 500, "top": 290},
            {"text": "Type / for commands", "left": 420, "top": 760},
        ]
        with patch.object(
            claude_platform_macos, "_collect_role_texts", return_value=["Send"]
        ), patch.object(
            claude_platform_macos, "_collect_visible_items", return_value=visible_items
        ), patch.object(claude_platform_macos.time, "sleep"):
            response = claude_platform_macos.wait_and_read_response(
                timeout=1,
                last_prompt="mac prompt",
            )

        self.assertEqual(response, "Claude cevap satir 1\nClaude cevap satir 2")

    def test_response_formatter_falls_back_to_last_non_chrome_text(self):
        response = claude_platform_macos._format_response_from_visible_items(
            [
                {"text": "Chat mode", "left": 10, "top": 10},
                {"text": "· Low", "left": 10, "top": 20},
                {"text": "Son cevap", "left": 500, "top": 30},
            ],
            last_prompt="prompt UI'da yok",
        )

        self.assertEqual(response, "Son cevap")


if __name__ == "__main__":
    unittest.main()

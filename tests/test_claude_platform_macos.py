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


if __name__ == "__main__":
    unittest.main()

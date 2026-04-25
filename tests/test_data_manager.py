import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import data_manager


class DataManagerTests(unittest.TestCase):
    def test_invalid_file_falls_back_to_normalized_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "hotkeys.json"
            data_path.write_text("{invalid", encoding="utf-8")

            with patch.object(data_manager, "DATA_FILE", str(data_path)):
                data = data_manager.DataManager.load_data()

        self.assertIn("settings", data)
        self.assertIn("claude_profiles", data)
        self.assertIn("default", data["claude_profiles"])

    def test_profile_specific_settings_are_isolated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "hotkeys.json"

            with patch.object(data_manager, "DATA_FILE", str(data_path)):
                data_manager.DataManager.update_claude_settings(
                    profile_id="u1", tab="chat", chat_model="sonnet"
                )
                data_manager.DataManager.update_claude_settings(
                    profile_id="u2", tab="code", code_model="opus_1m"
                )
                u1 = data_manager.DataManager.get_claude_settings("u1")
                u2 = data_manager.DataManager.get_claude_settings("u2")

        self.assertEqual(u1["tab"], "chat")
        self.assertEqual(u1["chat_model"], "sonnet")
        self.assertEqual(u2["tab"], "code")
        self.assertEqual(u2["code_model"], "opus_1m")

    def test_windows_defaults_include_escape_hotkeys(self):
        with patch.object(data_manager.sys, "platform", "win32"):
            hotkeys = data_manager._platform_hotkeys()

        self.assertEqual(hotkeys["Gorev Yon."], ["ctrl", "shift", "esc"])
        self.assertEqual(hotkeys["Gorev Yon. Kapat"], ["taskmgr-close"])
        self.assertEqual(hotkeys["Pencere Kapat"], ["alt", "f4"])
        self.assertEqual(hotkeys["Gorev Degistir"], ["alt", "tab"])


if __name__ == "__main__":
    unittest.main()

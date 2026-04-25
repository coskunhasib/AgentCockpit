import unittest
from unittest.mock import patch

from core import system_tools
from core.system_tools import SystemOps


class SystemToolsHotkeyTests(unittest.TestCase):
    def test_mac_maps_windows_style_shortcuts_to_macos_intent(self):
        with patch.object(system_tools.sys, "platform", "darwin"):
            self.assertEqual(SystemOps.normalize_hotkey(["ctrl", "c"]), ["command", "c"])
            self.assertEqual(SystemOps.normalize_hotkey(["alt", "tab"]), ["command", "tab"])
            self.assertEqual(SystemOps.normalize_hotkey(["alt", "shift", "tab"]), ["command", "shift", "tab"])
            self.assertEqual(SystemOps.normalize_hotkey(["winleft", "d"]), ["command", "f3"])
            self.assertEqual(
                SystemOps.normalize_hotkey(["ctrl", "shift", "esc"]),
                ["command", "option", "esc"],
            )

    def test_desktop_keeps_windows_style_shortcuts_usable(self):
        with patch.object(system_tools.sys, "platform", "win32"):
            self.assertEqual(SystemOps.normalize_hotkey(["win", "d"]), ["winleft", "d"])
            self.assertEqual(SystemOps.normalize_hotkey(["command", "v"]), ["ctrl", "v"])
            self.assertEqual(SystemOps.normalize_hotkey(["option", "tab"]), ["alt", "tab"])

    def test_task_manager_close_command_uses_windows_taskkill(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        with patch.object(system_tools.sys, "platform", "win32"), patch(
            "core.system_tools.subprocess.run", return_value=completed
        ) as run_mock:
            self.assertTrue(SystemOps.close_task_manager())
            self.assertTrue(SystemOps.press_key("taskmgr-close"))
            self.assertTrue(SystemOps.execute_hotkey(["taskmgr-close"]))

        run_mock.assert_called_with(
            ["taskkill", "/IM", "Taskmgr.exe", "/F"],
            capture_output=True,
            text=True,
            timeout=5,
        )


if __name__ == "__main__":
    unittest.main()

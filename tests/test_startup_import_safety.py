import builtins
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from core.system_tools import SystemOps
import core.system_tools as system_tools
import phone_bridge_server
import phone_wan_transport


ROOT = Path(__file__).resolve().parents[1]


def _load_module_with_blocked_imports(relative_path, temp_name, blocked_roots):
    source_path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(temp_name, source_path)
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules so dataclass annotation resolution works
    sys.modules[temp_name] = module
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".", 1)[0]
        if root in blocked_roots:
            raise ImportError(f"blocked import: {name}")
        return real_import(name, globals, locals, fromlist, level)

    try:
        with patch("builtins.__import__", side_effect=guarded_import):
            spec.loader.exec_module(module)
    finally:
        sys.modules.pop(temp_name, None)
    return module


class StartupImportSafetyTests(unittest.TestCase):
    def test_system_tools_import_does_not_require_pyautogui(self):
        module = _load_module_with_blocked_imports(
            Path("core") / "system_tools.py",
            "temp_system_tools_no_gui",
            {"pyautogui", "pyperclip"},
        )
        self.assertTrue(hasattr(module, "SystemOps"))

    def test_phone_wan_transport_import_does_not_require_pyautogui(self):
        module = _load_module_with_blocked_imports(
            "phone_wan_transport.py",
            "temp_phone_wan_transport_no_gui",
            {"pyautogui"},
        )
        self.assertTrue(hasattr(module, "_capture_frame"))

    def test_phone_bridge_server_import_does_not_require_pyautogui(self):
        module = _load_module_with_blocked_imports(
            "phone_bridge_server.py",
            "temp_phone_bridge_server_no_gui",
            {"pyautogui"},
        )
        self.assertTrue(hasattr(module, "TrustedDeviceStore"))

    def test_system_tools_fail_closed_when_desktop_control_is_unavailable(self):
        with patch("core.system_tools._get_pyautogui", return_value=None):
            self.assertFalse(SystemOps.mouse_click())
            self.assertFalse(SystemOps.execute_hotkey(["ctrl", "c"]))
            self.assertFalse(SystemOps.type_text("merhaba"))
            self.assertIsNone(SystemOps.take_screenshot())

    def test_phone_bridge_health_metrics_degrade_gracefully_without_pyautogui(self):
        with patch("phone_bridge_server._get_pyautogui", return_value=None):
            metrics = phone_bridge_server._get_screen_metrics()

        self.assertEqual(metrics["width"], 0)
        self.assertEqual(metrics["height"], 0)
        self.assertFalse(metrics["available"])

    def test_phone_wan_capture_reports_clear_runtime_error_without_pyautogui(self):
        with patch("phone_wan_transport._get_pyautogui", return_value=None):
            with self.assertRaises(RuntimeError):
                phone_wan_transport._capture_frame()


if __name__ == "__main__":
    unittest.main()

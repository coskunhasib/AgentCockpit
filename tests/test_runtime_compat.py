import unittest

from core.runtime_compat import (
    apply_runtime_defaults,
    desktop_automation_help_text,
    detect_runtime_compatibility,
    format_runtime_compatibility,
)


class RuntimeCompatTests(unittest.TestCase):
    def test_linux_headless_runtime_degrades_gracefully(self):
        report = detect_runtime_compatibility(
            platform_name="linux",
            machine_name="x86_64",
            env={},
            browser_tools=set(),
            import_module=lambda name: object(),
        )

        self.assertFalse(report["gui_session"])
        self.assertFalse(report["browser_available"])
        self.assertFalse(report["desktop_automation_available"])
        self.assertTrue(report["public_tunnel_supported"])

    def test_import_failure_marks_desktop_automation_unavailable(self):
        def broken_import(name):
            raise RuntimeError("boom")

        report = detect_runtime_compatibility(
            platform_name="darwin",
            machine_name="arm64",
            env={},
            browser_tools={"open"},
            import_module=broken_import,
        )

        self.assertTrue(report["browser_available"])
        self.assertFalse(report["desktop_automation_available"])
        self.assertIn("pyautogui", report["desktop_automation_reason"])

    def test_unsupported_tunnel_platform_applies_off_default(self):
        report = detect_runtime_compatibility(
            platform_name="linux",
            machine_name="mips64",
            env={"DISPLAY": ":1"},
            browser_tools={"xdg-open"},
            import_module=lambda name: object(),
        )
        env = {}

        apply_runtime_defaults(report, env=env)

        self.assertFalse(report["public_tunnel_supported"])
        self.assertEqual(env["PHONE_PUBLIC_TUNNEL"], "off")
        self.assertIn("PHONE_PUBLIC_TUNNEL=off", report["applied_defaults"])

    def test_help_text_and_formatting_are_platform_specific(self):
        self.assertIn("Screen Recording", desktop_automation_help_text("darwin"))
        self.assertIn("DISPLAY", desktop_automation_help_text("linux"))

        report = detect_runtime_compatibility(
            platform_name="win32",
            machine_name="AMD64",
            env={},
            browser_tools=set(),
            import_module=lambda name: object(),
        )
        lines = format_runtime_compatibility(report)

        self.assertTrue(any(line.startswith("[COMPAT] Platform: win32") for line in lines))


if __name__ == "__main__":
    unittest.main()

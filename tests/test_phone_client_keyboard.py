import unittest
from pathlib import Path


class PhoneClientKeyboardTests(unittest.TestCase):
    def test_keyboard_panel_exposes_recovery_shortcuts(self):
        html = Path("phone_client/index.html").read_text(encoding="utf-8")

        self.assertIn('data-key="ctrl+shift+esc"', html)
        self.assertIn('data-key="taskmgr-close"', html)
        self.assertIn('data-key="alt+f4"', html)
        self.assertIn('data-key="winleft+d"', html)


if __name__ == "__main__":
    unittest.main()

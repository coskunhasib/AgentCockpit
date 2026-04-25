import unittest
from pathlib import Path


class PhoneClientLayoutTests(unittest.TestCase):
    def test_viewer_uses_dynamic_offsets_and_status_dropdown(self):
        html = Path("phone_client/index.html").read_text(encoding="utf-8")

        self.assertIn("--viewer-top-offset", html)
        self.assertIn("--viewer-bottom-offset", html)
        self.assertIn('id="status-card"', html)
        self.assertIn('id="btn-status-toggle"', html)
        self.assertIn('id="toolbar"', html)
        self.assertIn("function updateViewerInsets()", html)
        self.assertIn("setStatusExpanded(", html)
        self.assertIn("if (element === topbar && !statusExpanded)", html)
        self.assertIn("setStatusExpanded(false);", html)
        self.assertIn("document.documentElement.style.setProperty('--viewer-top-offset'", html)
        self.assertIn("document.documentElement.style.setProperty('--viewer-bottom-offset'", html)


if __name__ == "__main__":
    unittest.main()

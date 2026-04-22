import inspect
import unittest
from pathlib import Path

from phone_bridge_server import PhoneBridgeHandler


class PhoneBridgeSecurityTests(unittest.TestCase):
    def test_public_root_route_does_not_render_startup_tokens(self):
        source = inspect.getsource(PhoneBridgeHandler.do_GET)
        root_block = source.split('if route == "/":', 1)[1].split(
            'if route == "/pair":',
            1,
        )[0]

        self.assertNotIn("startup_link", root_block)
        self.assertNotIn("startup_session", root_block)
        self.assertNotIn("_build_app_url_from_base", root_block)

    def test_phone_client_clears_stale_wan_links_and_keeps_rotate_dismissal(self):
        client_html = Path("phone_client/index.html").read_text(encoding="utf-8")

        self.assertIn("Object.prototype.hasOwnProperty.call(payload, 'public_url')", client_html)
        self.assertIn("Object.prototype.hasOwnProperty.call(payload, 'wan_url')", client_html)

        orientation_block = client_html.split("window.addEventListener('orientationchange'", 1)[1].split(
            "});",
            1,
        )[0]
        self.assertNotIn("rotateHintDismissed", orientation_block)


if __name__ == "__main__":
    unittest.main()

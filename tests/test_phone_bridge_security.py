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

    def test_link_payload_uses_validated_public_url_for_qr(self):
        source = inspect.getsource(PhoneBridgeHandler._build_link_payload)
        self.assertIn("get_public_url(validate=True)", source)

    def test_qr_alias_redirects_to_pair(self):
        source = inspect.getsource(PhoneBridgeHandler.do_GET)
        self.assertIn('if route == "/qr":', source)
        self.assertIn('self.send_header("Location", "/pair")', source)

    def test_app_shell_can_recover_with_persisted_device_token(self):
        source = inspect.getsource(PhoneBridgeHandler)
        get_source = inspect.getsource(PhoneBridgeHandler.do_GET)
        viewer_source = inspect.getsource(PhoneBridgeHandler._get_viewer_session)
        app_block = get_source.split('if route == "/app":', 1)[1].split(
            'if route == "/manifest.webmanifest":',
            1,
        )[0]

        # Device tokens are read from cookie, query, or header, and the viewer
        # session check falls back to the persisted trusted-device token, so a
        # reinstalled PWA recovers without a fresh pairing link.
        self.assertIn('or query.get("device", [""])[0]', source)
        self.assertIn("session, auth_kind = self._require_viewer_session(html=True)", app_block)
        self.assertIn("trusted_device = self.server.trusted_devices.consume(self._extract_device_token())", viewer_source)
        self.assertIn('"{{DEVICE_TOKEN}}"', app_block)
        self.assertIn('handoff_token = ""', app_block)
        self.assertIn('if session:', app_block)
        self.assertIn('wan_url = _build_app_url_from_base(public_url, handoff_token) if handoff_token else ""', app_block)


if __name__ == "__main__":
    unittest.main()

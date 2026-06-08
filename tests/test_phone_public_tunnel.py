import unittest
import time
from unittest.mock import patch

import phone_public_tunnel


class PhonePublicTunnelTests(unittest.TestCase):
    def test_extract_tunnel_url_from_cloudflared_output(self):
        line = "INF +--------------------------------------------------------------------------------------------+ https://quiet-river-123.trycloudflare.com"
        self.assertEqual(
            phone_public_tunnel.extract_tunnel_url(line),
            "https://quiet-river-123.trycloudflare.com",
        )

    def test_tunnel_enabled_accepts_product_defaults_and_off_switches(self):
        self.assertTrue(phone_public_tunnel.tunnel_enabled("auto"))
        self.assertTrue(phone_public_tunnel.tunnel_enabled("on"))
        self.assertFalse(phone_public_tunnel.tunnel_enabled("off"))
        self.assertFalse(phone_public_tunnel.tunnel_enabled("0"))

    def test_download_url_matches_supported_platforms(self):
        self.assertTrue(
            phone_public_tunnel.cloudflared_download_url("Windows", "AMD64").endswith(
                "cloudflared-windows-amd64.exe"
            )
        )
        self.assertTrue(
            phone_public_tunnel.cloudflared_download_url("Linux", "x86_64").endswith(
                "cloudflared-linux-amd64"
            )
        )
        self.assertTrue(
            phone_public_tunnel.cloudflared_download_url("Darwin", "arm64").endswith(
                "cloudflared-darwin-arm64.tgz"
            )
        )

    def test_tunnel_restart_limit_defaults_to_finite_value(self):
        with patch.dict("os.environ", {}, clear=True):
            tunnel = phone_public_tunnel.QuickTunnel("http://127.0.0.1:8765")

        self.assertEqual(tunnel.max_restarts, 3)

    def test_get_public_url_returns_empty_when_health_validation_fails(self):
        tunnel = phone_public_tunnel.QuickTunnel("http://127.0.0.1:8765")
        tunnel.public_url = "https://dead.trycloudflare.com"

        with patch("phone_public_tunnel.urllib.request.urlopen", side_effect=OSError("boom")):
            self.assertEqual(tunnel.get_public_url(validate=True), "")

    def test_get_public_url_returns_url_when_health_validation_succeeds(self):
        tunnel = phone_public_tunnel.QuickTunnel("http://127.0.0.1:8765")
        tunnel.public_url = "https://live.trycloudflare.com"

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("phone_public_tunnel.urllib.request.urlopen", return_value=Response()):
            self.assertEqual(
                tunnel.get_public_url(validate=True),
                "https://live.trycloudflare.com",
            )

    def test_snapshot_can_skip_validation(self):
        tunnel = phone_public_tunnel.QuickTunnel("http://127.0.0.1:8765")
        tunnel.public_url = "https://live.trycloudflare.com"

        with patch(
            "phone_public_tunnel.urllib.request.urlopen",
            side_effect=AssertionError("validation should be skipped"),
        ):
            snapshot = tunnel.snapshot(validate=False)

        self.assertEqual(snapshot["public_url"], "https://live.trycloudflare.com")

    def test_unreachable_tunnel_restarts_after_grace_and_failures(self):
        class Process:
            def poll(self):
                return None

        tunnel = phone_public_tunnel.QuickTunnel("http://127.0.0.1:8765")
        tunnel.public_url = "https://dead.trycloudflare.com"
        tunnel.process = Process()
        tunnel._url_seen_at = time.monotonic() - 180
        tunnel._validation_failures = 2

        with patch("phone_public_tunnel.urllib.request.urlopen", side_effect=OSError("boom")), patch.object(
            tunnel,
            "_terminate_unreachable_process",
        ) as restart:
            self.assertEqual(tunnel.get_public_url(validate=True), "")

        restart.assert_called_once_with(tunnel.process)
        self.assertEqual(tunnel.public_url, "")
        self.assertEqual(tunnel.status, "yeniden_baslatiliyor")

    def test_unreachable_tunnel_does_not_restart_during_grace_period(self):
        class Process:
            def poll(self):
                return None

        tunnel = phone_public_tunnel.QuickTunnel("http://127.0.0.1:8765")
        tunnel.public_url = "https://propagating.trycloudflare.com"
        tunnel.process = Process()
        tunnel._url_seen_at = time.monotonic() - 30

        with patch("phone_public_tunnel.urllib.request.urlopen", side_effect=OSError("boom")), patch.object(
            tunnel,
            "_terminate_unreachable_process",
        ) as restart:
            self.assertEqual(tunnel.get_public_url(validate=True), "")

        restart.assert_not_called()
        self.assertEqual(tunnel.public_url, "https://propagating.trycloudflare.com")
        self.assertEqual(tunnel.status, "kapali")


if __name__ == "__main__":
    unittest.main()

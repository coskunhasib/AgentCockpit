import unittest

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


if __name__ == "__main__":
    unittest.main()

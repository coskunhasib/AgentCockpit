import unittest
from unittest.mock import patch

import phone_bridge_server
import phone_bridge_client


class _FakePyAutoGui:
    def __init__(self):
        self.writes = []

    def write(self, text, interval=0.0):
        self.writes.append((text, interval))


class PhoneBridgeClientTests(unittest.TestCase):
    def test_create_phone_link_reads_admin_token_at_call_time(self):
        with patch.object(
            phone_bridge_client, "get_shared_admin_token", return_value="fresh-token"
        ), patch.object(
            phone_bridge_client,
            "_request_json",
            return_value={"status": "ok", "session": {"token": "phone-link"}},
        ) as request_json:
            session = phone_bridge_client.create_phone_link(minutes=0)

        self.assertEqual(session, {"token": "phone-link"})
        self.assertEqual(
            request_json.call_args.kwargs["headers"],
            {"X-AgentCockpit-Admin": "fresh-token"},
        )

    def test_request_json_wraps_timeout_error(self):
        with patch.object(
            phone_bridge_client.urllib.request,
            "urlopen",
            side_effect=TimeoutError("timed out"),
        ):
            with self.assertRaises(phone_bridge_client.PhoneBridgeClientError) as context:
                phone_bridge_client._request_json("/health")

        self.assertIn("zaman asimina", str(context.exception))

    def test_local_ipv4_candidates_does_not_use_blocking_fqdn_lookup(self):
        with patch.object(phone_bridge_server, "_get_local_ip", return_value="192.168.1.8"), patch.object(
            phone_bridge_server.socket, "gethostname", return_value="macbook"
        ), patch.object(
            phone_bridge_server.socket,
            "getfqdn",
            side_effect=AssertionError("getfqdn should not be called"),
        ), patch.object(
            phone_bridge_server.socket,
            "getaddrinfo",
            return_value=[
                (
                    phone_bridge_server.socket.AF_INET,
                    phone_bridge_server.socket.SOCK_DGRAM,
                    0,
                    "",
                    ("192.168.1.9", 0),
                )
            ],
        ):
            ips = phone_bridge_server._get_local_ipv4_candidates()

        self.assertEqual(ips, ["192.168.1.8", "192.168.1.9"])

    def test_phone_bridge_server_bind_does_not_use_blocking_fqdn_lookup(self):
        def fake_server_bind(server):
            server.server_address = ("127.0.0.1", 54321)

        with patch.object(phone_bridge_server.TCPServer, "server_bind", fake_server_bind), patch.object(
            phone_bridge_server.TCPServer, "server_activate", lambda server: None
        ), patch.object(
            phone_bridge_server, "_get_local_ipv4_candidates", return_value=[]
        ), patch.object(
            phone_bridge_server, "_get_local_ip", return_value="127.0.0.1"
        ), patch.object(
            phone_bridge_server.socket,
            "getfqdn",
            side_effect=AssertionError("getfqdn should not be called"),
        ):
            server = phone_bridge_server.PhoneBridgeServer(
                ("127.0.0.1", 0),
                phone_bridge_server.PhoneBridgeHandler,
                admin_token="admin",
                screenshot_quality=60,
                max_width=1280,
                poll_ms=1000,
                default_session_minutes=0,
            )

        try:
            self.assertEqual(server.server_name, "127.0.0.1")
            self.assertEqual(server.server_port, 54321)
        finally:
            server.server_close()

    def test_sensitive_phone_typing_uses_direct_keystrokes_without_clipboard(self):
        fake = _FakePyAutoGui()

        with patch.object(phone_bridge_server, "_require_pyautogui", return_value=fake), patch.object(
            phone_bridge_server.SystemOps,
            "type_text",
            side_effect=AssertionError("clipboard fallback should not be used"),
        ):
            self.assertTrue(phone_bridge_server._perform_type("Password123!", sensitive=True))

        self.assertEqual(fake.writes, [("Password123!", 0.02)])

    def test_sensitive_phone_typing_rejects_non_direct_characters(self):
        fake = _FakePyAutoGui()

        with patch.object(phone_bridge_server, "_require_pyautogui", return_value=fake):
            with self.assertRaises(RuntimeError):
                phone_bridge_server._perform_type("şifre", sensitive=True)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

import phone_bridge_client
import phone_bridge_server


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

    def test_phone_bridge_server_limits_active_stream_slots(self):
        def fake_server_bind(server):
            server.server_address = ("127.0.0.1", 54322)

        with patch.object(phone_bridge_server.TCPServer, "server_bind", fake_server_bind), patch.object(
            phone_bridge_server.TCPServer, "server_activate", lambda server: None
        ), patch.object(
            phone_bridge_server, "_get_local_ipv4_candidates", return_value=[]
        ), patch.object(
            phone_bridge_server, "_get_local_ip", return_value="127.0.0.1"
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
            for _ in range(server.max_stream_connections):
                self.assertTrue(server.acquire_stream_slot())
            self.assertFalse(server.acquire_stream_slot())
            self.assertEqual(server.active_stream_count(), server.max_stream_connections)
            for _ in range(server.max_stream_connections):
                server.release_stream_slot()
            self.assertEqual(server.active_stream_count(), 0)
        finally:
            server.server_close()

    def test_sensitive_phone_typing_uses_clipboard_paste_and_restores_clipboard(self):
        with patch.object(
            phone_bridge_server.SystemOps,
            "paste_text",
            return_value=True,
        ) as paste_text:
            self.assertTrue(phone_bridge_server._perform_type("Password123!", sensitive=True))

        paste_text.assert_called_once_with("Password123!", restore_clipboard=True)

    def test_phone_typing_refocuses_last_screen_target_before_writing(self):
        with patch.object(phone_bridge_server, "_perform_click") as click, patch.object(
            phone_bridge_server.SystemOps,
            "paste_text",
            return_value=True,
        ) as paste_text:
            self.assertTrue(
                phone_bridge_server._perform_type(
                    "normal text",
                    sensitive=False,
                    focus={"x": 0.25, "y": 0.75},
                )
            )

        click.assert_called_once_with(0.25, 0.75, "left")
        paste_text.assert_called_once_with("normal text", restore_clipboard=False)

    def test_normal_phone_typing_uses_clipboard_paste_for_ascii(self):
        with patch.object(
            phone_bridge_server.SystemOps,
            "paste_text",
            return_value=True,
        ) as paste_text:
            self.assertTrue(phone_bridge_server._perform_type("normal text", sensitive=False))

        paste_text.assert_called_once_with("normal text", restore_clipboard=False)

    def test_normal_phone_typing_uses_clipboard_paste_for_unicode(self):
        with patch.object(
            phone_bridge_server.SystemOps,
            "type_text_unicode",
            side_effect=AssertionError("Quartz typing should not be used"),
        ) as unicode_type, patch.object(
            phone_bridge_server.SystemOps,
            "paste_text",
            return_value=True,
        ) as paste_text:
            self.assertTrue(phone_bridge_server._perform_type("Turkce şifre", sensitive=False))

        unicode_type.assert_not_called()
        paste_text.assert_called_once_with("Turkce şifre", restore_clipboard=False)

    def test_phone_typing_returns_false_when_clipboard_paste_fails(self):
        with patch.object(
            phone_bridge_server.SystemOps,
            "paste_text",
            return_value=False,
        ) as paste_text:
            self.assertFalse(phone_bridge_server._perform_type("şifre", sensitive=True))

        paste_text.assert_called_once_with("şifre", restore_clipboard=True)


if __name__ == "__main__":
    unittest.main()

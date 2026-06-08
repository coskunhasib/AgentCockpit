import asyncio
import socket
import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch

from core import dns_fallback


class DnsFallbackTests(unittest.TestCase):
    def test_resolve_host_uses_udp_fallback_servers(self):
        with patch.object(dns_fallback, "_CACHE", {}), patch.object(
            dns_fallback, "_dns_servers", return_value=["192.168.1.1"]
        ), patch.object(
            dns_fallback, "_query_a", return_value=["203.0.113.10"]
        ) as query:
            self.assertEqual(dns_fallback.resolve_host("example.test"), ["203.0.113.10"])

        query.assert_called_once_with("example.test", "192.168.1.1")

    def test_fallback_getaddrinfo_synthesizes_ipv4_result(self):
        with patch.object(
            dns_fallback,
            "_ORIGINAL_GETADDRINFO",
            side_effect=socket.gaierror("missing"),
        ), patch.object(
            dns_fallback,
            "resolve_host",
            return_value=["203.0.113.20"],
        ):
            result = dns_fallback._fallback_getaddrinfo(
                "example.test",
                443,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
                0,
                0,
            )

        self.assertEqual(
            result,
            [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("203.0.113.20", 443))],
        )

    def test_fallback_getaddrinfo_handles_encoded_host(self):
        with patch.object(
            dns_fallback,
            "_ORIGINAL_GETADDRINFO",
            side_effect=socket.gaierror("missing"),
        ), patch.object(
            dns_fallback,
            "resolve_host",
            return_value=["203.0.113.30"],
        ) as resolve:
            dns_fallback._fallback_getaddrinfo(
                b"example.test",
                443,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
                0,
                0,
            )

        resolve.assert_called_once_with("example.test")

    def test_anyio_getaddrinfo_uses_dns_fallback(self):
        import anyio._core._sockets as anyio_sockets

        original_anyio_getaddrinfo = anyio_sockets.getaddrinfo
        failing_getaddrinfo = AsyncMock(side_effect=socket.gaierror("missing"))
        anyio_sockets.getaddrinfo = failing_getaddrinfo
        dns_fallback._ANYIO_INSTALLED = False
        dns_fallback._ORIGINAL_ANYIO_GETADDRINFO = None

        try:
            with patch.object(
                dns_fallback,
                "_ORIGINAL_GETADDRINFO",
                side_effect=socket.gaierror("missing"),
            ), patch.object(
                dns_fallback,
                "resolve_host",
                return_value=["203.0.113.40"],
            ):
                self.assertTrue(dns_fallback._install_anyio_getaddrinfo())
                result = asyncio.run(
                    anyio_sockets.getaddrinfo(
                        "example.test",
                        443,
                        family=socket.AF_UNSPEC,
                        type=socket.SOCK_STREAM,
                    )
                )

            self.assertEqual(
                result,
                [
                    (
                        socket.AF_INET,
                        socket.SOCK_STREAM,
                        socket.IPPROTO_TCP,
                        "",
                        ("203.0.113.40", 443),
                    )
                ],
            )
        finally:
            anyio_sockets.getaddrinfo = original_anyio_getaddrinfo
            dns_fallback._ANYIO_INSTALLED = False
            dns_fallback._ORIGINAL_ANYIO_GETADDRINFO = None


if __name__ == "__main__":
    unittest.main()

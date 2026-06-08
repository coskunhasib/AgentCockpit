"""Small DNS fallback for environments where macOS getaddrinfo is unavailable."""

from __future__ import annotations

import os
import random
import socket
import struct
import threading
import time
from pathlib import Path


_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_ORIGINAL_ANYIO_GETADDRINFO = None
_INSTALLED = False
_ANYIO_INSTALLED = False
_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, list[str]]] = {}
_CACHE_TTL = 60.0


def _dns_servers():
    servers = []
    try:
        for line in Path("/etc/resolv.conf").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "nameserver":
                server = parts[1]
                if ":" not in server:
                    servers.append(server)
    except Exception:
        pass

    for server in ("192.168.1.1", "1.1.1.1", "8.8.8.8"):
        if server not in servers:
            servers.append(server)
    return servers


def _encode_name(hostname: str) -> bytes:
    return b"".join(
        bytes([len(label)]) + label.encode("ascii")
        for label in hostname.rstrip(".").split(".")
    ) + b"\x00"


def _skip_name(packet: bytes, offset: int) -> int:
    while True:
        length = packet[offset]
        offset += 1
        if length == 0:
            return offset
        if length & 0xC0 == 0xC0:
            return offset + 1
        offset += length


def _query_a(hostname: str, server: str, timeout: float = 1.2) -> list[str]:
    query_id = random.randint(0, 0xFFFF)
    question = _encode_name(hostname) + struct.pack("!HH", 1, 1)
    packet = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0) + question

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, (server, 53))
        response, _ = sock.recvfrom(4096)
    finally:
        sock.close()

    if len(response) < 12:
        return []

    rid, _flags, qdcount, ancount, _nscount, _arcount = struct.unpack(
        "!HHHHHH", response[:12]
    )
    if rid != query_id:
        return []

    offset = 12
    for _ in range(qdcount):
        offset = _skip_name(response, offset) + 4

    addresses = []
    for _ in range(ancount):
        offset = _skip_name(response, offset)
        if offset + 10 > len(response):
            break
        rtype, rclass, _ttl, rdlength = struct.unpack("!HHIH", response[offset : offset + 10])
        offset += 10
        rdata = response[offset : offset + rdlength]
        offset += rdlength
        if rtype == 1 and rclass == 1 and rdlength == 4:
            addresses.append(socket.inet_ntoa(rdata))
    return addresses


def resolve_host(hostname: str) -> list[str]:
    host = (hostname or "").strip().rstrip(".")
    if not host:
        return []

    try:
        socket.inet_aton(host)
        return [host]
    except OSError:
        pass

    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(host)
        if cached and now - cached[0] < _CACHE_TTL:
            return list(cached[1])

    addresses: list[str] = []
    for server in _dns_servers():
        try:
            addresses = _query_a(host, server)
        except Exception:
            addresses = []
        if addresses:
            break

    with _LOCK:
        _CACHE[host] = (now, addresses)
    return list(addresses)


def _service_to_port(service):
    if isinstance(service, int):
        return service
    if service is None:
        return 0
    try:
        return int(service)
    except (TypeError, ValueError):
        return socket.getservbyname(str(service))


def _host_to_text(host) -> str:
    if host is None:
        return ""
    if isinstance(host, bytes):
        return host.decode("ascii")
    return str(host)


def _fallback_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)
    except socket.gaierror:
        addresses = resolve_host(_host_to_text(host))
        if not addresses:
            raise

    resolved_port = _service_to_port(port)
    socktype = type or socket.SOCK_STREAM
    protocol = proto or (socket.IPPROTO_TCP if socktype == socket.SOCK_STREAM else 0)
    return [
        (socket.AF_INET, socktype, protocol, "", (address, resolved_port))
        for address in addresses
        if family in (0, socket.AF_UNSPEC, socket.AF_INET)
    ]


def _install_anyio_getaddrinfo():
    global _ORIGINAL_ANYIO_GETADDRINFO, _ANYIO_INSTALLED
    if _ANYIO_INSTALLED:
        return True

    try:
        import anyio._core._sockets as anyio_sockets
    except Exception:
        return False

    original = anyio_sockets.getaddrinfo
    if getattr(original, "_agentcockpit_dns_fallback", False) is True:
        _ORIGINAL_ANYIO_GETADDRINFO = getattr(original, "_agentcockpit_original", original)
        _ANYIO_INSTALLED = True
        return True

    _ORIGINAL_ANYIO_GETADDRINFO = original

    async def _fallback_anyio_getaddrinfo(
        host,
        port,
        *,
        family=0,
        type=0,
        proto=0,
        flags=0,
    ):
        try:
            return await original(
                host, port, family=family, type=type, proto=proto, flags=flags
            )
        except OSError as exc:
            try:
                result = _fallback_getaddrinfo(host, port, family, type, proto, flags)
            except OSError:
                raise exc
            if result:
                return result
            raise exc

    _fallback_anyio_getaddrinfo._agentcockpit_dns_fallback = True
    _fallback_anyio_getaddrinfo._agentcockpit_original = original
    anyio_sockets.getaddrinfo = _fallback_anyio_getaddrinfo
    _ANYIO_INSTALLED = True
    return True


def install():
    global _INSTALLED
    if os.getenv("AGENTCOCKPIT_DNS_FALLBACK", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False
    with _LOCK:
        if not _INSTALLED:
            socket.getaddrinfo = _fallback_getaddrinfo
            _INSTALLED = True
        _install_anyio_getaddrinfo()
    return True


def install_tls_fallback():
    if os.getenv("AGENTCOCKPIT_TLS_FALLBACK", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False

    try:
        from pip._vendor import truststore

        truststore.extract_from_ssl()
    except Exception:
        pass

    try:
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except Exception:
        pass
    return True

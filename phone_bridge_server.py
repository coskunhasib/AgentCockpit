import argparse
import base64
import ipaddress
import io
import json
import os
import secrets
import socket
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT_DIR

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pyautogui
from PIL import Image, ImageDraw
from dotenv import load_dotenv
try:
    import qrcode
except ImportError:
    qrcode = None

from core.logger import get_logger
from core.system_tools import SystemOps
from phone_runtime_config import (
    TRUSTED_DEVICES_FILE,
    get_installation_id,
    get_runtime_paths,
    get_shared_admin_token,
)
from phone_public_tunnel import start_public_tunnel


load_dotenv(PROJECT_ROOT / ".env")
logger = get_logger("phone_bridge")

PHONE_CLIENT_DIR = ROOT_DIR / "phone_client"

DEFAULT_BIND = os.getenv("PHONE_BIND", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("PHONE_PORT", "8765"))
DEFAULT_ADMIN_TOKEN = get_shared_admin_token()
DEFAULT_QUALITY = max(20, min(95, int(os.getenv("PHONE_SCREENSHOT_QUALITY", "55"))))
DEFAULT_MAX_WIDTH = max(640, int(os.getenv("PHONE_SCREENSHOT_MAX_WIDTH", "1600")))
DEFAULT_POLL_MS = max(500, int(os.getenv("PHONE_POLL_MS", "1400")))
DEFAULT_SESSION_MINUTES = int(os.getenv("PHONE_SESSION_MINUTES", "0"))
DEFAULT_TELEGRAM_URL = os.getenv("PHONE_TELEGRAM_URL", "").strip()
DEFAULT_TELEGRAM_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
DEFAULT_PUBLIC_TUNNEL = os.getenv("PHONE_PUBLIC_TUNNEL", "auto")


def _telegram_bot_url():
    if DEFAULT_TELEGRAM_URL:
        return DEFAULT_TELEGRAM_URL
    if DEFAULT_TELEGRAM_USERNAME:
        return f"https://t.me/{DEFAULT_TELEGRAM_USERNAME}"
    return ""


def _get_local_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _get_local_ipv4_candidates():
    candidates = []

    def add(ip):
        try:
            parsed = ipaddress.ip_address(ip)
        except ValueError:
            return
        if parsed.version != 4 or parsed.is_loopback or parsed.is_link_local:
            return
        value = str(parsed)
        if value not in candidates:
            candidates.append(value)

    preferred = _get_local_ip()
    add(preferred)

    host_names = [socket.gethostname()]
    try:
        fqdn = socket.getfqdn()
        if fqdn and fqdn not in host_names:
            host_names.append(fqdn)
    except Exception:
        pass

    for host in host_names:
        try:
            infos = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)
        except OSError:
            continue
        for info in infos:
            add(info[4][0])

    private = [ip for ip in candidates if ipaddress.ip_address(ip).is_private]
    public = [ip for ip in candidates if not ipaddress.ip_address(ip).is_private]
    return private + public


def _clamp_ratio(value):
    return max(0.0, min(1.0, float(value)))


def _format_ttl(seconds):
    if seconds is None:
        return "Sinirsiz"
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} sn"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} dk" if rem == 0 else f"{minutes} dk {rem} sn"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} sa {minutes} dk" if minutes else f"{hours} sa"


def _build_app_url(host, port, token):
    return f"http://{host}:{port}/app?token={token}"


def _build_app_url_from_base(base_url, token):
    if not base_url:
        return ""
    return f"{base_url.rstrip('/')}/app?token={token}"


def _render_qr_data_url(data):
    if not qrcode:
        return ""

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _mouse_overlay_point(image_size):
    mouse_x, mouse_y = pyautogui.position()
    logical_width, logical_height = pyautogui.size()
    image_width, image_height = image_size

    scale_x = image_width / logical_width if logical_width else 1.0
    scale_y = image_height / logical_height if logical_height else 1.0
    return mouse_x * scale_x, mouse_y * scale_y


def _capture_payload(quality, max_width):
    screenshot = pyautogui.screenshot()
    screen_width, screen_height = screenshot.size

    try:
        mouse_x, mouse_y = _mouse_overlay_point(screenshot.size)
        draw = ImageDraw.Draw(screenshot)
        radius = 10
        draw.ellipse(
            (mouse_x - radius, mouse_y - radius, mouse_x + radius, mouse_y + radius),
            outline="#ff4d4d",
            width=3,
        )
        draw.ellipse(
            (mouse_x - 2, mouse_y - 2, mouse_x + 2, mouse_y + 2),
            fill="#ff4d4d",
        )
    except Exception:
        pass

    if screenshot.width > max_width:
        ratio = max_width / screenshot.width
        screenshot = screenshot.resize(
            (max_width, int(screenshot.height * ratio)),
            Image.LANCZOS,
        )

    buffer = io.BytesIO()
    screenshot = screenshot.convert("RGB")
    screenshot.save(buffer, format="JPEG", quality=quality, optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return {
        "image": encoded,
        "width": screenshot.width,
        "height": screenshot.height,
        "screen_width": screen_width,
        "screen_height": screen_height,
        "timestamp": time.time(),
    }


def _perform_click(x_ratio, y_ratio, button="left"):
    screen_width, screen_height = pyautogui.size()
    x = int(_clamp_ratio(x_ratio) * screen_width)
    y = int(_clamp_ratio(y_ratio) * screen_height)
    x = max(0, min(x, screen_width - 1))
    y = max(0, min(y, screen_height - 1))

    if button == "right":
        pyautogui.rightClick(x, y)
    elif button == "double":
        pyautogui.doubleClick(x, y)
    else:
        pyautogui.click(x, y)


def _perform_scroll(x_ratio, y_ratio, delta):
    screen_width, screen_height = pyautogui.size()
    x = int(_clamp_ratio(x_ratio) * screen_width)
    y = int(_clamp_ratio(y_ratio) * screen_height)
    pyautogui.moveTo(x, y)
    pyautogui.scroll(int(delta))


def _perform_keypress(keys):
    if not keys:
        return
    if "+" in keys:
        SystemOps.execute_hotkey(
            [part.strip() for part in keys.split("+") if part.strip()]
        )
    else:
        SystemOps.press_key(keys.strip())


def _perform_type(text):
    if text:
        SystemOps.type_text(text)


def _parse_cookie_header(raw_cookie):
    pairs = {}
    for chunk in (raw_cookie or "").split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            pairs[key] = value
    return pairs


def _device_label_from_user_agent(user_agent):
    text = (user_agent or "").lower()
    parts = []
    if "iphone" in text:
        parts.append("iPhone")
    elif "ipad" in text:
        parts.append("iPad")
    elif "android" in text:
        parts.append("Android")
    elif "windows" in text:
        parts.append("Windows")
    elif "mac os" in text or "macintosh" in text:
        parts.append("Mac")

    if "safari" in text and "chrome" not in text:
        parts.append("Safari")
    elif "chrome" in text or "crios" in text:
        parts.append("Chrome")
    elif "firefox" in text:
        parts.append("Firefox")
    elif "edg" in text:
        parts.append("Edge")

    return " ".join(parts) or "Guvenilir Cihaz"


class SessionLinkStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {}

    def _cleanup_locked(self, now):
        expired_tokens = [
            token
            for token, session in self._sessions.items()
            if session["expires_at"] is not None and session["expires_at"] <= now
        ]
        for token in expired_tokens:
            self._sessions.pop(token, None)

    def _snapshot_locked(self, session, *, include_token=False, now=None):
        current = now or time.time()
        expires_at = session["expires_at"]
        expires_in = None if expires_at is None else max(0, int(expires_at - current))
        payload = {
            "label": session["label"],
            "created_at": session["created_at"],
            "duration_minutes": session.get("duration_minutes", 0),
            "expires_at": expires_at,
            "expires_in": expires_in,
            "expires_in_text": _format_ttl(expires_in),
            "expires_unlimited": expires_at is None,
            "last_seen": session["last_seen"],
        }
        if include_token:
            payload["token"] = session["token"]
        return payload

    def create(self, ttl_seconds, *, label="phone-client"):
        ttl_seconds = None if ttl_seconds in (None, 0, "", False) else max(300, int(ttl_seconds))
        duration_minutes = 0 if ttl_seconds is None else max(5, int(ttl_seconds // 60))
        now = time.time()
        token = secrets.token_urlsafe(24)
        session = {
            "token": token,
            "label": (label or "phone-client").strip()[:80],
            "duration_minutes": duration_minutes,
            "created_at": now,
            "expires_at": None if ttl_seconds is None else now + ttl_seconds,
            "last_seen": 0.0,
        }
        with self._lock:
            self._cleanup_locked(now)
            self._sessions[token] = session
            return self._snapshot_locked(session, include_token=True, now=now)

    def consume(self, token):
        if not token:
            return None
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            session = self._sessions.get(token)
            if not session:
                return None
            session["last_seen"] = now
            return self._snapshot_locked(session, include_token=True, now=now)


class TrustedDeviceStore:
    def __init__(self, storage_path):
        self.storage_path = Path(storage_path)
        self._lock = threading.Lock()
        self._devices = self._load()

    def _load(self):
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    def _save_locked(self):
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(
            json.dumps(self._devices, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _snapshot_locked(self, device, *, include_token=False, now=None):
        current = now or time.time()
        payload = {
            "label": device["label"],
            "device_label": device["label"],
            "trusted_device": True,
            "created_at": device["created_at"],
            "expires_at": None,
            "expires_in": None,
            "expires_in_text": "Sinirsiz",
            "expires_unlimited": True,
            "last_seen": device.get("last_seen", 0.0),
            "last_seen_ago": max(0, int(current - device.get("last_seen", 0.0))) if device.get("last_seen") else None,
        }
        if include_token:
            payload["token"] = device["token"]
        return payload

    def count(self):
        with self._lock:
            return len(self._devices)

    def create(self, *, label="Guvenilir Cihaz", user_agent=""):
        now = time.time()
        token = secrets.token_urlsafe(32)
        device = {
            "token": token,
            "label": (label or _device_label_from_user_agent(user_agent)).strip()[:80] or "Guvenilir Cihaz",
            "created_at": now,
            "last_seen": now,
            "user_agent": (user_agent or "").strip()[:240],
        }
        with self._lock:
            self._devices[token] = device
            self._save_locked()
            return self._snapshot_locked(device, include_token=True, now=now)

    def consume(self, token):
        if not token:
            return None
        now = time.time()
        with self._lock:
            device = self._devices.get(token)
            if not device:
                return None
            device["last_seen"] = now
            self._save_locked()
            return self._snapshot_locked(device, include_token=True, now=now)


def _expired_page():
    return """<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AgentCockpit Link Gecersiz</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: radial-gradient(circle at top, rgba(56,163,255,.18), transparent 35%), #0d1016;
      color: #edf1f7;
      font-family: "Segoe UI", system-ui, sans-serif;
      padding: 24px;
    }
    .card {
      max-width: 420px;
      background: rgba(18, 22, 32, 0.92);
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 22px;
      padding: 24px;
      box-shadow: 0 18px 48px rgba(0,0,0,.32);
    }
    h1 { margin: 0 0 12px; font-size: 24px; }
    p { margin: 0; line-height: 1.6; color: #b8c3d6; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Link suresi dolmus veya gecersiz</h1>
    <p>Bu telefon linki artik kullanilamiyor. Masaustundeki AgentCockpit phone bridge penceresinden yeni link alip tekrar deneyelim.</p>
  </div>
</body>
</html>"""


class PhoneBridgeHandler(BaseHTTPRequestHandler):
    server_version = "AgentCockpitPhone/2.0"

    def log_message(self, format, *args):
        logger.info(f"{self.address_string()} - {format % args}")

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def _cache_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")

    def _json_response(self, payload, status=HTTPStatus.OK, extra_headers=None):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._cache_headers()
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def _text_response(
        self,
        text,
        status=HTTPStatus.OK,
        content_type="text/plain; charset=utf-8",
        extra_headers=None,
    ):
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self._cache_headers()
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def _serve_file(self, path, content_type, *, cacheable=False, extra_headers=None):
        if not path.exists():
            self._text_response("Not found", status=HTTPStatus.NOT_FOUND)
            return
        raw = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        if cacheable:
            self.send_header("Cache-Control", "public, max-age=3600")
        else:
            self._cache_headers()
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def _extract_token(self):
        query = self._query()
        return (
            query.get("token", [""])[0]
            or self.headers.get("X-AgentCockpit-Token", "")
        ).strip()

    def _extract_device_token(self):
        cookies = _parse_cookie_header(self.headers.get("Cookie", ""))
        return (
            cookies.get("acp_device", "")
            or self.headers.get("X-AgentCockpit-Device", "")
        ).strip()

    def _extract_admin_token(self):
        query = self._query()
        return (
            query.get("admin_token", [""])[0]
            or self.headers.get("X-AgentCockpit-Admin", "")
        ).strip()

    def _is_local_request(self):
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except Exception:
            return False

    def _get_viewer_session(self):
        session = self.server.session_links.consume(self._extract_token())
        if session:
            return session, "link"

        trusted_device = self.server.trusted_devices.consume(self._extract_device_token())
        if trusted_device:
            return trusted_device, "trusted"
        return None, None

    def _require_viewer_session(self, *, html=False):
        session, auth_kind = self._get_viewer_session()
        if session:
            return session, auth_kind

        if html:
            self._text_response(
                _expired_page(),
                status=HTTPStatus.FORBIDDEN,
                content_type="text/html; charset=utf-8",
            )
        else:
            self._json_response(
                {"status": "forbidden", "message": "Invalid or expired phone link."},
                status=HTTPStatus.FORBIDDEN,
            )
        return None, None

    def _require_admin(self):
        if self._extract_admin_token() == self.server.admin_token:
            return True
        self._json_response(
            {"status": "forbidden", "message": "Invalid admin token."},
            status=HTTPStatus.FORBIDDEN,
        )
        return False

    def _require_local_pairing_access(self):
        if self._is_local_request():
            return True
        self._json_response(
            {
                "status": "forbidden",
                "message": "QR pairing dashboard is only available from this PC.",
            },
            status=HTTPStatus.FORBIDDEN,
        )
        return False

    def _build_session_payload(self, session):
        return {
            "label": session["label"],
            "expires_at": session["expires_at"],
            "expires_in": session["expires_in"],
            "expires_in_text": session["expires_in_text"],
            "expires_unlimited": session.get("expires_unlimited", False),
            "last_seen": session["last_seen"],
        }

    def _build_link_payload(self, session):
        request_host = self.headers.get("Host") or f"{_get_local_ip()}:{self.server.server_port}"
        lan_ips = _get_local_ipv4_candidates()
        lan_urls = [
            _build_app_url(ip, self.server.server_port, session["token"])
            for ip in lan_ips
        ]
        lan_url = lan_urls[0] if lan_urls else _build_app_url(_get_local_ip(), self.server.server_port, session["token"])
        local_url = _build_app_url("127.0.0.1", self.server.server_port, session["token"])
        public_url = self.server.get_public_url()
        wan_url = _build_app_url_from_base(public_url, session["token"])
        return {
            **self._build_session_payload(session),
            "token": session["token"],
            "app_url": f"http://{request_host}/app?token={session['token']}",
            "preferred_url": wan_url or lan_url,
            "qr_url": wan_url or lan_url,
            "lan_url": lan_url,
            "lan_urls": lan_urls,
            "lan_ips": lan_ips,
            "local_url": local_url,
            "wan_url": wan_url,
            "public_url": public_url,
            "wan_available": bool(wan_url),
        }

    def _build_pairing_payload(self, session):
        link_payload = self._build_link_payload(session)
        return {
            **link_payload,
            "installation_id": get_installation_id(),
            "pairing_kind": "lan-qr",
            "default_minutes": self.server.default_session_minutes,
            "qr_data_url": _render_qr_data_url(link_payload["qr_url"]),
        }

    def _serve_pairing_page(self, pairing_payload):
        page_path = PHONE_CLIENT_DIR / "pair.html"
        if not page_path.exists():
            self._text_response(
                "Pairing page not found.",
                status=HTTPStatus.NOT_FOUND,
            )
            return

        html = page_path.read_text(encoding="utf-8")
        html = html.replace(
            "{{PAIRING_JSON}}",
            json.dumps(pairing_payload, ensure_ascii=False),
        )
        html = html.replace("{{PAIRING_API_PATH}}", "/api/pairing-session")
        html = html.replace("{{INSTALLATION_ID}}", pairing_payload["installation_id"])
        self._text_response(html, content_type="text/html; charset=utf-8")

    def _read_json_body(self):
        try:
            raw_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raw_length = 0

        try:
            return json.loads(self.rfile.read(raw_length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json_response(
                {"status": "bad_request", "message": "Invalid JSON body."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/health":
            lan_ips = _get_local_ipv4_candidates()
            tunnel_snapshot = self.server.public_tunnel_snapshot()
            self._json_response(
                {
                    "status": "ok",
                    "client": "phone-bridge",
                    "transport": "http",
                    "screen": f"{pyautogui.size().width}x{pyautogui.size().height}",
                    "session_minutes": self.server.default_session_minutes,
                    "session_unlimited": self.server.default_session_minutes <= 0,
                    "default_duration_text": "Sinirsiz" if self.server.default_session_minutes <= 0 else _format_ttl(self.server.default_session_minutes * 60),
                    "lan_ips": lan_ips,
                    "trusted_devices": self.server.trusted_devices.count(),
                    "pairing_local_only": True,
                    "public_url": tunnel_snapshot.get("public_url", ""),
                    "public_tunnel_enabled": tunnel_snapshot.get("enabled", False),
                    "public_tunnel_status": tunnel_snapshot.get("status", "kapali"),
                    "public_tunnel_error": tunnel_snapshot.get("error", ""),
                    "public_tunnel_restart_count": tunnel_snapshot.get("restart_count", 0),
                    "public_tunnel_last_exit_code": tunnel_snapshot.get("last_exit_code"),
                    "wan_pwa_available": bool(tunnel_snapshot.get("public_url")),
                    "telegram_wan_available": bool(_telegram_bot_url()),
                }
            )
            return

        if route == "/":
            if self._is_local_request():
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/pair")
                self.end_headers()
                return

            message = (
                "AgentCockpit phone bridge is running.\n\n"
                "Pairing links are only shown on the local PC or through the authorized Telegram panel.\n"
            )
            self._text_response(message)
            return

        if route == "/pair":
            if not self._require_local_pairing_access():
                return
            self._serve_pairing_page(self._build_pairing_payload(self.server.startup_session))
            return

        if route == "/app":
            session, auth_kind = self._require_viewer_session(html=True)
            if not session:
                return
            html_path = PHONE_CLIENT_DIR / "index.html"
            if not html_path.exists():
                self._text_response(
                    "Phone client not found.", status=HTTPStatus.NOT_FOUND
                )
                return
            html = html_path.read_text(encoding="utf-8")
            public_url = self.server.get_public_url()
            handoff_token = (
                session.get("token", "")
                if auth_kind == "link"
                else self.server.startup_session.get("token", "")
            )
            wan_url = _build_app_url_from_base(public_url, handoff_token)
            html = html.replace("{{TOKEN}}", session.get("token", "") if auth_kind == "link" else "")
            html = html.replace("{{POLL_MS}}", str(self.server.poll_ms))
            html = html.replace("{{TELEGRAM_BOT_URL}}", _telegram_bot_url())
            html = html.replace("{{PUBLIC_URL}}", public_url)
            html = html.replace("{{WAN_URL}}", wan_url)
            html = html.replace(
                "{{MANIFEST_PATH}}",
                "/manifest.webmanifest",
            )
            extra_headers = None
            if auth_kind == "link":
                trusted_device = self.server.trusted_devices.consume(self._extract_device_token())
                if not trusted_device:
                    trusted_device = self.server.trusted_devices.create(
                        label=_device_label_from_user_agent(self.headers.get("User-Agent", "")),
                        user_agent=self.headers.get("User-Agent", ""),
                    )
                extra_headers = {
                    "Set-Cookie": f"acp_device={trusted_device['token']}; Path=/; Max-Age=31536000; SameSite=Lax; HttpOnly"
                }
            self._text_response(html, content_type="text/html; charset=utf-8", extra_headers=extra_headers)
            return

        if route == "/manifest.webmanifest":
            manifest_path = PHONE_CLIENT_DIR / "manifest.webmanifest"
            if not manifest_path.exists():
                self._text_response("Manifest not found", status=HTTPStatus.NOT_FOUND)
                return
            manifest = manifest_path.read_text(encoding="utf-8")
            manifest = manifest.replace("{{START_URL}}", "/app")
            self._text_response(
                manifest,
                content_type="application/manifest+json; charset=utf-8",
            )
            return

        static_assets = {
            "/icon.svg": ("icon.svg", "image/svg+xml", True, None),
            "/icon-192.png": ("icon-192.png", "image/png", True, None),
            "/icon-512.png": ("icon-512.png", "image/png", True, None),
            "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png", True, None),
            "/offline.html": ("offline.html", "text/html; charset=utf-8", True, None),
            "/sw.js": (
                "sw.js",
                "application/javascript; charset=utf-8",
                False,
                {"Service-Worker-Allowed": "/"},
            ),
        }

        if route in static_assets:
            filename, content_type, cacheable, extra_headers = static_assets[route]
            self._serve_file(
                PHONE_CLIENT_DIR / filename,
                content_type,
                cacheable=cacheable,
                extra_headers=extra_headers,
            )
            return

        if route == "/api/screenshot":
            session, auth_kind = self._require_viewer_session()
            if not session:
                return
            handoff_token = (
                session.get("token", "")
                if auth_kind == "link"
                else self.server.startup_session.get("token", "")
            )
            payload = _capture_payload(
                self.server.screenshot_quality,
                self.server.max_width,
            )
            payload["session"] = self._build_session_payload(session)
            payload["public_url"] = self.server.get_public_url()
            payload["wan_url"] = _build_app_url_from_base(
                self.server.get_public_url(),
                handoff_token,
            )
            self._json_response(payload)
            return

        if route == "/api/session":
            session, auth_kind = self._require_viewer_session()
            if not session:
                return
            handoff_token = (
                session.get("token", "")
                if auth_kind == "link"
                else self.server.startup_session.get("token", "")
            )
            self._json_response(
                {
                    "status": "ok",
                    "screen_width": pyautogui.size().width,
                    "screen_height": pyautogui.size().height,
                    "poll_ms": self.server.poll_ms,
                    "quality": self.server.screenshot_quality,
                    "max_width": self.server.max_width,
                    "auth_kind": auth_kind,
                    "public_url": self.server.get_public_url(),
                    "wan_url": _build_app_url_from_base(
                        self.server.get_public_url(),
                        handoff_token,
                    ),
                    "session": self._build_session_payload(session),
                }
            )
            return

        self._text_response("Not found", status=HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/api/pairing-session":
            if not self._require_local_pairing_access():
                return
            payload = self._read_json_body()
            if payload is None:
                return
            raw_minutes = payload.get("minutes", self.server.default_session_minutes)
            minutes = int(raw_minutes) if raw_minutes not in (None, "") else self.server.default_session_minutes
            label = str(payload.get("label", "pair-qr")).strip()[:80] or "pair-qr"
            ttl_seconds = None if minutes <= 0 else minutes * 60
            session = self.server.session_links.create(ttl_seconds, label=label)
            self.server.startup_session = session
            lan_ips = _get_local_ipv4_candidates()
            self.server.startup_link = _build_app_url(
                lan_ips[0] if lan_ips else _get_local_ip(),
                self.server.server_port,
                session["token"],
            )
            self._json_response(
                {
                    "status": "ok",
                    "pairing": self._build_pairing_payload(session),
                }
            )
            return

        if route == "/api/session-links":
            if not self._require_admin():
                return
            payload = self._read_json_body()
            if payload is None:
                return
            raw_minutes = payload.get("minutes", self.server.default_session_minutes)
            minutes = int(raw_minutes) if raw_minutes not in (None, "") else self.server.default_session_minutes
            label = str(payload.get("label", "phone-client")).strip()[:80] or "phone-client"
            ttl_seconds = None if minutes <= 0 else minutes * 60
            session = self.server.session_links.create(ttl_seconds, label=label)
            self._json_response(
                {
                    "status": "ok",
                    "session": self._build_link_payload(session),
                }
            )
            return

        if route != "/api/action":
            self._text_response("Not found", status=HTTPStatus.NOT_FOUND)
            return

        session, auth_kind = self._require_viewer_session()
        if not session:
            return

        payload = self._read_json_body()
        if payload is None:
            return

        action_type = payload.get("type", "")
        delay = max(0.0, min(2.0, float(payload.get("delay", 0.15))))

        try:
            if action_type == "click":
                _perform_click(
                    payload.get("x", 0.0),
                    payload.get("y", 0.0),
                    payload.get("button", "left"),
                )
            elif action_type == "scroll":
                _perform_scroll(
                    payload.get("x", 0.5),
                    payload.get("y", 0.5),
                    payload.get("delta", 0),
                )
            elif action_type == "key":
                _perform_keypress(payload.get("keys", ""))
            elif action_type == "type":
                _perform_type(payload.get("text", ""))
            elif action_type == "refresh":
                pass
            else:
                self._json_response(
                    {
                        "status": "bad_request",
                        "message": f"Unknown action: {action_type}",
                    },
                    status=HTTPStatus.BAD_REQUEST,
                )
                return

            if delay:
                time.sleep(delay)

            refreshed_session = self.server.session_links.consume(session["token"]) or session
            handoff_token = (
                session.get("token", "")
                if auth_kind == "link"
                else self.server.startup_session.get("token", "")
            )
            screenshot_payload = _capture_payload(
                self.server.screenshot_quality,
                self.server.max_width,
            )
            screenshot_payload["public_url"] = self.server.get_public_url()
            screenshot_payload["wan_url"] = _build_app_url_from_base(
                self.server.get_public_url(),
                handoff_token,
            )
            self._json_response(
                {
                    "status": "ok",
                    "action": action_type,
                    "session": self._build_session_payload(refreshed_session),
                    "public_url": self.server.get_public_url(),
                    "wan_url": _build_app_url_from_base(
                        self.server.get_public_url(),
                        handoff_token,
                    ),
                    "screenshot": screenshot_payload,
                }
            )
        except Exception as exc:
            logger.exception("Phone bridge action failed: %s", exc)
            self._json_response(
                {"status": "error", "message": str(exc)},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )


class PhoneBridgeServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address,
        handler_class,
        *,
        admin_token,
        screenshot_quality,
        max_width,
        poll_ms,
        default_session_minutes,
    ):
        super().__init__(server_address, handler_class)
        self.admin_token = admin_token
        self.screenshot_quality = screenshot_quality
        self.max_width = max_width
        self.poll_ms = poll_ms
        self.default_session_minutes = default_session_minutes
        self.public_tunnel = None
        self.session_links = SessionLinkStore()
        self.trusted_devices = TrustedDeviceStore(TRUSTED_DEVICES_FILE)
        self.startup_session = self.session_links.create(
            None if self.default_session_minutes <= 0 else self.default_session_minutes * 60,
            label="startup-phone",
        )
        startup_ips = _get_local_ipv4_candidates()
        self.startup_link = _build_app_url(
            startup_ips[0] if startup_ips else _get_local_ip(),
            self.server_port,
            self.startup_session["token"],
        )

    def get_public_url(self):
        if not self.public_tunnel:
            return ""
        return self.public_tunnel.get_public_url(validate=True)

    def public_tunnel_snapshot(self):
        if not self.public_tunnel:
            return {
                "enabled": False,
                "status": "kapali",
                "public_url": "",
                "error": "",
            }
        return self.public_tunnel.snapshot()


def build_arg_parser():
    parser = argparse.ArgumentParser(description="AgentCockpit phone bridge server")
    parser.add_argument("--bind", default=DEFAULT_BIND, help="Bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTP port")
    parser.add_argument(
        "--admin-token",
        default=DEFAULT_ADMIN_TOKEN,
        help="Admin token used to mint new phone links",
    )
    parser.add_argument(
        "--session-minutes",
        type=int,
        default=DEFAULT_SESSION_MINUTES,
        help="Default lifetime for generated phone links. 0 = unlimited",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_QUALITY,
        help="JPEG screenshot quality (20-95)",
    )
    parser.add_argument(
        "--max-width",
        type=int,
        default=DEFAULT_MAX_WIDTH,
        help="Maximum screenshot width",
    )
    parser.add_argument(
        "--poll-ms",
        type=int,
        default=DEFAULT_POLL_MS,
        help="Suggested screenshot polling interval in milliseconds",
    )
    parser.add_argument(
        "--public-tunnel",
        default=DEFAULT_PUBLIC_TUNNEL,
        choices=("auto", "on", "off"),
        help="Start a free Cloudflare Quick Tunnel for WAN PWA access",
    )
    return parser


def run_server(bind, port, admin_token, session_minutes, quality, max_width, poll_ms, public_tunnel="auto"):
    server = PhoneBridgeServer(
        (bind, port),
        PhoneBridgeHandler,
        admin_token=admin_token,
        screenshot_quality=max(20, min(95, quality)),
        max_width=max(640, max_width),
        poll_ms=max(500, poll_ms),
        default_session_minutes=int(session_minutes),
    )

    lan_ips = _get_local_ipv4_candidates()
    startup_session = server.startup_session
    lan_urls = [
        _build_app_url(ip, port, startup_session["token"])
        for ip in lan_ips
    ]
    lan_url = lan_urls[0] if lan_urls else _build_app_url(_get_local_ip(), port, startup_session["token"])
    localhost_url = _build_app_url("127.0.0.1", port, startup_session["token"])
    server.public_tunnel = start_public_tunnel(
        f"http://127.0.0.1:{port}",
        mode=public_tunnel,
    )
    public_url = server.get_public_url()
    wan_url = _build_app_url_from_base(public_url, startup_session["token"])

    logger.info("AgentCockpit phone bridge basladi")
    logger.info(f"Phone app (LAN): {lan_url}")
    if wan_url:
        logger.info(f"Phone app (WAN): {wan_url}")
    logger.info(f"Phone app (Localhost): {localhost_url}")
    logger.info(f"Phone installation id: {get_installation_id()}")
    logger.info(f"Phone admin token: {admin_token}")
    logger.info(f"Phone runtime token file: {get_runtime_paths()['admin_token_file']}")
    print("AgentCockpit phone bridge hazir.")
    print(f"Pairing Dashboard (this PC): http://127.0.0.1:{port}/pair")
    print(f"LAN URL ({startup_session['expires_in_text']}): {lan_url}")
    if len(lan_urls) > 1:
        for index, alt_url in enumerate(lan_urls[1:], start=2):
            print(f"LAN URL {index} ({startup_session['expires_in_text']}): {alt_url}")
    if wan_url:
        print(f"WAN URL ({startup_session['expires_in_text']}): {wan_url}")
    else:
        tunnel_snapshot = server.public_tunnel_snapshot()
        if tunnel_snapshot.get("enabled"):
            print(
                "WAN URL: hazirlaniyor veya kapali "
                f"({tunnel_snapshot.get('status', 'bilinmiyor')})"
            )
    print(f"Local URL ({startup_session['expires_in_text']}): {localhost_url}")
    print(f"Installation id: {get_installation_id()}")
    print(f"Admin token: {admin_token}")
    print(f"Token file: {get_runtime_paths()['admin_token_file']}")
    print(
        "Not: Varsayilan telefon linki sinirsizdir. Yeni link uretmek icin /api/session-links endpoint'ini admin token ile cagirabilirsin."
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nKapatiliyor...")
    finally:
        if server.public_tunnel:
            server.public_tunnel.stop()
        server.server_close()


def main():
    args = build_arg_parser().parse_args()
    run_server(
        bind=args.bind,
        port=args.port,
        admin_token=args.admin_token,
        session_minutes=args.session_minutes,
        quality=args.quality,
        max_width=args.max_width,
        poll_ms=args.poll_ms,
        public_tunnel=args.public_tunnel,
    )


if __name__ == "__main__":
    main()

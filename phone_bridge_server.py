import argparse
import base64
import gc
import importlib
import ipaddress
import io
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from urllib.parse import parse_qs, urlparse

ROOT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT_DIR

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from core.dns_fallback import install as install_dns_fallback
    from core.dns_fallback import install_tls_fallback

    install_dns_fallback()
    install_tls_fallback()
except Exception:
    pass

from PIL import Image, ImageDraw
from core.app_config import get_float, get_int, get_str
from dotenv import load_dotenv
try:
    import qrcode
except ImportError:
    qrcode = None

from core.logger import (
    get_logger,
    install_diagnostics_hooks,
    record_runtime_event,
    start_diagnostics_heartbeat,
)
from core.runtime_compat import desktop_automation_help_text, detect_runtime_compatibility
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
_PYAUTOGUI = None
_CAPTURE_STATE = {
    "last_error": "",
    "last_error_at": 0.0,
    "last_success_at": 0.0,
    "last_width": 0,
    "last_height": 0,
    "failure_count": 0,
    "backoff_until": 0.0,
}
_CAPTURE_STATE_LOCK = threading.Lock()
_CAPTURE_LOCK = threading.Lock()
_KEEP_AWAKE_PROCESS = None
_KEEP_AWAKE_ERROR = ""

PHONE_CLIENT_DIR = ROOT_DIR / "phone_client"

LOCAL_HOST = get_str("AGENTCOCKPIT_LOCAL_HOST")
DEFAULT_BIND = get_str("PHONE_BIND")
DEFAULT_PORT = get_int("PHONE_PORT")
DEFAULT_ADMIN_TOKEN = get_shared_admin_token()
DEFAULT_QUALITY = max(20, min(95, get_int("PHONE_SCREENSHOT_QUALITY")))
DEFAULT_MAX_WIDTH = max(640, get_int("PHONE_SCREENSHOT_MAX_WIDTH"))
DEFAULT_POLL_MS = max(500, get_int("PHONE_POLL_MS"))
DEFAULT_SESSION_MINUTES = get_int("PHONE_SESSION_MINUTES")
DEFAULT_TELEGRAM_URL = get_str("PHONE_TELEGRAM_URL")
DEFAULT_TELEGRAM_USERNAME = get_str("TELEGRAM_BOT_USERNAME").lstrip("@")
DEFAULT_PUBLIC_TUNNEL = get_str("PHONE_PUBLIC_TUNNEL")
DEFAULT_KEEP_AWAKE = get_str("PHONE_KEEP_AWAKE")
DEFAULT_KEEP_AWAKE_FLAGS = get_str("PHONE_KEEP_AWAKE_FLAGS")
DEFAULT_CAPTURE_LOCK_TIMEOUT_SEC = max(0.5, get_float("PHONE_CAPTURE_LOCK_TIMEOUT_SEC", "3.0"))
DEFAULT_CAPTURE_UNAVAILABLE_RETRY_SEC = max(
    3.0, get_float("PHONE_CAPTURE_UNAVAILABLE_RETRY_SEC", "12.0")
)
DEFAULT_STREAM_MAX_CONNECTIONS = max(1, get_int("PHONE_STREAM_MAX_CONNECTIONS", "2"))
DEFAULT_STREAM_MAX_SECONDS = max(60.0, get_float("PHONE_STREAM_MAX_SECONDS", "600"))
DEFAULT_STREAM_GC_EVERY_FRAMES = max(30, get_int("PHONE_STREAM_GC_EVERY_FRAMES", "120"))


class CaptureUnavailable(RuntimeError):
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = int(max(1, retry_after or DEFAULT_CAPTURE_UNAVAILABLE_RETRY_SEC))


def _get_pyautogui():
    global _PYAUTOGUI
    if _PYAUTOGUI is not None:
        return _PYAUTOGUI

    try:
        _PYAUTOGUI = importlib.import_module("pyautogui")
        _PYAUTOGUI.FAILSAFE = os.environ.get("FAILSAFE_OFF", "").lower() != "true"
        return _PYAUTOGUI
    except Exception as exc:
        logger.error(f"Phone bridge pyautogui kullanilamiyor: {exc}")
        return None


def _require_pyautogui():
    pyautogui = _get_pyautogui()
    if not pyautogui:
        raise RuntimeError(desktop_automation_help_text())
    return pyautogui


def _get_screen_metrics():
    pyautogui = _get_pyautogui()
    if not pyautogui:
        return {"width": 0, "height": 0, "available": False}

    try:
        size = pyautogui.size()
        width = int(size.width)
        height = int(size.height)
        return {
            "width": width,
            "height": height,
            "available": bool(width > 0 and height > 0),
        }
    except Exception as exc:
        logger.error(f"Ekran boyutu okunamadi: {exc}")
        return {"width": 0, "height": 0, "available": False}


def _redact_capture_error(error):
    text = str(error or "").strip()
    text = re.sub(r"(/private)?/var/folders/\S+", "<temp-file>", text)
    text = re.sub(r"(/tmp|/var/tmp)/\S+", "<temp-file>", text)
    text = re.sub(r"([?&]token=)[^&\s]+", r"\1<redacted>", text)
    text = re.sub(r"\bacp_[A-Za-z0-9_-]+", "acp_<redacted>", text)
    text = " ".join(text.split())
    return text[:300]


def _redact_url_for_log(url):
    return _redact_capture_error(url)


def _stdout_secret(value):
    if os.environ.get("PHONE_PRINT_RAW_LINKS", "").strip().lower() in {"1", "true", "yes", "on"}:
        return value
    return _redact_capture_error(value)


def _stdout_admin_token(value):
    if os.environ.get("PHONE_PRINT_RAW_LINKS", "").strip().lower() in {"1", "true", "yes", "on"}:
        return value
    return "<redacted>"


def _record_capture_success(width, height):
    with _CAPTURE_STATE_LOCK:
        _CAPTURE_STATE["last_error"] = ""
        _CAPTURE_STATE["last_success_at"] = time.time()
        _CAPTURE_STATE["last_width"] = int(width)
        _CAPTURE_STATE["last_height"] = int(height)
        _CAPTURE_STATE["failure_count"] = 0
        _CAPTURE_STATE["backoff_until"] = 0.0


def _is_capture_unavailable_error(text):
    return bool(
        re.search(
            r"screen metrics unavailable|could not create image|cannot identify image|"
            r"Screen Recording|Siyah ekran|kilitli|uykuda|screencapture",
            str(text or ""),
            re.IGNORECASE,
        )
    )


def _record_capture_error(error):
    now = time.time()
    redacted = _redact_capture_error(error)
    with _CAPTURE_STATE_LOCK:
        _CAPTURE_STATE["last_error"] = redacted
        _CAPTURE_STATE["last_error_at"] = now
        _CAPTURE_STATE["failure_count"] = int(_CAPTURE_STATE.get("failure_count", 0)) + 1
        if isinstance(error, CaptureUnavailable) or _is_capture_unavailable_error(redacted):
            retry_after = getattr(error, "retry_after", DEFAULT_CAPTURE_UNAVAILABLE_RETRY_SEC)
            _CAPTURE_STATE["backoff_until"] = max(
                float(_CAPTURE_STATE.get("backoff_until", 0.0)),
                now + float(retry_after),
            )


def _capture_retry_after_seconds():
    with _CAPTURE_STATE_LOCK:
        backoff_until = float(_CAPTURE_STATE.get("backoff_until", 0.0) or 0.0)
    remaining = backoff_until - time.time()
    return int(remaining) + 1 if remaining > 0 else 0


def _raise_if_capture_deferred():
    retry_after = _capture_retry_after_seconds()
    if retry_after > 0:
        raise CaptureUnavailable(
            "Ekran yakalama gecici olarak durduruldu; macOS ekran oturumu hazir degil.",
            retry_after=retry_after,
        )

    screen = _get_screen_metrics()
    if not screen.get("available"):
        raise CaptureUnavailable(
            "Ekran yakalama hazir degil: screen metrics unavailable. "
            "Mac kilitli/uykuda olabilir veya aktif GUI ekran oturumu yok.",
            retry_after=DEFAULT_CAPTURE_UNAVAILABLE_RETRY_SEC,
        )


def _capture_retry_headers(error):
    retry_after = int(max(1, getattr(error, "retry_after", DEFAULT_CAPTURE_UNAVAILABLE_RETRY_SEC)))
    return {
        "Retry-After": str(retry_after),
        "X-AgentCockpit-Capture": "unavailable",
    }


def _capture_error_payload(error):
    retry_after = int(max(1, getattr(error, "retry_after", DEFAULT_CAPTURE_UNAVAILABLE_RETRY_SEC)))
    return {
        "status": "capture_unavailable",
        "message": _redact_capture_error(error),
        "retry_after": retry_after,
    }


def _capture_health(screen):
    with _CAPTURE_STATE_LOCK:
        state = dict(_CAPTURE_STATE)
    metrics_ok = bool(screen.get("available")) and screen.get("width", 0) > 0 and screen.get("height", 0) > 0
    capture_error = state["last_error"]
    if not metrics_ok:
        capture_error = "screen metrics unavailable"
    return {
        "capture_available": bool(metrics_ok and not capture_error),
        "capture_error": capture_error,
        "capture_last_error": state["last_error"],
        "capture_last_error_at": int(state["last_error_at"]) if state["last_error_at"] else 0,
        "capture_last_success_at": int(state["last_success_at"]) if state["last_success_at"] else 0,
        "capture_last_width": state["last_width"],
        "capture_last_height": state["last_height"],
        "capture_retry_after": _capture_retry_after_seconds(),
    }


def _diagnostic_snapshot(server=None):
    screen = _get_screen_metrics()
    capture = _capture_health(screen)
    snapshot = {
        "screen": {
            "width": screen.get("width", 0),
            "height": screen.get("height", 0),
            "available": bool(screen.get("available")),
        },
        "capture": capture,
        "keep_awake": _keep_awake_snapshot(),
    }
    if server is not None:
        try:
            tunnel = server.public_tunnel_snapshot(validate=False)
        except Exception as exc:
            tunnel = {"enabled": True, "status": "snapshot_error", "error": _redact_capture_error(exc)}
        snapshot["public_tunnel"] = {
            "enabled": tunnel.get("enabled", False),
            "provider": tunnel.get("provider", ""),
            "status": tunnel.get("status", ""),
            "has_public_url": bool(tunnel.get("public_url")),
            "error": tunnel.get("error", ""),
            "restart_count": tunnel.get("restart_count", 0),
            "last_exit_code": tunnel.get("last_exit_code", None),
            "primary_status": tunnel.get("primary_status", ""),
            "primary_error": tunnel.get("primary_error", ""),
            "fallback_status": tunnel.get("fallback_status", ""),
            "fallback_error": tunnel.get("fallback_error", ""),
            "fallback_last_exit_code": tunnel.get("fallback_last_exit_code", None),
        }
        try:
            snapshot["trusted_devices"] = server.trusted_devices.count()
        except Exception:
            snapshot["trusted_devices"] = None
        try:
            snapshot["session_links"] = server.session_links.count()
        except Exception:
            snapshot["session_links"] = None
        try:
            snapshot["stream"] = {
                "active": server.active_stream_count(),
                "max": server.max_stream_connections,
                "max_seconds": int(server.stream_max_seconds),
            }
        except Exception:
            snapshot["stream"] = None
    return snapshot


def _keep_awake_enabled():
    return DEFAULT_KEEP_AWAKE.strip().lower() not in {"", "0", "false", "no", "off", "disabled"}


def _start_keep_awake():
    global _KEEP_AWAKE_PROCESS, _KEEP_AWAKE_ERROR
    if sys.platform != "darwin" or not _keep_awake_enabled():
        return
    if _KEEP_AWAKE_PROCESS and _KEEP_AWAKE_PROCESS.poll() is None:
        return

    caffeinate = "/usr/bin/caffeinate"
    if not Path(caffeinate).exists():
        _KEEP_AWAKE_ERROR = "caffeinate bulunamadi"
        logger.warning(_KEEP_AWAKE_ERROR)
        return

    flags = [flag for flag in DEFAULT_KEEP_AWAKE_FLAGS.split() if flag.startswith("-")]
    if not flags:
        flags = ["-dims"]
    command = [caffeinate, *flags, "-w", str(os.getpid())]
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(0.15)
        if process.poll() is not None:
            stderr = (process.stderr.read() if process.stderr else "").strip()
            _KEEP_AWAKE_ERROR = _redact_capture_error(stderr or f"caffeinate cikti: {process.returncode}")
            logger.warning(f"Keep-awake baslatilamadi: {_KEEP_AWAKE_ERROR}")
            return
        _KEEP_AWAKE_PROCESS = process
        _KEEP_AWAKE_ERROR = ""
        logger.info(f"Keep-awake aktif: caffeinate {' '.join(flags)}")
    except Exception as exc:
        _KEEP_AWAKE_ERROR = _redact_capture_error(exc)
        logger.warning(f"Keep-awake baslatilamadi: {_KEEP_AWAKE_ERROR}")


def _keep_awake_snapshot():
    if sys.platform != "darwin" or not _keep_awake_enabled():
        return {"enabled": False, "active": False, "error": ""}
    active = bool(_KEEP_AWAKE_PROCESS and _KEEP_AWAKE_PROCESS.poll() is None)
    return {
        "enabled": True,
        "active": active,
        "error": "" if active else _KEEP_AWAKE_ERROR,
    }


def _telegram_bot_url():
    if DEFAULT_TELEGRAM_URL:
        return DEFAULT_TELEGRAM_URL
    if DEFAULT_TELEGRAM_USERNAME:
        return f"https://t.me/{DEFAULT_TELEGRAM_USERNAME}"
    return ""


def _get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return LOCAL_HOST


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

    # socket.getfqdn() can block on macOS while doing reverse mDNS lookups.
    # Hostname + active route IP is enough for LAN phone links.
    host_names = [socket.gethostname()]

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
    pyautogui = _get_pyautogui()
    if not pyautogui:
        raise RuntimeError(desktop_automation_help_text())

    mouse_x, mouse_y = pyautogui.position()
    logical_width, logical_height = pyautogui.size()
    image_width, image_height = image_size

    scale_x = image_width / logical_width if logical_width else 1.0
    scale_y = image_height / logical_height if logical_height else 1.0
    return mouse_x * scale_x, mouse_y * scale_y


def _capture_legacy():
    """Capture via screencapture/pyautogui -> RGB PIL image (no cursor, no scaling)."""
    primary_capture_error = None
    fallback_capture_error = None

    screenshot = None
    if sys.platform == "darwin":
        screenshot = _capture_with_screencapture()
        if screenshot is None:
            primary_capture_error = RuntimeError("screencapture ile ekran alinmadi")
            try:
                pyautogui = _require_pyautogui()
                screenshot = pyautogui.screenshot().convert("RGB")
            except Exception as exc:
                fallback_capture_error = exc
    else:
        try:
            pyautogui = _require_pyautogui()
            screenshot = pyautogui.screenshot().convert("RGB")
        except Exception as exc:
            primary_capture_error = exc

    if screenshot is None:
        detail = fallback_capture_error or primary_capture_error
        raise RuntimeError(
            "Ekran goruntusu olusturulamadi. "
            "macOS'ta Screen Recording iznini kontrol edin ve kilitli/uykuda ekran olmadigindan emin olun. "
            f"Asil hata: {detail}"
        ) from detail

    if _is_nearly_black_frame(screenshot):
        fallback = _capture_with_screencapture()
        if fallback and not _is_nearly_black_frame(fallback):
            screenshot = fallback
        else:
            raise RuntimeError(
                "Siyah ekran algilandi. Ekran kilitli/uykuda olabilir veya Screen Recording izni eksik. "
                "macOS'ta Terminal/iTerm icin Screen Recording iznini acip uygulamayi yeniden baslatin."
            )
    elif primary_capture_error is not None or fallback_capture_error is not None:
        logger.warning(
            "Primary screenshot path failed, backup screenshot path kullanildi: %s",
            fallback_capture_error or primary_capture_error,
        )

    return screenshot


_QUARTZ_STATE = {"checked": False, "ok": False}


def _capture_with_quartz():
    """Fast in-memory full-screen capture via Quartz. Returns an RGB image or None."""
    if sys.platform != "darwin":
        return None
    try:
        import Quartz
    except Exception:
        return None
    try:
        image_ref = Quartz.CGDisplayCreateImage(Quartz.CGMainDisplayID())
        if image_ref is None:
            return None
        width = Quartz.CGImageGetWidth(image_ref)
        height = Quartz.CGImageGetHeight(image_ref)
        if not width or not height:
            return None
        bytes_per_row = Quartz.CGImageGetBytesPerRow(image_ref)
        provider = Quartz.CGImageGetDataProvider(image_ref)
        data = Quartz.CGDataProviderCopyData(provider)
        if data is None:
            return None
        # CGDisplayCreateImage yields 32-bit little-endian BGRA; map straight to RGBA.
        image = Image.frombuffer(
            "RGBA", (width, height), bytes(data), "raw", "BGRA", bytes_per_row, 1
        )
        return image.convert("RGB")
    except Exception:
        return None


def _channel_means(image):
    small = image.resize((32, 18), Image.BILINEAR)
    pixels = list(small.getdata())
    count = len(pixels) or 1
    return tuple(sum(pixel[i] for pixel in pixels) / count for i in range(3))


def _validate_quartz_once():
    """One-time guard: only trust Quartz if its colours match screencapture, so a
    wrong pixel-format mapping can never silently ship miscoloured frames.

    A genuine format mismatch diverges on every attempt, whereas a transient
    screen change between the two samples only diverges sometimes -- so we retry
    a few rounds and accept Quartz if any round matches closely.
    """
    if _QUARTZ_STATE["checked"]:
        return _QUARTZ_STATE["ok"]
    _QUARTZ_STATE["checked"] = True
    try:
        if _capture_with_quartz() is None:
            _QUARTZ_STATE["ok"] = False
            return False
        best = None
        for _ in range(3):
            reference = _capture_with_screencapture()
            quartz_frame = _capture_with_quartz()
            if reference is None:
                # screencapture unavailable; Quartz is our only working capture path.
                _QUARTZ_STATE["ok"] = True
                logger.info("Hizli Quartz ekran yakalama etkin (screencapture dogrulamasi atlandi).")
                return True
            if quartz_frame is None:
                continue
            divergence = max(
                abs(q - r) for q, r in zip(_channel_means(quartz_frame), _channel_means(reference))
            )
            best = divergence if best is None else min(best, divergence)
            if divergence <= 45:
                _QUARTZ_STATE["ok"] = True
                logger.info("Hizli Quartz ekran yakalama etkin.")
                return True
        _QUARTZ_STATE["ok"] = False
        logger.warning(
            "Quartz renkleri screencapture ile uyusmadi (en iyi fark=%s); screencapture kullanilacak.",
            round(best) if best is not None else "?",
        )
    except Exception as exc:
        logger.warning(f"Quartz dogrulamasi basarisiz, screencapture kullanilacak: {exc}")
        _QUARTZ_STATE["ok"] = False
    return _QUARTZ_STATE["ok"]


def _raw_capture():
    """Capture the full screen -> RGB image. Prefers fast Quartz, falls back to screencapture."""
    if sys.platform == "darwin" and _validate_quartz_once():
        fast = _capture_with_quartz()
        if fast is not None and not _is_nearly_black_frame(fast):
            return fast
    return _capture_legacy()


def _close_image(image):
    try:
        image.close()
    except Exception:
        pass


def _raw_capture_serialized():
    """Serialize full-screen capture so concurrent WAN streams cannot fan out memory use."""
    _raise_if_capture_deferred()
    acquired = _CAPTURE_LOCK.acquire(timeout=DEFAULT_CAPTURE_LOCK_TIMEOUT_SEC)
    if not acquired:
        raise RuntimeError(
            "Ekran yakalama mesgul. Aktif goruntu akis sayisini azaltin veya sayfayi yenileyin."
        )
    try:
        return _raw_capture()
    finally:
        _CAPTURE_LOCK.release()


def _draw_cursor(image):
    try:
        mouse_x, mouse_y = _mouse_overlay_point(image.size)
        draw = ImageDraw.Draw(image)
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
    return image


def _scale_to_width(image, max_width):
    if image.width > max_width:
        ratio = max_width / image.width
        image = image.resize(
            (max_width, int(image.height * ratio)),
            Image.BILINEAR,
        )
    return image


def _frame_signature(raw_image):
    """Cheap change fingerprint of a raw capture.

    A tiny grayscale thumbnail plus the quantized cursor position. Folding the
    cursor in means pointer-only movement still yields a fresh frame (so the
    remote cursor stays live) without re-sending an otherwise unchanged screen.
    """
    try:
        factor = max(1, raw_image.width // 96)
        thumb = raw_image.reduce(factor).convert("L")
        checksum = zlib.crc32(thumb.tobytes()) & 0xFFFFFFFF
    except Exception:
        checksum = 0
    try:
        mouse_x, mouse_y = _get_pyautogui().position()
        checksum = zlib.crc32(f"|{mouse_x // 3},{mouse_y // 3}".encode(), checksum) & 0xFFFFFFFF
    except Exception:
        pass
    return format(checksum, "08x")


def _encode_jpeg(image, quality):
    buffer = io.BytesIO()
    # optimize=False trades ~10% size for a much cheaper encode, which matters
    # when frames are produced continuously for the live stream.
    image.save(buffer, format="JPEG", quality=quality, optimize=False)
    return buffer.getvalue()


def _grab_frame(quality, max_width):
    """Capture one finished frame.

    Returns (jpeg_bytes, signature, frame_w, frame_h, screen_w, screen_h).
    """
    raw = None
    image = None
    try:
        raw = _raw_capture_serialized()
        screen_width, screen_height = raw.size
        _record_capture_success(screen_width, screen_height)
        signature = _frame_signature(raw)
        image = _scale_to_width(_draw_cursor(raw), max_width)
        jpeg = _encode_jpeg(image, quality)
        return jpeg, signature, image.width, image.height, screen_width, screen_height
    except Exception as exc:
        _record_capture_error(exc)
        raise
    finally:
        if image is not None and image is not raw:
            _close_image(image)
        if raw is not None:
            _close_image(raw)


def _capture_payload(quality, max_width):
    jpeg, signature, frame_w, frame_h, screen_w, screen_h = _grab_frame(quality, max_width)
    return {
        "image": base64.b64encode(jpeg).decode("ascii"),
        "signature": signature,
        "width": frame_w,
        "height": frame_h,
        "screen_width": screen_w,
        "screen_height": screen_h,
        "timestamp": time.time(),
    }


def _parse_stream_params(query, default_quality, default_width):
    """Parse optional ?q=<jpeg quality>&w=<max width> for the frame/stream endpoints.

    Width is capped at 2560 so an 'HD' client mode can ask for more detail than
    the default while still staying well under the native Retina width.
    """
    try:
        requested_quality = int(query.get("q", [""])[0])
    except (TypeError, ValueError):
        requested_quality = default_quality
    quality = max(20, min(95, requested_quality))
    try:
        requested_width = int(query.get("w", [""])[0])
    except (TypeError, ValueError):
        requested_width = default_width
    max_width = max(640, min(2560, requested_width))
    return quality, max_width


def _is_nearly_black_frame(image, *, max_channel=4):
    try:
        extrema = image.convert("RGB").getextrema()
    except Exception:
        return False

    return all(channel_max <= max_channel for _, channel_max in extrema)


def _capture_with_screencapture():
    if sys.platform != "darwin":
        return None

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            temp_path = tmp.name

        result = subprocess.run(
            ["screencapture", "-x", "-t", "jpg", temp_path],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if result.returncode != 0:
            return None

        if not os.path.exists(temp_path) or os.path.getsize(temp_path) <= 0:
            return None

        with Image.open(temp_path) as captured:
            return captured.convert("RGB")
    except Exception:
        return None
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _perform_click(x_ratio, y_ratio, button="left"):
    pyautogui = _require_pyautogui()
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
    pyautogui = _require_pyautogui()
    screen_width, screen_height = pyautogui.size()
    x = int(_clamp_ratio(x_ratio) * screen_width)
    y = int(_clamp_ratio(y_ratio) * screen_height)
    pyautogui.moveTo(x, y)
    
    # PyAutoGUI has a platform-dependent inconsistency:
    # - On Windows, pyautogui.scroll() expects units where 120 is one scroll notch.
    # - On macOS and Linux, it expects units where 1 is one scroll notch/line.
    # The client sends values in Windows-compatible units (e.g. approx 120 per notch).
    if sys.platform in ("darwin", "linux", "linux2"):
        scaled_delta = int(delta / 120)
        if scaled_delta == 0 and delta != 0:
            scaled_delta = 1 if delta > 0 else -1
        pyautogui.scroll(scaled_delta)
    else:
        pyautogui.scroll(int(delta))


def _perform_keypress(keys):
    if not keys:
        return True
    if "+" in keys:
        return SystemOps.execute_hotkey(
            [part.strip() for part in keys.split("+") if part.strip()]
        )
    return SystemOps.press_key(keys.strip())


def _perform_focus_click(focus):
    if not isinstance(focus, dict):
        return False

    if "x" not in focus or "y" not in focus:
        return False

    _perform_click(focus.get("x"), focus.get("y"), "left")
    time.sleep(0.12)
    return True


def _perform_type(text, *, sensitive=False, focus=None):
    if not text:
        return True

    focused = _perform_focus_click(focus)
    pasted = SystemOps.paste_text(text, restore_clipboard=bool(sensitive))
    logger.info(
        f"Telefon metni clipboard paste ile gonderildi: chars={len(text)} "
        f"sensitive={bool(sensitive)} focus={focused} success={pasted}"
    )
    return pasted


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


class ActionDedup:
    """Single-flight + short-TTL cache keyed by request_id.

    The phone client retries a command (re-using the same request_id) when a
    response is lost in transit. This makes such a retry safe: the command is
    applied exactly once and every retry receives the original response instead
    of triggering the desktop action a second time.
    """

    def __init__(self, ttl_seconds=30.0, max_entries=256, wait_timeout=15.0, inflight_ttl=60.0):
        self._cond = threading.Condition()
        self._done = {}          # request_id -> (timestamp, response)
        self._inflight = {}      # request_id -> acquired timestamp
        self._order = deque()    # insertion order of completed ids for eviction
        self._ttl = ttl_seconds
        self._max = max_entries
        self._wait_timeout = wait_timeout
        # Safety net: if an owner ever fails to call complete()/abort() (e.g. an
        # unexpected error escapes the action handler), its reservation would
        # otherwise live forever and later block retries of the same request_id.
        # No real action takes anywhere near this long, so evicting stale
        # in-flight ids cannot drop a still-running one.
        self._inflight_ttl = inflight_ttl

    def _evict_locked(self, now):
        if self._inflight:
            stale = [rid for rid, ts in self._inflight.items() if now - ts > self._inflight_ttl]
            for rid in stale:
                self._inflight.pop(rid, None)
        while self._order:
            rid = self._order[0]
            entry = self._done.get(rid)
            if entry is None:
                self._order.popleft()
                continue
            if now - entry[0] > self._ttl:
                self._order.popleft()
                self._done.pop(rid, None)
                continue
            break
        while len(self._done) > self._max and self._order:
            rid = self._order.popleft()
            self._done.pop(rid, None)

    def acquire(self, request_id):
        """Reserve a request_id for execution.

        Returns ``(cached_response_or_None, is_owner)``:
        - ``(response, False)``  -> already applied; caller replays ``response``.
        - ``(None, True)``       -> caller owns execution; must call
          ``complete()`` on success or ``abort()`` on failure.
        - ``(None, False)``      -> no request_id, or the in-flight original took
          too long; caller proceeds best-effort without caching.
        """
        if not request_id:
            return (None, False)
        deadline = time.time() + self._wait_timeout
        with self._cond:
            while True:
                now = time.time()
                self._evict_locked(now)
                entry = self._done.get(request_id)
                if entry is not None:
                    return (entry[1], False)
                if request_id not in self._inflight:
                    self._inflight[request_id] = now
                    return (None, True)
                remaining = deadline - now
                if remaining <= 0:
                    return (None, False)
                self._cond.wait(remaining)

    def complete(self, request_id, response):
        if not request_id:
            return
        now = time.time()
        with self._cond:
            if request_id not in self._done:
                self._order.append(request_id)
            self._done[request_id] = (now, response)
            self._inflight.pop(request_id, None)
            self._evict_locked(now)
            self._cond.notify_all()

    def abort(self, request_id):
        if not request_id:
            return
        with self._cond:
            self._inflight.pop(request_id, None)
            self._cond.notify_all()


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
    # Bound the per-connection socket timeout so a slow/stalled client (e.g. a
    # slowloris sending headers or a body byte-by-byte, or one that stops
    # reading mid-stream) cannot pin a handler thread forever. Active screen
    # streams write a frame or keepalive at least once per second, so this never
    # trips a healthy stream; a stalled write raises OSError, which the stream
    # loop already treats as a clean disconnect.
    timeout = max(15, get_int("PHONE_BRIDGE_SOCKET_TIMEOUT_SEC"))
    # Cap request bodies so a huge/forged Content-Length cannot exhaust memory.
    MAX_REQUEST_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB

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
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("JSON response client tarafinda erken kapatildi.")

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
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("Text response client tarafinda erken kapatildi.")

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
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            logger.debug("File response client tarafinda erken kapatildi.")

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
        import hmac
        if hmac.compare_digest(self._extract_admin_token() or "", self.server.admin_token or ""):
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
        local_url = _build_app_url(LOCAL_HOST, self.server.server_port, session["token"])
        public_url = self.server.get_public_url(validate=True)
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
        if raw_length < 0:
            raw_length = 0
        if raw_length > self.MAX_REQUEST_BODY_BYTES:
            self._json_response(
                {"status": "payload_too_large", "message": "Request body too large."},
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return None

        try:
            raw_body = self.rfile.read(raw_length)
        except (OSError, ValueError):
            # Socket timeout / reset while reading the (possibly stalled) body.
            return None

        try:
            return json.loads(raw_body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json_response(
                {"status": "bad_request", "message": "Invalid JSON body."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return None

    def _coerce_minutes(self, payload):
        """Parse the client-supplied ``minutes`` field, replying 400 on garbage.

        Returns the int on success, or ``None`` after sending a bad-request
        response (so the caller just returns). A bare int() on attacker JSON
        would otherwise raise and tear down the connection with no response.
        """
        raw_minutes = payload.get("minutes", self.server.default_session_minutes)
        if raw_minutes in (None, ""):
            return self.server.default_session_minutes
        try:
            return int(raw_minutes)
        except (TypeError, ValueError):
            self._json_response(
                {"status": "bad_request", "message": "minutes must be an integer."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/_agentcockpit/tunnel-check":
            self._json_response({"status": "ok", "client": "phone-bridge"})
            return

        if route == "/health":
            lan_ips = _get_local_ipv4_candidates()
            tunnel_snapshot = self.server.public_tunnel_snapshot(validate=True)
            screen = _get_screen_metrics()
            capture = _capture_health(screen)
            keep_awake = _keep_awake_snapshot()
            compatibility = detect_runtime_compatibility()
            input_permissions = SystemOps.desktop_input_permissions()
            self._json_response(
                {
                    "status": "ok",
                    "client": "phone-bridge",
                    "transport": "http",
                    "screen": f"{screen['width']}x{screen['height']}" if screen["available"] else "unavailable",
                    "screen_width": screen["width"],
                    "screen_height": screen["height"],
                    "screen_available": screen["available"],
                    "capture_available": capture["capture_available"],
                    "capture_error": capture["capture_error"],
                    "capture_last_error": capture["capture_last_error"],
                    "capture_last_error_at": capture["capture_last_error_at"],
                    "capture_last_success_at": capture["capture_last_success_at"],
                    "capture_last_width": capture["capture_last_width"],
                    "capture_last_height": capture["capture_last_height"],
                    "capture_retry_after": capture["capture_retry_after"],
                    "keep_awake_enabled": keep_awake["enabled"],
                    "keep_awake_active": keep_awake["active"],
                    "keep_awake_error": keep_awake["error"],
                    "runtime_platform": compatibility["platform"],
                    "gui_session": compatibility["gui_session"],
                    "browser_available": compatibility["browser_available"],
                    "desktop_automation_available": compatibility["desktop_automation_available"],
                    "desktop_automation_reason": compatibility["desktop_automation_reason"],
                    "desktop_input_permissions": input_permissions,
                    "session_minutes": self.server.default_session_minutes,
                    "session_unlimited": self.server.default_session_minutes <= 0,
                    "default_duration_text": "Sinirsiz" if self.server.default_session_minutes <= 0 else _format_ttl(self.server.default_session_minutes * 60),
                    "lan_ips": lan_ips,
                    "trusted_devices": self.server.trusted_devices.count(),
                    "pairing_local_only": True,
                    "public_url": tunnel_snapshot.get("public_url", ""),
                    "public_tunnel_enabled": tunnel_snapshot.get("enabled", False),
                    "public_tunnel_provider": tunnel_snapshot.get("provider", ""),
                    "public_tunnel_status": tunnel_snapshot.get("status", "kapali"),
                    "public_tunnel_error": tunnel_snapshot.get("error", ""),
                    "public_tunnel_restart_count": tunnel_snapshot.get("restart_count", 0),
                    "public_tunnel_last_exit_code": tunnel_snapshot.get("last_exit_code"),
                    "public_tunnel_primary_status": tunnel_snapshot.get("primary_status", ""),
                    "public_tunnel_primary_error": tunnel_snapshot.get("primary_error", ""),
                    "public_tunnel_fallback_status": tunnel_snapshot.get("fallback_status", ""),
                    "public_tunnel_fallback_error": tunnel_snapshot.get("fallback_error", ""),
                    "public_tunnel_fallback_last_exit_code": tunnel_snapshot.get("fallback_last_exit_code"),
                    "wan_pwa_available": bool(tunnel_snapshot.get("public_url")),
                    "telegram_wan_available": bool(_telegram_bot_url()),
                    "active_streams": self.server.active_stream_count(),
                    "max_streams": self.server.max_stream_connections,
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

        if route == "/qr":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/pair")
            self.end_headers()
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
            public_url = self.server.get_public_url(validate=True)
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
            quality, max_width = _parse_stream_params(
                self._query(), self.server.screenshot_quality, self.server.max_width
            )
            try:
                payload = _capture_payload(quality, max_width)
            except CaptureUnavailable as exc:
                _record_capture_error(exc)
                logger.warning("Phone bridge screenshot unavailable: %s", _redact_capture_error(exc))
                self._json_response(
                    _capture_error_payload(exc),
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                    extra_headers=_capture_retry_headers(exc),
                )
                return
            except Exception as exc:
                logger.exception(f"Phone bridge screenshot failed: {exc}")
                self._json_response(
                    {"status": "error", "message": str(exc)},
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return
            payload["session"] = self._build_session_payload(session)
            public_url = self.server.get_public_url(validate=True)
            payload["public_url"] = public_url
            payload["wan_url"] = _build_app_url_from_base(
                public_url,
                handoff_token,
            )
            self._json_response(payload)
            return

        if route == "/api/frame":
            # Long-poll, push-on-change frame stream. The request is held open
            # until the screen differs from the client's last signature (or a
            # short timeout), then returns a single binary JPEG. This removes the
            # fixed polling gap and the base64 overhead of /api/screenshot.
            session, auth_kind = self._require_viewer_session()
            if not session:
                return
            query = self._query()
            since = (query.get("since", [""])[0] or "")[:16]
            quality, max_width = _parse_stream_params(
                query, self.server.screenshot_quality, self.server.max_width
            )

            deadline = time.time() + 15.0
            tick = 0.12
            try:
                while True:
                    raw = None
                    image = None
                    try:
                        raw = _raw_capture_serialized()
                    except Exception as exc:
                        _record_capture_error(exc)
                        raise
                    try:
                        signature = _frame_signature(raw)
                        if signature != since:
                            screen_width, screen_height = raw.size
                            _record_capture_success(screen_width, screen_height)
                            image = _scale_to_width(_draw_cursor(raw), max_width)
                            jpeg = _encode_jpeg(image, quality)
                            self.send_response(HTTPStatus.OK)
                            self.send_header("Content-Type", "image/jpeg")
                            self.send_header("Content-Length", str(len(jpeg)))
                            self.send_header("Cache-Control", "no-store")
                            self.send_header("X-Frame-Sig", signature)
                            self.send_header("X-Frame-Width", str(image.width))
                            self.send_header("X-Frame-Height", str(image.height))
                            self.send_header("X-Screen-Width", str(screen_width))
                            self.send_header("X-Screen-Height", str(screen_height))
                            self.end_headers()
                            try:
                                self.wfile.write(jpeg)
                            except (BrokenPipeError, ConnectionResetError):
                                pass
                            return
                        if time.time() >= deadline:
                            self.send_response(HTTPStatus.NO_CONTENT)
                            self.send_header("X-Frame-Sig", since)
                            self.send_header("Cache-Control", "no-store")
                            self.end_headers()
                            return
                    finally:
                        if image is not None and image is not raw:
                            _close_image(image)
                        if raw is not None:
                            _close_image(raw)
                    time.sleep(tick)
                    if tick < 0.4:
                        # Back off while the screen is static to keep idle CPU low;
                        # an active change still returns on the next capture.
                        tick += 0.04
            except CaptureUnavailable as exc:
                _record_capture_error(exc)
                logger.warning("Phone bridge frame unavailable: %s", _redact_capture_error(exc))
                self._json_response(
                    _capture_error_payload(exc),
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                    extra_headers=_capture_retry_headers(exc),
                )
                return
            except Exception as exc:
                logger.exception(f"Phone bridge frame failed: {exc}")
                self._json_response(
                    {"status": "error", "message": str(exc)},
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                )
                return

        if route == "/api/stream":
            # Persistent push stream: one connection, the server writes
            # length-prefixed (4-byte big-endian) binary JPEG frames as the screen
            # changes (plus a ~1/s keepalive). No per-frame round-trip, so the
            # client sees smooth motion limited only by capture/encode + bandwidth.
            session, auth_kind = self._require_viewer_session()
            if not session:
                return
            try:
                _raise_if_capture_deferred()
            except CaptureUnavailable as exc:
                _record_capture_error(exc)
                logger.warning("Phone bridge stream unavailable: %s", _redact_capture_error(exc))
                self._json_response(
                    _capture_error_payload(exc),
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                    extra_headers=_capture_retry_headers(exc),
                )
                return
            if not self.server.acquire_stream_slot():
                record_runtime_event(
                    "phone_bridge_stream_rejected",
                    active_streams=self.server.active_stream_count(),
                    max_streams=self.server.max_stream_connections,
                )
                self._json_response(
                    {
                        "status": "busy",
                        "message": "Cok fazla aktif goruntu akisi var. Sayfayi yenileyin.",
                    },
                    status=HTTPStatus.TOO_MANY_REQUESTS,
                    extra_headers={"Retry-After": "2"},
                )
                return
            query = self._query()
            quality, max_width = _parse_stream_params(
                query, self.server.screenshot_quality, self.server.max_width
            )
            try:
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "close")
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError, OSError):
                self.server.release_stream_slot()
                return
            record_runtime_event(
                "phone_bridge_stream_started",
                active_streams=self.server.active_stream_count(),
                max_streams=self.server.max_stream_connections,
                quality=quality,
                max_width=max_width,
            )
            last_sig = None
            last_jpeg = None
            last_send = 0.0
            idle = 0
            motion = 0
            was_high_motion = False
            capture_errors = 0
            active_interval = 1.0 / 15.0
            started_at = time.time()
            frame_count = 0
            last_gc_frame = 0
            try:
                while time.time() - started_at < self.server.stream_max_seconds:
                    loop_start = time.time()
                    raw = None
                    image = None
                    try:
                        raw = _raw_capture_serialized()
                        _record_capture_success(*raw.size)
                        capture_errors = 0
                    except CaptureUnavailable as exc:
                        _record_capture_error(exc)
                        logger.warning("Phone bridge stream stopped: %s", _redact_capture_error(exc))
                        break
                    except Exception as exc:
                        _record_capture_error(exc)
                        capture_errors += 1
                        if capture_errors > 10:
                            break  # let the client fall back to the long-poll
                        time.sleep(0.3)
                        continue
                    try:
                        signature = _frame_signature(raw)
                        changed = signature != last_sig
                        if changed:
                            motion = min(motion + 2, 12)
                            idle = 0
                        else:
                            motion = max(motion - 1, 0)
                            idle += 1
                        high_motion = motion >= 5
                        just_settled = was_high_motion and not high_motion
                        was_high_motion = high_motion
                        now = time.time()
                        if changed or just_settled:
                            # While the screen is actively moving (scrolling, video), send
                            # smaller, lower-quality frames so they don't saturate the
                            # uplink/tunnel and stutter; restore full detail the instant it
                            # settles. Pixels dominate bandwidth, so trim width too.
                            if high_motion:
                                encode_quality = max(28, quality - 24)
                                encode_width = max(720, (max_width * 7) // 10)
                            else:
                                encode_quality = quality
                                encode_width = max_width
                            image = _scale_to_width(_draw_cursor(raw), encode_width)
                            last_jpeg = _encode_jpeg(image, encode_quality)
                            last_sig = signature
                            frame_count += 1
                            try:
                                self.wfile.write(len(last_jpeg).to_bytes(4, "big"))
                                self.wfile.write(last_jpeg)
                                self.wfile.flush()
                            except (BrokenPipeError, ConnectionResetError, OSError):
                                break
                            last_send = now
                        elif now - last_send >= 1.0:
                            # Tiny zero-length heartbeat keeps the connection warm and
                            # lets the client confirm liveness without resending a frame.
                            try:
                                self.wfile.write((0).to_bytes(4, "big"))
                                self.wfile.flush()
                            except (BrokenPipeError, ConnectionResetError, OSError):
                                break
                            last_send = now
                    finally:
                        if image is not None and image is not raw:
                            _close_image(image)
                        if raw is not None:
                            _close_image(raw)
                    if (
                        frame_count
                        and frame_count != last_gc_frame
                        and frame_count % self.server.stream_gc_every_frames == 0
                    ):
                        gc.collect()
                        last_gc_frame = frame_count
                    # Pace fast while the screen is moving; back off when static.
                    interval = active_interval if idle < 12 else 0.25
                    elapsed = time.time() - loop_start
                    if elapsed < interval:
                        time.sleep(interval - elapsed)
            except Exception as exc:
                logger.debug(f"Phone bridge stream ended: {exc}")
            finally:
                self.server.release_stream_slot()
                record_runtime_event(
                    "phone_bridge_stream_ended",
                    active_streams=self.server.active_stream_count(),
                    frames=frame_count,
                    duration_seconds=round(time.time() - started_at, 2),
                )
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
            screen = _get_screen_metrics()
            capture = _capture_health(screen)
            public_url = self.server.get_public_url(validate=True)
            self._json_response(
                {
                    "status": "ok",
                    "screen_width": screen["width"],
                    "screen_height": screen["height"],
                    "screen_available": screen["available"],
                    "capture_available": capture["capture_available"],
                    "capture_error": capture["capture_error"],
                    "capture_retry_after": capture["capture_retry_after"],
                    "poll_ms": self.server.poll_ms,
                    "quality": self.server.screenshot_quality,
                    "max_width": self.server.max_width,
                    "auth_kind": auth_kind,
                    "public_url": public_url,
                    "wan_url": _build_app_url_from_base(
                        public_url,
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
            minutes = self._coerce_minutes(payload)
            if minutes is None:
                return
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
            minutes = self._coerce_minutes(payload)
            if minutes is None:
                return
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
        if action_type not in ("click", "scroll", "key", "type", "refresh"):
            self._json_response(
                {
                    "status": "bad_request",
                    "message": f"Unknown action: {action_type}",
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        # Idempotency: a retried command carries the same request_id. If it has
        # already been applied (the client never saw our first response), replay
        # the stored result instead of executing the desktop action again.
        request_id = str(payload.get("request_id", "")).strip()[:128]
        cached_response, is_owner = self.server.action_dedup.acquire(request_id)
        if cached_response is not None:
            self._json_response(cached_response)
            return

        try:
            # Parse delay inside the try so the except path below releases the
            # in-flight reservation (action_dedup.abort) on bad input; a
            # malformed value just falls back to the default instead of leaking.
            try:
                delay = max(0.0, min(2.0, float(payload.get("delay", 0.15))))
            except (TypeError, ValueError):
                delay = 0.15

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
                if not _perform_keypress(payload.get("keys", "")):
                    raise RuntimeError("Klavye kisayolu uygulanamadi. Accessibility iznini kontrol edin.")
            elif action_type == "type":
                if not _perform_type(
                    payload.get("text", ""),
                    sensitive=bool(payload.get("sensitive", False)),
                    focus=payload.get("focus"),
                ):
                    raise RuntimeError("Metin yazilamadi. Accessibility iznini kontrol edin.")
            elif action_type == "refresh":
                pass

            if delay:
                time.sleep(delay)

            refreshed_session = self.server.session_links.consume(session["token"]) or session
            handoff_token = (
                session.get("token", "")
                if auth_kind == "link"
                else self.server.startup_session.get("token", "")
            )
            public_url = self.server.get_public_url(validate=True)
            wan_url = _build_app_url_from_base(public_url, handoff_token)
            # When the client drives a live frame stream it already shows the
            # result, so it asks us to skip the (heavier) action screenshot.
            if payload.get("no_screenshot"):
                screenshot_payload = None
            else:
                screenshot_payload = _capture_payload(
                    self.server.screenshot_quality,
                    self.server.max_width,
                )
                screenshot_payload["public_url"] = public_url
                screenshot_payload["wan_url"] = wan_url
            response_body = {
                "status": "ok",
                "action": action_type,
                "request_id": request_id,
                "session": self._build_session_payload(refreshed_session),
                "public_url": public_url,
                "wan_url": wan_url,
                "screenshot": screenshot_payload,
            }
        except Exception as exc:
            logger.exception(f"Phone bridge action failed: {exc}")
            if is_owner:
                self.server.action_dedup.abort(request_id)
            self._json_response(
                {"status": "error", "message": str(exc)},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        # Cache the result *before* writing it out so that even if the socket
        # write fails the action is never re-applied on the client's retry.
        if is_owner:
            self.server.action_dedup.complete(request_id, response_body)
        self._json_response(response_body)


class PhoneBridgeServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer.server_bind() calls socket.getfqdn(), which can hang on
        # macOS mDNS reverse lookups before the bridge even starts listening.
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host or LOCAL_HOST
        self.server_port = port

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
        self.action_dedup = ActionDedup()
        self.max_stream_connections = DEFAULT_STREAM_MAX_CONNECTIONS
        self.stream_max_seconds = DEFAULT_STREAM_MAX_SECONDS
        self.stream_gc_every_frames = DEFAULT_STREAM_GC_EVERY_FRAMES
        self._stream_slots = threading.BoundedSemaphore(self.max_stream_connections)
        self._stream_count_lock = threading.Lock()
        self._active_streams = 0
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

    def acquire_stream_slot(self):
        acquired = self._stream_slots.acquire(blocking=False)
        if not acquired:
            return False
        with self._stream_count_lock:
            self._active_streams += 1
        return True

    def release_stream_slot(self):
        with self._stream_count_lock:
            if self._active_streams <= 0:
                return
            self._active_streams -= 1
        try:
            self._stream_slots.release()
        except ValueError:
            pass

    def active_stream_count(self):
        with self._stream_count_lock:
            return self._active_streams

    def get_public_url(self, *, validate=True):
        if not self.public_tunnel:
            return ""
        return self.public_tunnel.get_public_url(validate=validate)

    def public_tunnel_snapshot(self, *, validate=True):
        if not self.public_tunnel:
            return {
                "enabled": False,
                "status": "kapali",
                "public_url": "",
                "error": "",
            }
        return self.public_tunnel.snapshot(validate=validate)


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
    install_diagnostics_hooks("phone_bridge")
    server = PhoneBridgeServer(
        (bind, port),
        PhoneBridgeHandler,
        admin_token=admin_token,
        screenshot_quality=max(20, min(95, quality)),
        max_width=max(640, max_width),
        poll_ms=max(500, poll_ms),
        default_session_minutes=int(session_minutes),
    )
    start_diagnostics_heartbeat("phone_bridge", extra_snapshot=lambda: _diagnostic_snapshot(server))
    record_runtime_event("phone_bridge_server_created", bind=bind, port=port)

    lan_ips = _get_local_ipv4_candidates()
    startup_session = server.startup_session
    lan_urls = [
        _build_app_url(ip, port, startup_session["token"])
        for ip in lan_ips
    ]
    lan_url = lan_urls[0] if lan_urls else _build_app_url(_get_local_ip(), port, startup_session["token"])
    localhost_url = _build_app_url(LOCAL_HOST, port, startup_session["token"])
    server.public_tunnel = start_public_tunnel(
        f"http://{LOCAL_HOST}:{port}",
        mode=public_tunnel,
    )
    _start_keep_awake()
    public_url = server.get_public_url(validate=True)
    wan_url = _build_app_url_from_base(public_url, startup_session["token"])

    logger.info("AgentCockpit phone bridge basladi")
    record_runtime_event(
        "phone_bridge_ready",
        bind=bind,
        port=port,
        lan_ip_count=len(lan_ips),
        public_tunnel_status=server.public_tunnel_snapshot(validate=False).get("status", ""),
        capture=_diagnostic_snapshot(server).get("capture"),
    )
    logger.info(f"Phone app (LAN): {_redact_url_for_log(lan_url)}")
    if wan_url:
        logger.info(f"Phone app (WAN): {_redact_url_for_log(wan_url)}")
    logger.info(f"Phone app (Localhost): {_redact_url_for_log(localhost_url)}")
    logger.info(f"Phone installation id: {get_installation_id()}")
    logger.info("Phone admin token: <redacted>")
    logger.info(f"Phone runtime token file: {get_runtime_paths()['admin_token_file']}")
    print("AgentCockpit phone bridge hazir.")
    print(f"Pairing Dashboard (this PC): http://{LOCAL_HOST}:{port}/pair")
    print(f"LAN URL ({startup_session['expires_in_text']}): {_stdout_secret(lan_url)}")
    if len(lan_urls) > 1:
        for index, alt_url in enumerate(lan_urls[1:], start=2):
            print(f"LAN URL {index} ({startup_session['expires_in_text']}): {_stdout_secret(alt_url)}")
    if wan_url:
        print(f"WAN URL ({startup_session['expires_in_text']}): {_stdout_secret(wan_url)}")
    else:
        tunnel_snapshot = server.public_tunnel_snapshot()
        if tunnel_snapshot.get("enabled"):
            print(
                "WAN URL: hazirlaniyor veya kapali "
                f"({tunnel_snapshot.get('status', 'bilinmiyor')})"
            )
    print(f"Local URL ({startup_session['expires_in_text']}): {_stdout_secret(localhost_url)}")
    print(f"Installation id: {get_installation_id()}")
    print(f"Admin token: {_stdout_admin_token(admin_token)}")
    print(f"Token file: {get_runtime_paths()['admin_token_file']}")
    print(
        "Not: Varsayilan telefon linki sinirsizdir. Yeni link uretmek icin /api/session-links endpoint'ini admin token ile cagirabilirsin."
    )

    # Translate SIGTERM (how launcher.py / runner.sh / kill stop us) into the
    # same clean shutdown as Ctrl-C, so the public tunnel child is always
    # stopped instead of being orphaned as a live internet-facing tunnel.
    def _handle_sigterm(signum, frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, _handle_sigterm)
    except (ValueError, OSError):
        # Not running in the main thread / signal unsupported on this platform.
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nKapatiliyor...")
    finally:
        record_runtime_event("phone_bridge_stopping")
        if server.public_tunnel:
            server.public_tunnel.stop()
        server.server_close()
        record_runtime_event("phone_bridge_stopped")


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

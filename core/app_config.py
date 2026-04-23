import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


DEFAULTS = {
    "AGENTCOCKPIT_LOCAL_HOST": "127.0.0.1",
    "PHONE_BIND": "0.0.0.0",
    "PHONE_PORT": "8765",
    "PHONE_SCREENSHOT_QUALITY": "55",
    "PHONE_SCREENSHOT_MAX_WIDTH": "1600",
    "PHONE_POLL_MS": "1400",
    "PHONE_SESSION_MINUTES": "0",
    "PHONE_PUBLIC_TUNNEL": "auto",
    "PHONE_PUBLIC_TUNNEL_DOWNLOAD": "1",
    "PHONE_PUBLIC_TUNNEL_WAIT_SEC": "1.5",
    "PHONE_BRIDGE_TIMEOUT_SEC": "6",
    "PHONE_WAN_INTERVAL_SEC": "1.4",
    "PHONE_WAN_MAX_WIDTH": "1280",
    "PHONE_WAN_QUALITY": "45",
    "PHONE_WAN_CHANGE_THRESHOLD": "5.0",
    "PHONE_WAN_IDLE_REFRESH_SEC": "20",
    "TELEGRAM_SETUP_HOST": "127.0.0.1",
}


def get_str(name, default=None):
    fallback = DEFAULTS.get(name) if default is None else default
    return (os.getenv(name) or fallback or "").strip()


def get_int(name, default=None):
    raw = get_str(name, default)
    return int(raw)


def get_float(name, default=None):
    raw = get_str(name, default)
    return float(raw)

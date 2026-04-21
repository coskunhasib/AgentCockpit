import os
import secrets
import shutil
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
LEGACY_RUNTIME_DIR = ROOT_DIR / "runtime"
LEGACY_V2_RUNTIME_DIR = ROOT_DIR / "v2" / "runtime"
LEGACY_ADMIN_TOKEN_FILE = LEGACY_RUNTIME_DIR / "phone_admin_token.txt"
LEGACY_INSTALL_ID_FILE = LEGACY_RUNTIME_DIR / "install_id.txt"


def _default_runtime_root():
    custom = (os.getenv("AGENTCOCKPIT_HOME") or "").strip()
    if custom:
        return Path(custom).expanduser()

    if os.name == "nt":
        local_appdata = (os.getenv("LOCALAPPDATA") or "").strip()
        if local_appdata:
            return Path(local_appdata) / "AgentCockpit"

    return Path.home() / ".agentcockpit"


RUNTIME_ROOT = _default_runtime_root()
RUNTIME_DIR = RUNTIME_ROOT / "runtime"
LEGACY_APP_RUNTIME_DIR = RUNTIME_ROOT / "v2"
ADMIN_TOKEN_FILE = RUNTIME_DIR / "phone_admin_token.txt"
INSTALL_ID_FILE = RUNTIME_DIR / "install_id.txt"
TRUSTED_DEVICES_FILE = RUNTIME_DIR / "trusted_devices.json"
CLOUDFLARED_BIN_DIR = RUNTIME_DIR / "bin"
CLOUDFLARED_URL_FILE = RUNTIME_DIR / "public_tunnel_url.txt"
PHONE_NOTIFICATION_STATE_FILE = RUNTIME_DIR / "phone_notification_state.json"


def _read_text(path):
    try:
        value = path.read_text(encoding="utf-8").strip()
        return value or None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _ensure_runtime_dir():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def _read_with_legacy(primary, *legacy_paths):
    value = _read_text(primary)
    if value:
        return value
    for legacy in legacy_paths:
        value = _read_text(legacy)
        if value:
            return value
    return None


def _copy_file_if_missing(source, target):
    if target.exists() or not source.exists():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    except Exception:
        pass


def _copy_dir_if_missing(source, target):
    if target.exists() or not source.exists():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    except Exception:
        pass


def _migrate_runtime_files():
    legacy_dirs = [LEGACY_APP_RUNTIME_DIR, LEGACY_RUNTIME_DIR, LEGACY_V2_RUNTIME_DIR]
    filenames = [
        "phone_admin_token.txt",
        "install_id.txt",
        "trusted_devices.json",
        "public_tunnel_url.txt",
        "phone_notification_state.json",
    ]
    for legacy_dir in legacy_dirs:
        for filename in filenames:
            _copy_file_if_missing(legacy_dir / filename, RUNTIME_DIR / filename)
        _copy_dir_if_missing(legacy_dir / "bin", CLOUDFLARED_BIN_DIR)


def get_installation_id():
    env_value = (os.getenv("PHONE_INSTALLATION_ID") or "").strip()
    if env_value:
        return env_value

    existing = _read_with_legacy(
        INSTALL_ID_FILE,
        LEGACY_INSTALL_ID_FILE,
        LEGACY_V2_RUNTIME_DIR / "install_id.txt",
        LEGACY_APP_RUNTIME_DIR / "install_id.txt",
    )
    if existing:
        _ensure_runtime_dir()
        INSTALL_ID_FILE.write_text(existing, encoding="utf-8")
        return existing

    _ensure_runtime_dir()
    generated = secrets.token_hex(8)
    INSTALL_ID_FILE.write_text(generated, encoding="utf-8")
    return generated


def get_shared_admin_token():
    env_value = (os.getenv("PHONE_ADMIN_TOKEN") or os.getenv("PHONE_TOKEN") or "").strip()
    if env_value:
        return env_value

    install_prefix = f"acp_{get_installation_id()[:8]}_"
    existing = _read_with_legacy(
        ADMIN_TOKEN_FILE,
        LEGACY_ADMIN_TOKEN_FILE,
        LEGACY_V2_RUNTIME_DIR / "phone_admin_token.txt",
        LEGACY_APP_RUNTIME_DIR / "phone_admin_token.txt",
    )
    if existing:
        _ensure_runtime_dir()
        if existing.startswith(install_prefix):
            ADMIN_TOKEN_FILE.write_text(existing, encoding="utf-8")
            return existing

    _ensure_runtime_dir()
    generated = f"{install_prefix}{secrets.token_urlsafe(24)}"
    ADMIN_TOKEN_FILE.write_text(generated, encoding="utf-8")
    return generated


def get_runtime_paths():
    return {
        "runtime_dir": str(RUNTIME_DIR),
        "admin_token_file": str(ADMIN_TOKEN_FILE),
        "install_id_file": str(INSTALL_ID_FILE),
        "trusted_devices_file": str(TRUSTED_DEVICES_FILE),
        "cloudflared_bin_dir": str(CLOUDFLARED_BIN_DIR),
        "public_tunnel_url_file": str(CLOUDFLARED_URL_FILE),
        "phone_notification_state_file": str(PHONE_NOTIFICATION_STATE_FILE),
        "legacy_runtime_dir": str(LEGACY_RUNTIME_DIR),
        "legacy_app_runtime_dir": str(LEGACY_APP_RUNTIME_DIR),
    }


_migrate_runtime_files()

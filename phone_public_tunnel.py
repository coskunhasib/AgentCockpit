import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from core.logger import get_logger
from phone_runtime_config import CLOUDFLARED_BIN_DIR, CLOUDFLARED_URL_FILE


logger = get_logger("phone_public_tunnel")

TUNNEL_URL_RE = re.compile(r"https://[-a-zA-Z0-9.]+\.trycloudflare\.com")


def default_tunnel_mode():
    return os.getenv("PHONE_PUBLIC_TUNNEL", "auto").strip().lower()


def default_download_enabled():
    return os.getenv("PHONE_PUBLIC_TUNNEL_DOWNLOAD", "1").strip().lower()


def tunnel_enabled(value=None):
    mode = (default_tunnel_mode() if value is None else str(value)).strip().lower()
    return mode not in {"", "0", "false", "no", "off", "disabled", "none"}


def auto_download_enabled(value=None):
    raw = default_download_enabled() if value is None else str(value)
    return raw.strip().lower() not in {"", "0", "false", "no", "off", "disabled"}


def extract_tunnel_url(text):
    match = TUNNEL_URL_RE.search(text or "")
    return match.group(0) if match else ""


def _machine_arch(machine=None):
    value = (machine or platform.machine() or "").strip().lower()
    if value in {"amd64", "x86_64"}:
        return "amd64"
    if value in {"arm64", "aarch64"}:
        return "arm64"
    if value in {"x86", "i386", "i686"}:
        return "386"
    return value


def cloudflared_download_url(system=None, machine=None):
    system_name = (system or platform.system()).strip().lower()
    arch = _machine_arch(machine)
    base = "https://github.com/cloudflare/cloudflared/releases/latest/download"

    if system_name == "windows" and arch in {"amd64", "386"}:
        return f"{base}/cloudflared-windows-{arch}.exe"
    if system_name == "linux" and arch in {"amd64", "arm64", "386"}:
        return f"{base}/cloudflared-linux-{arch}"
    if system_name == "darwin" and arch in {"amd64", "arm64"}:
        return f"{base}/cloudflared-darwin-{arch}.tgz"
    return ""


def _local_cloudflared_path():
    suffix = ".exe" if os.name == "nt" else ""
    return CLOUDFLARED_BIN_DIR / f"cloudflared{suffix}"


def find_cloudflared():
    env_path = (os.getenv("CLOUDFLARED_EXE") or "").strip()
    if env_path and Path(env_path).exists():
        return Path(env_path)

    path_value = shutil.which("cloudflared")
    if path_value:
        return Path(path_value)

    local_path = _local_cloudflared_path()
    if local_path.exists():
        return local_path
    return None


def _make_executable(path):
    if os.name == "nt":
        return
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _download_cloudflared():
    download_url = cloudflared_download_url()
    if not download_url:
        raise RuntimeError(
            f"Bu platform icin cloudflared otomatik indirme desteklenmiyor: "
            f"{platform.system()} {platform.machine()}"
        )

    CLOUDFLARED_BIN_DIR.mkdir(parents=True, exist_ok=True)
    target = _local_cloudflared_path()
    logger.info(f"cloudflared indiriliyor: {download_url}")

    with tempfile.TemporaryDirectory(prefix="agentcockpit-cloudflared-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        archive_path = tmp_path / Path(download_url).name
        urllib.request.urlretrieve(download_url, archive_path)

        if archive_path.suffix == ".tgz":
            with tarfile.open(archive_path, "r:gz") as archive:
                member = next(
                    (
                        item
                        for item in archive.getmembers()
                        if Path(item.name).name == "cloudflared" and item.isfile()
                    ),
                    None,
                )
                if member is None:
                    raise RuntimeError("cloudflared arşivi icinde binary bulunamadi.")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise RuntimeError("cloudflared arşivi okunamadi.")
                target.write_bytes(extracted.read())
        else:
            shutil.copyfile(archive_path, target)

    _make_executable(target)
    return target


def ensure_cloudflared(*, allow_download=True):
    existing = find_cloudflared()
    if existing:
        return existing
    if not allow_download:
        return None
    return _download_cloudflared()


def write_public_url(url):
    CLOUDFLARED_URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLOUDFLARED_URL_FILE.write_text((url or "").strip(), encoding="utf-8")


def clear_public_url():
    try:
        CLOUDFLARED_URL_FILE.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        logger.debug("Public tunnel URL dosyasi temizlenemedi.", exc_info=True)


class QuickTunnel:
    def __init__(self, target_url, *, mode="auto", allow_download=True):
        self.target_url = target_url.rstrip("/")
        self.mode = mode
        self.allow_download = allow_download
        self.process = None
        self.public_url = ""
        self.status = "kapali"
        self.error = ""
        self.restart_count = 0
        self.last_exit_code = None
        self.restart_delay = max(
            1.0, float(os.getenv("PHONE_PUBLIC_TUNNEL_RESTART_DELAY_SEC", "3"))
        )
        self.max_restarts = max(
            0, int(os.getenv("PHONE_PUBLIC_TUNNEL_MAX_RESTARTS", "0"))
        )
        self._binary = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._url_event = threading.Event()
        self._reader_thread = None
        self._watchdog_thread = None

    def start(self):
        if not tunnel_enabled(self.mode):
            self.status = "kapali"
            clear_public_url()
            return self

        try:
            self._binary = ensure_cloudflared(allow_download=self.allow_download)
            if not self._binary:
                self.status = "kapali"
                self.error = "cloudflared bulunamadi"
                logger.warning(self.error)
                clear_public_url()
                return self

            self._launch_process()
            self._watchdog_thread = threading.Thread(
                target=self._watchdog,
                name="agentcockpit-public-tunnel-watchdog",
                daemon=True,
            )
            self._watchdog_thread.start()
        except Exception as exc:
            self.status = "hata"
            self.error = str(exc)
            logger.warning(f"Public tunnel baslatilamadi: {exc}")
            clear_public_url()
        return self

    def _launch_process(self):
        if not self._binary:
            raise RuntimeError("cloudflared binary hazir degil")

        command = [
            str(self._binary),
            "tunnel",
            "--url",
            self.target_url,
            "--no-autoupdate",
        ]
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        with self._lock:
            self.process = process
            self.public_url = ""
            self.status = "baslatiliyor"
            self.error = ""
            self.last_exit_code = None
            self._url_event.clear()
            clear_public_url()

        self._reader_thread = threading.Thread(
            target=self._read_output,
            args=(process,),
            name="agentcockpit-public-tunnel-reader",
            daemon=True,
        )
        self._reader_thread.start()

    def _read_output(self, process):
        if not process or not process.stdout:
            return

        for raw_line in process.stdout:
            line = raw_line.strip()
            if line:
                logger.info(f"cloudflared: {line}")
            url = extract_tunnel_url(line)
            if url:
                with self._lock:
                    if process is not self.process or self._stop_event.is_set():
                        continue
                    self.public_url = url.rstrip("/")
                    self.status = "hazir"
                    self.error = ""
                write_public_url(self.public_url)
                self._url_event.set()

        exit_code = process.poll()
        if exit_code is None:
            try:
                exit_code = process.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                exit_code = None
        with self._lock:
            if process is not self.process:
                return
            self.last_exit_code = exit_code
            self.public_url = ""
            self._url_event.clear()
            clear_public_url()
            if self._stop_event.is_set():
                self.status = "kapali"
                return
            self.status = "yeniden_baslatiliyor"
            self.error = f"cloudflared cikti: {exit_code}"

    def _watchdog(self):
        while not self._stop_event.wait(self.restart_delay):
            if not tunnel_enabled(self.mode):
                return
            process = self.process
            if process and process.poll() is None:
                continue
            if self.max_restarts and self.restart_count >= self.max_restarts:
                with self._lock:
                    self.status = "hata"
                    self.error = "public tunnel yeniden baslatma limiti doldu"
                return
            try:
                self.restart_count += 1
                logger.warning(
                    f"Public tunnel yeniden baslatiliyor (deneme {self.restart_count})"
                )
                self._launch_process()
            except Exception as exc:
                with self._lock:
                    self.status = "hata"
                    self.error = str(exc)
                logger.warning(f"Public tunnel yeniden baslatilamadi: {exc}")

    def wait_for_url(self, timeout=0):
        if timeout and not self.public_url:
            self._url_event.wait(timeout)
        return self.public_url

    def snapshot(self):
        if self.public_url and self.process and self.process.poll() is None:
            status = "hazir"
        elif self.status == "baslatiliyor" and self.process and self.process.poll() is not None:
            status = "yeniden_baslatiliyor"
        else:
            status = self.status
        return {
            "enabled": tunnel_enabled(self.mode),
            "status": status,
            "public_url": self.public_url,
            "error": self.error,
            "restart_count": self.restart_count,
            "last_exit_code": self.last_exit_code,
        }

    def stop(self):
        self._stop_event.set()
        clear_public_url()
        if not self.process or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)


def start_public_tunnel(target_url, *, mode=None, allow_download=None):
    tunnel = QuickTunnel(
        target_url,
        mode=default_tunnel_mode() if mode is None else mode,
        allow_download=auto_download_enabled() if allow_download is None else bool(allow_download),
    )
    tunnel.start()
    # Quick Tunnel genelde 2-5 saniyede URL verir; server yine de hemen servis vermeye devam eder.
    tunnel.wait_for_url(timeout=float(os.getenv("PHONE_PUBLIC_TUNNEL_WAIT_SEC", "1.5")))
    return tunnel

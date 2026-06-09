import os
import ipaddress
import platform
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

from core.app_config import get_float, get_int, get_str
from core.logger import get_logger
from phone_runtime_config import CLOUDFLARED_BIN_DIR, CLOUDFLARED_URL_FILE


logger = get_logger("phone_public_tunnel")

TUNNEL_URL_RE = re.compile(r"https://[-a-zA-Z0-9.]+\.trycloudflare\.com")
IP_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9:])(?:\d{1,3}(?:\.\d{1,3}){3}|[0-9A-Fa-f:]{3,})(?![A-Za-z0-9:])")


def default_tunnel_mode():
    return get_str("PHONE_PUBLIC_TUNNEL").lower()


def default_download_enabled():
    return get_str("PHONE_PUBLIC_TUNNEL_DOWNLOAD").lower()


def tunnel_enabled(value=None):
    mode = (default_tunnel_mode() if value is None else str(value)).strip().lower()
    return mode not in {"", "0", "false", "no", "off", "disabled", "none"}


def auto_download_enabled(value=None):
    raw = default_download_enabled() if value is None else str(value)
    return raw.strip().lower() not in {"", "0", "false", "no", "off", "disabled"}


def extract_tunnel_url(text):
    match = TUNNEL_URL_RE.search(text or "")
    return match.group(0) if match else ""


def _public_ip_tokens(text):
    ips = []
    seen = set()
    for match in IP_TOKEN_RE.finditer(text or ""):
        token = match.group(0).strip("[]")
        try:
            ip = ipaddress.ip_address(token)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_private or ip.is_unspecified:
            continue
        value = str(ip)
        if value not in seen:
            seen.add(value)
            ips.append(value)
    return ips


def _resolve_host_with_dns_tools(hostname):
    if not hostname:
        return []
    commands = [
        ["nslookup", hostname],
    ]
    if shutil.which("dig"):
        commands.append(["dig", "+short", hostname])
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        ips = _public_ip_tokens(f"{result.stdout}\n{result.stderr}")
        if ips:
            return ips
    return []


def _https_get_via_resolved_ip(url, ip, *, timeout=2.5):
    parsed = urllib.parse.urlsplit(url)
    hostname = parsed.hostname
    if not hostname:
        return False, "host yok"
    port = parsed.port or 443
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    try:
        raw_sock = socket.create_connection((ip, port), timeout=timeout)
        with raw_sock:
            context = ssl.create_default_context()
            with context.wrap_socket(raw_sock, server_hostname=hostname) as sock:
                request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {hostname}\r\n"
                    "User-Agent: AgentCockpit/2.0\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                sock.settimeout(timeout)
                sock.sendall(request.encode("ascii"))
                data = sock.recv(256)
        status_line = data.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        parts = status_line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            status = int(parts[1])
            return 200 <= status < 300, f"HTTP {status}"
        return False, f"gecersiz HTTP yaniti: {status_line}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def validate_public_tunnel_url(url, *, timeout=2.5):
    health_url = f"{url.rstrip('/')}/_agentcockpit/tunnel-check"
    request = urllib.request.Request(
        health_url,
        headers={"User-Agent": "AgentCockpit/2.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            ok = 200 <= response.status < 300
            return ok, "" if ok else f"HTTP {response.status}"
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        primary_error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        primary_error = f"{type(exc).__name__}: {exc}"

    hostname = urllib.parse.urlsplit(health_url).hostname or ""
    if hostname.endswith(".trycloudflare.com"):
        ips = _resolve_host_with_dns_tools(hostname)
        for ip in ips[:4]:
            ok, fallback_error = _https_get_via_resolved_ip(
                health_url,
                ip,
                timeout=timeout,
            )
            if ok:
                logger.info(
                    "Public tunnel normal DNS dogrulamasi basarisizdi; "
                    f"DNS fallback ile dogrulandi: {hostname} -> {ip}"
                )
                return True, ""
            primary_error = f"{primary_error}; fallback {ip}: {fallback_error}"
        if not ips:
            primary_error = f"{primary_error}; DNS fallback IP bulamadi"

    return False, primary_error


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
    env_path = get_str("CLOUDFLARED_EXE")
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


def cloudflared_process_env():
    env = os.environ.copy()
    if sys.platform == "darwin":
        # cloudflared is a Go binary. In some non-interactive macOS sessions the
        # default SystemConfiguration DNS lookup can be empty; forcing Go DNS is
        # available as an opt-in escape hatch, but it is not safe as a default on
        # every macOS trust-store setup.
        force_go_dns = get_str("CLOUDFLARED_FORCE_GO_DNS", "0").lower()
        if force_go_dns in {"1", "true", "yes", "on"}:
            godebug = env.get("GODEBUG", "")
            parts = [part for part in godebug.split(",") if part]
            if not any(part.startswith("netdns=") for part in parts):
                parts.append("netdns=go")
            env["GODEBUG"] = ",".join(parts)
    return env


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
        self.restart_delay = max(1.0, get_float("PHONE_PUBLIC_TUNNEL_RESTART_DELAY_SEC", "3"))
        self.restart_delay_max = max(
            self.restart_delay,
            get_float("PHONE_PUBLIC_TUNNEL_RESTART_MAX_DELAY_SEC", "60"),
        )
        self.max_restarts = max(0, get_int("PHONE_PUBLIC_TUNNEL_MAX_RESTARTS"))
        self._binary = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._url_event = threading.Event()
        self._reader_thread = None
        self._watchdog_thread = None
        self._validation_checked_at = 0.0
        self._validation_ok = False
        self._validation_failures = 0
        self._url_seen_at = 0.0

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
            env=cloudflared_process_env(),
        )
        with self._lock:
            self.process = process
            self.public_url = ""
            self.status = "baslatiliyor"
            self.error = ""
            self.last_exit_code = None
            self._validation_checked_at = 0.0
            self._validation_ok = False
            self._validation_failures = 0
            self._url_seen_at = 0.0
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
                    self._validation_checked_at = 0.0
                    self._validation_ok = False
                    self._validation_failures = 0
                    self._url_seen_at = time.monotonic()
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
            self._validation_checked_at = 0.0
            self._validation_ok = False
            self._validation_failures = 0
            self._url_seen_at = 0.0
            self._url_event.clear()
            clear_public_url()
            if self._stop_event.is_set():
                self.status = "kapali"
                return
            self.status = "yeniden_baslatiliyor"
            self.error = f"cloudflared cikti: {exit_code}"

    def _watchdog(self):
        delay = self.restart_delay
        while not self._stop_event.wait(delay):
            if not tunnel_enabled(self.mode):
                return
            process = self.process
            if process and process.poll() is None:
                delay = self.restart_delay
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
                delay = min(self.restart_delay_max, max(self.restart_delay, delay * 2))
            except Exception as exc:
                with self._lock:
                    self.status = "hata"
                    self.error = str(exc)
                logger.warning(f"Public tunnel yeniden baslatilamadi: {exc}")
                delay = min(self.restart_delay_max, max(self.restart_delay, delay * 2))

    def wait_for_url(self, timeout=0):
        if timeout and not self.public_url:
            self._url_event.wait(timeout)
        return self.public_url

    def get_public_url(self, *, validate=True):
        with self._lock:
            url = self.public_url
            process = self.process
            checked_at = self._validation_checked_at
            validation_ok = self._validation_ok

        if not url:
            return ""

        if process and process.poll() is not None:
            return ""

        if not validate:
            return url

        now = time.monotonic()
        cache_ttl = max(1.0, get_float("PHONE_PUBLIC_TUNNEL_VALIDATE_CACHE_SEC"))
        if validation_ok and (now - checked_at) < cache_ttl:
            return url
        if (not validation_ok) and checked_at and (now - checked_at) < cache_ttl:
            return ""

        ok, validation_error = validate_public_tunnel_url(url, timeout=2.5)

        restart_process = None
        with self._lock:
            if url == self.public_url:
                self._validation_checked_at = now
                self._validation_ok = ok
                if ok:
                    self._validation_failures = 0
                    self.status = "hazir"
                    self.error = ""
                else:
                    self.status = "dogrulaniyor"
                    self.error = f"public tunnel dogrulanamadi: {validation_error}"
                    grace_sec = max(0.0, get_float("PHONE_PUBLIC_TUNNEL_VALIDATE_GRACE_SEC"))
                    max_failures = max(
                        1,
                        get_int("PHONE_PUBLIC_TUNNEL_VALIDATE_FAILURES_BEFORE_RESTART"),
                    )
                    url_age = now - self._url_seen_at if self._url_seen_at else 0.0
                    if url_age >= grace_sec:
                        self._validation_failures += 1
                        if self._validation_failures >= max_failures:
                            restart_process = self.process
                            self.public_url = ""
                            self.status = "yeniden_baslatiliyor"
                            self.error = f"public tunnel erisilemiyor: {url}"
                            self._validation_checked_at = 0.0
                            self._validation_failures = 0
                            self._url_event.clear()

        if restart_process:
            clear_public_url()
            logger.warning(
                f"Public tunnel URL dogrulanamadi; cloudflared yeniden baslatiliyor: {url}"
            )
            self._terminate_unreachable_process(restart_process)

        return url if ok else ""

    def _terminate_unreachable_process(self, process):
        if not process or process.poll() is not None:
            return

        def terminate():
            try:
                process.terminate()
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    logger.debug("Public tunnel kill islemi tamamlanamadi.", exc_info=True)
            except Exception:
                logger.debug("Public tunnel terminate islemi tamamlanamadi.", exc_info=True)

        threading.Thread(
            target=terminate,
            name="agentcockpit-public-tunnel-restart",
            daemon=True,
        ).start()

    def snapshot(self, *, validate=True):
        public_url = self.get_public_url(validate=validate)
        if public_url and self.process and self.process.poll() is None:
            status = "hazir"
        elif self.status == "baslatiliyor" and self.process and self.process.poll() is not None:
            status = "yeniden_baslatiliyor"
        else:
            status = self.status
        return {
            "enabled": tunnel_enabled(self.mode),
            "status": status,
            "public_url": public_url,
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
    tunnel.wait_for_url(timeout=get_float("PHONE_PUBLIC_TUNNEL_WAIT_SEC"))
    return tunnel

import asyncio
import faulthandler
import json
import os
import platform
import re
import shutil
import signal
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from telegram import Bot

try:
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = str(PROJECT_ROOT / "logs")
CRASH_DIR = str(PROJECT_ROOT / "logs/crashes")
DIAGNOSTIC_DIR = str(PROJECT_ROOT / "logs/diagnostics")
APP_LOG_FILE = os.path.join(LOG_DIR, f"app_{os.getpid()}.log")
EVENT_LOG_FILE = os.path.join(DIAGNOSTIC_DIR, f"events_{os.getpid()}.jsonl")

_STARTED_AT = time.time()
_PROCESS_NAME = "agentcockpit"
_HOOKS_INSTALLED = False
_HEARTBEAT_STARTED = False
_FAULT_FILE_HANDLE = None
_PREVIOUS_THREADING_HOOK = getattr(threading, "excepthook", None)
_PREVIOUS_UNRAISABLE_HOOK = getattr(sys, "unraisablehook", None)
_PREVIOUS_SYS_HOOK = sys.excepthook

_SECRET_PATTERNS = (
    (re.compile(r"(?i)(telegram[_-]?token\s*[=:]\s*)[^\s]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(x-agentcockpit-admin\s*[:=]\s*)[^\s]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(admin[_-]?token\s*[=:]\s*)[^\s]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(credentials-contents\s+)[^\s]+"), r"\1<redacted>"),
    (re.compile(r"([?&](?:token|admin|session|key)=)[^&\s]+"), r"\1<redacted>"),
    (re.compile(r"\b\d{5,}:[A-Za-z0-9_-]{20,}\b"), "<telegram-token-redacted>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"), "ghp_<redacted>"),
    (re.compile(r"\bacp_[A-Za-z0-9_-]+"), "acp_<redacted>"),
    (re.compile(r"(/private)?/var/folders/\S+"), "<temp-file>"),
    (re.compile(r"(/tmp|/var/tmp)/\S+"), "<temp-file>"),
)


def _ensure_dirs():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(CRASH_DIR, exist_ok=True)
    os.makedirs(DIAGNOSTIC_DIR, exist_ok=True)


_ensure_dirs()


def redact_text(value):
    text = str(value or "")
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _sanitize_record(record):
    try:
        record["message"] = redact_text(record.get("message", ""))
        for key, value in list(record.get("extra", {}).items()):
            if isinstance(value, str):
                record["extra"][key] = redact_text(value)
    except Exception:
        pass
    return True


logger.remove()

# stderr UTF-8 fix: Windows charmap + macOS LANG=C
_stderr_sink = sys.stderr
try:
    import io

    if hasattr(sys.stderr, "buffer") and (sys.stderr.encoding or "").lower() not in ("utf-8", "utf8"):
        _stderr_sink = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

logger.add(
    _stderr_sink,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    colorize=True,
    filter=_sanitize_record,
)

logger.add(
    APP_LOG_FILE,
    rotation="00:00",
    retention="7 days",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | pid={process.id} | thread={thread.name} | {name} | {message}",
    encoding="utf-8",
    enqueue=True,
    filter=_sanitize_record,
)


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_call(func, default=None):
    try:
        return func()
    except Exception as exc:
        return default if default is not None else f"error: {redact_text(exc)}"


def _safe_int_env(name, default):
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _count_open_fds():
    if os.name == "nt":
        return None
    for fd_dir in ("/proc/self/fd", "/dev/fd"):
        try:
            return len(os.listdir(fd_dir))
        except Exception:
            continue
    return None


def _resource_snapshot():
    if resource is None:
        return {"available": False}
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss_units = "bytes" if sys.platform == "darwin" else "kb"
        return {
            "max_rss": int(usage.ru_maxrss),
            "max_rss_units": rss_units,
            "user_cpu_seconds": round(float(usage.ru_utime), 3),
            "system_cpu_seconds": round(float(usage.ru_stime), 3),
        }
    except Exception as exc:
        return {"error": redact_text(exc)}


def _disk_snapshot():
    try:
        usage = shutil.disk_usage(PROJECT_ROOT)
        return {
            "total_mb": usage.total // (1024 * 1024),
            "free_mb": usage.free // (1024 * 1024),
        }
    except Exception as exc:
        return {"error": redact_text(exc)}


def _selected_env_snapshot():
    keys = (
        "AGENTCOCKPIT_AUTOSTART",
        "AGENTCOCKPIT_PARENT_PIDS",
        "AGENTCOCKPIT_DIAGNOSTICS_INTERVAL",
        "PHONE_BIND",
        "PHONE_PORT",
        "PHONE_PUBLIC_TUNNEL",
        "PHONE_KEEP_AWAKE",
        "PHONE_KEEP_AWAKE_FLAGS",
        "PYTHONIOENCODING",
        "USER",
        "LOGNAME",
    )
    snapshot = {}
    for key in keys:
        if key in os.environ:
            snapshot[key] = redact_text(os.environ.get(key, ""))
    for key in ("TELEGRAM_TOKEN", "ALLOWED_USER_ID"):
        snapshot[key] = "set" if os.getenv(key) else "unset"
    return snapshot


def _thread_snapshot():
    threads = []
    for thread in threading.enumerate():
        threads.append(
            {
                "name": thread.name,
                "ident": thread.ident,
                "daemon": thread.daemon,
                "alive": thread.is_alive(),
            }
        )
    return threads


def collect_diagnostics_snapshot(process_name=None, *, extra=None):
    snapshot = {
        "schema": 1,
        "created_at": _utc_now(),
        "process": process_name or _PROCESS_NAME,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "uptime_seconds": round(time.time() - _STARTED_AT, 3),
        "argv": [redact_text(arg) for arg in sys.argv],
        "cwd": redact_text(_safe_call(lambda: os.getcwd(), "")),
        "executable": redact_text(sys.executable),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "env": _selected_env_snapshot(),
        "threads": _thread_snapshot(),
        "open_fds": _count_open_fds(),
        "resource": _resource_snapshot(),
        "disk": _disk_snapshot(),
        "app_log_file": redact_text(APP_LOG_FILE),
        "event_log_file": redact_text(EVENT_LOG_FILE),
    }
    if extra:
        snapshot["extra"] = _sanitize_json(extra)
    return snapshot


def _sanitize_json(value):
    if isinstance(value, dict):
        return {str(key): _sanitize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _write_json_atomic(path, payload):
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(_sanitize_json(payload), handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    os.replace(temp_path, path)


def _append_jsonl(path, payload):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(_sanitize_json(payload), ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def record_runtime_event(event, **payload):
    _ensure_dirs()
    body = {
        "created_at": _utc_now(),
        "event": str(event),
        "process": _PROCESS_NAME,
        "pid": os.getpid(),
        **payload,
    }
    try:
        _append_jsonl(EVENT_LOG_FILE, body)
    except Exception as exc:
        logger.debug(f"Diagnostic event yazilamadi: {exc}")


def _tail_file(path, max_lines=160):
    try:
        if not path or not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()[-max_lines:]
        return [redact_text(line.rstrip("\n")) for line in lines]
    except Exception as exc:
        return [f"<tail failed: {redact_text(exc)}>"]


def _thread_dump_text():
    frames = sys._current_frames()
    chunks = []
    for thread in threading.enumerate():
        chunks.append(f"\n--- Thread {thread.name} ident={thread.ident} daemon={thread.daemon} ---")
        frame = frames.get(thread.ident)
        if frame is None:
            chunks.append("<no frame>")
            continue
        chunks.extend(traceback.format_stack(frame))
    return redact_text("".join(chunks))


def _crash_path():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return os.path.join(CRASH_DIR, f"crash_{timestamp}_{os.getpid()}.log")


def log_crash(module, error, exc_info=None):
    _ensure_dirs()
    crash_file = _crash_path()
    snapshot = collect_diagnostics_snapshot(module)
    payload = {
        "module": module,
        "error": redact_text(error),
        "snapshot": snapshot,
    }
    record_runtime_event("crash", **payload)

    with open(crash_file, "w", encoding="utf-8") as handle:
        handle.write("=== AGENTCOCKPIT CRASH REPORT ===\n")
        handle.write(f"created_at: {datetime.now().isoformat(timespec='seconds')}\n")
        handle.write(f"module: {module}\n")
        handle.write(f"pid: {os.getpid()}\n")
        handle.write(f"error: {redact_text(error)}\n")
        if exc_info:
            handle.write("\n--- Traceback ---\n")
            handle.write(redact_text(exc_info))
            if not str(exc_info).endswith("\n"):
                handle.write("\n")
        handle.write("\n--- Runtime snapshot ---\n")
        json.dump(snapshot, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n\n--- Thread dump ---\n")
        handle.write(_thread_dump_text())
        handle.write("\n\n--- Recent app log tail ---\n")
        for line in _tail_file(APP_LOG_FILE):
            handle.write(line + "\n")
        handle.write("\n--- Recent diagnostic event tail ---\n")
        for line in _tail_file(EVENT_LOG_FILE):
            handle.write(line + "\n")

    logger.critical(f"COKME [{module}]: {redact_text(error)}")
    return crash_file


def _sys_exception_hook(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        _PREVIOUS_SYS_HOOK(exc_type, exc_value, exc_traceback)
        return
    exc_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    log_crash(f"{_PROCESS_NAME}.main", str(exc_value), exc_text)
    _PREVIOUS_SYS_HOOK(exc_type, exc_value, exc_traceback)


def _thread_exception_hook(args):
    exc_text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    log_crash(f"{_PROCESS_NAME}.thread.{args.thread.name}", str(args.exc_value), exc_text)
    if _PREVIOUS_THREADING_HOOK:
        _PREVIOUS_THREADING_HOOK(args)


def _unraisable_hook(unraisable):
    exc_type = type(unraisable.exc_value)
    exc_text = "".join(traceback.format_exception(exc_type, unraisable.exc_value, unraisable.exc_traceback))
    object_text = redact_text(getattr(unraisable, "object", ""))
    log_crash(f"{_PROCESS_NAME}.unraisable", f"{unraisable.exc_value} object={object_text}", exc_text)
    if _PREVIOUS_UNRAISABLE_HOOK:
        _PREVIOUS_UNRAISABLE_HOOK(unraisable)


def install_diagnostics_hooks(process_name, *, main_excepthook=True):
    global _FAULT_FILE_HANDLE, _HOOKS_INSTALLED, _PROCESS_NAME
    if _HOOKS_INSTALLED:
        if process_name and process_name != _PROCESS_NAME:
            record_runtime_event("diagnostics_hooks_already_installed", component=process_name)
        return
    _PROCESS_NAME = process_name or _PROCESS_NAME
    _HOOKS_INSTALLED = True
    _ensure_dirs()

    try:
        fault_path = os.path.join(DIAGNOSTIC_DIR, f"fault_{os.getpid()}.log")
        _FAULT_FILE_HANDLE = open(fault_path, "a", encoding="utf-8")
        faulthandler.enable(file=_FAULT_FILE_HANDLE, all_threads=True)
        if hasattr(signal, "SIGUSR1"):
            faulthandler.register(signal.SIGUSR1, file=_FAULT_FILE_HANDLE, all_threads=True)
    except Exception as exc:
        logger.warning(f"Faulthandler baslatilamadi: {exc}")

    if main_excepthook:
        sys.excepthook = _sys_exception_hook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_exception_hook
    if hasattr(sys, "unraisablehook"):
        sys.unraisablehook = _unraisable_hook

    record_runtime_event("diagnostics_hooks_installed", app_log_file=APP_LOG_FILE)
    logger.info(f"Diagnostics hooks aktif: process={_PROCESS_NAME} pid={os.getpid()}")


def start_diagnostics_heartbeat(process_name=None, *, interval=None, extra_snapshot=None):
    global _HEARTBEAT_STARTED, _PROCESS_NAME
    if _HEARTBEAT_STARTED:
        if process_name and process_name != _PROCESS_NAME:
            record_runtime_event("diagnostics_heartbeat_already_started", component=process_name)
        return
    if process_name:
        _PROCESS_NAME = process_name
    interval = interval if interval is not None else _safe_int_env("AGENTCOCKPIT_DIAGNOSTICS_INTERVAL", 30)
    if interval <= 0:
        logger.info("Diagnostics heartbeat devre disi.")
        return
    _HEARTBEAT_STARTED = True

    state_path = os.path.join(DIAGNOSTIC_DIR, f"state_{_PROCESS_NAME}_{os.getpid()}.json")

    def _loop():
        while True:
            try:
                extra = extra_snapshot() if callable(extra_snapshot) else None
                snapshot = collect_diagnostics_snapshot(_PROCESS_NAME, extra=extra)
                _write_json_atomic(state_path, snapshot)
                record_runtime_event("heartbeat", uptime_seconds=snapshot["uptime_seconds"], open_fds=snapshot["open_fds"])
            except Exception as exc:
                logger.debug(f"Diagnostics heartbeat hatasi: {exc}")
            time.sleep(interval)

    thread = threading.Thread(target=_loop, name="agentcockpit-diagnostics-heartbeat", daemon=True)
    thread.start()
    logger.info(f"Diagnostics heartbeat aktif: interval={interval}s state={state_path}")


def configure_asyncio_diagnostics(loop=None, process_name=None):
    target_loop = loop or _safe_call(asyncio.get_event_loop, None)
    if target_loop is None:
        return
    name = process_name or _PROCESS_NAME
    previous_handler = target_loop.get_exception_handler()

    def _handler(loop, context):
        message = context.get("message", "asyncio exception")
        exc = context.get("exception")
        if exc:
            exc_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            log_crash(f"{name}.asyncio", f"{message}: {exc}", exc_text)
        else:
            log_crash(f"{name}.asyncio", message, repr(context))
        if previous_handler:
            previous_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    target_loop.set_exception_handler(_handler)
    record_runtime_event("asyncio_diagnostics_installed", process=name)


def get_logger(name):
    return logger.bind(name=name)


async def notify_crash(token, user_id, crash_file, error_msg):
    """Kullaniciya crash bildirimi gonder."""
    try:
        bot = Bot(token=token)
        message = "**HATA TESPIT EDILDI**\n\n"
        message += f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"Hata: {redact_text(error_msg)}\n"
        message += f"Dosya: {redact_text(crash_file)}"

        await bot.send_message(chat_id=user_id, text=message)
        logger.info(f"Crash bildirimi gonderildi: {user_id}")
    except Exception as exc:
        logger.error(f"Crash bildirimi gonderilemedi: {redact_text(exc)}")

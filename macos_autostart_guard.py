"""Delay macOS auto-start until a real desktop user owns the console.

LaunchAgents may be kicked while the console is still at loginwindow/root.
Starting AgentCockpit there creates the broken state we have seen: no user
desktop, no useful remote control, and flaky macOS services. Once a real user
owns /dev/console, AgentCockpit should start and report finer-grained health
itself; screen capture and tunnel DNS can recover after process start.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time


DEFAULT_INTERVAL_SEC = 10.0
DEFAULT_TIMEOUT_SEC = 0.0  # 0 means wait forever; launchd keeps this process alive.


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        return default


def _run(command: list[str], *, timeout: float = 5.0):
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return exc


def _console_identity() -> tuple[str, int]:
    result = _run(["stat", "-f", "%Su:%u", "/dev/console"], timeout=2)
    if isinstance(result, Exception) or result.returncode != 0:
        return "", -1
    raw = (result.stdout or "").strip()
    name, _, uid_text = raw.partition(":")
    try:
        uid = int(uid_text)
    except ValueError:
        uid = -1
    return name.strip(), uid


def _expected_user() -> str:
    return (os.getenv("USER") or os.getenv("LOGNAME") or "").strip()


def _console_ready() -> tuple[bool, str]:
    console_user, console_uid = _console_identity()
    expected = _expected_user()
    current_uid = os.getuid()
    if console_uid in {-1, 0} or not console_user or console_user in {"root", "_mbsetupuser", "loginwindow"}:
        return False, f"console user hazir degil ({console_user or 'unknown'})"
    # In some launchd/TCC states stat may print "(501)" instead of resolving the
    # user name. UID equality is still enough to prove that the real desktop user
    # owns the console.
    if console_uid == current_uid:
        return True, ""
    if expected and console_user != expected:
        return False, f"console user farkli ({console_user}, beklenen {expected})"
    return True, ""


def readiness_reasons() -> list[str]:
    if sys.platform != "darwin":
        return []

    reasons: list[str] = []
    ok, reason = _console_ready()
    if not ok:
        reasons.append(reason)
    return reasons


def wait_until_ready(*, sleep=time.sleep, now=time.monotonic) -> bool:
    interval = _env_float("AGENTCOCKPIT_MAC_READY_INTERVAL_SEC", DEFAULT_INTERVAL_SEC)
    timeout = _env_float("AGENTCOCKPIT_MAC_READY_TIMEOUT_SEC", DEFAULT_TIMEOUT_SEC)
    deadline = (now() + timeout) if timeout > 0 else None
    attempt = 0

    while True:
        reasons = readiness_reasons()
        if not reasons:
            if attempt:
                print("[AUTOSTART] macOS oturumu hazir. AgentCockpit baslatiliyor.", flush=True)
            return True

        attempt += 1
        print(
            "[AUTOSTART] macOS oturumu hazir degil; bekleniyor "
            f"(deneme {attempt}): {'; '.join(reasons)}",
            flush=True,
        )

        current_time = now()
        if deadline is not None and current_time >= deadline:
            print("[AUTOSTART] Hazirlik zaman asimina ulasti; baslatma ertelendi.", flush=True)
            return False

        sleep_for = interval
        if deadline is not None:
            sleep_for = max(0.0, min(interval, deadline - current_time))
        sleep(sleep_for)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Kullanim: macos_autostart_guard.py <command> [args...]", file=sys.stderr)
        return 2
    if not wait_until_ready():
        return 75
    os.execvpe(args[0], args, os.environ.copy())
    return 127


if __name__ == "__main__":
    raise SystemExit(main())

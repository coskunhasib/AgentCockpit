"""Register/unregister AgentCockpit for auto-start on user login."""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path


APP_LABEL = "com.agentcockpit.bot"
MAC_SCREEN_SESSION = "agentcockpit"
WINDOWS_TASK_NAME = "AgentCockpitBot"
LINUX_SERVICE_NAME = "agentcockpit-bot"
MAC_PROTECTED_DIR_NAMES = {"Desktop", "Documents", "Downloads"}

LEGACY_MAC_LABELS = ("com.antigravity.bot",)
LEGACY_WINDOWS_TASKS = ("AntigravityBot",)
LEGACY_LINUX_SERVICES = ("antigravity-bot",)


def get_bot_dir() -> Path:
    return Path(__file__).resolve().parent


def _first_existing(paths):
    for path in paths:
        if path.exists():
            return path
    return paths[-1]


def _python_executable(bot_dir: Path, *, windows_gui: bool = False) -> Path:
    if os.name == "nt":
        script_dir = bot_dir / "venv" / "Scripts"
        candidates = []
        if windows_gui:
            candidates.append(script_dir / "pythonw.exe")
        candidates.extend([script_dir / "python.exe", Path(sys.executable)])
        return _first_existing(candidates)

    return _first_existing(
        [
            bot_dir / "venv" / "bin" / "python3",
            bot_dir / "venv" / "bin" / "python",
            Path(sys.executable),
        ]
    )


def _ensure_log_dir(bot_dir: Path) -> Path:
    logs_dir = bot_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _run(command, *, check: bool = False):
    return subprocess.run(command, capture_output=True, text=True, check=check)


def _print_completed(prefix: str, result):
    output = (result.stdout or result.stderr or "").strip()
    if output:
        print(f"{prefix} {output}")


def register_windows(*, start_now: bool = False, bot_dir: Path | None = None):
    """Register via Windows Task Scheduler (no admin required)."""
    bot_dir = Path(bot_dir or get_bot_dir())
    python_exe = _python_executable(bot_dir, windows_gui=True)
    main_py = bot_dir / "main.py"
    command = subprocess.list2cmdline([str(python_exe), str(main_py)])

    for old_name in (*LEGACY_WINDOWS_TASKS, WINDOWS_TASK_NAME):
        _run(["schtasks", "/Delete", "/TN", old_name, "/F"])

    _run(
        [
            "schtasks",
            "/Create",
            "/TN",
            WINDOWS_TASK_NAME,
            "/TR",
            command,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/F",
        ],
        check=True,
    )
    print(f"[OK] '{WINDOWS_TASK_NAME}' auto-start kaydedildi.")

    if start_now:
        _run(["schtasks", "/Run", "/TN", WINDOWS_TASK_NAME], check=True)
        print(f"[OK] '{WINDOWS_TASK_NAME}' simdi baslatildi.")


def unregister_windows():
    removed = False
    for task_name in (WINDOWS_TASK_NAME, *LEGACY_WINDOWS_TASKS):
        result = _run(["schtasks", "/Delete", "/TN", task_name, "/F"])
        if result.returncode == 0:
            print(f"[OK] '{task_name}' auto-start kaldirildi.")
            removed = True
    if not removed:
        print("[OK] Auto-start gorevi zaten kayitli degildi.")


def status_windows():
    result = _run(["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME])
    if result.returncode == 0:
        print(f"[OK] '{WINDOWS_TASK_NAME}' kayitli.")
        _print_completed("[INFO]", result)
    else:
        print(f"[INFO] '{WINDOWS_TASK_NAME}' kayitli degil.")


def _mac_domain() -> str:
    return f"gui/{os.getuid()}"


def _mac_target(label: str = APP_LABEL) -> str:
    return f"{_mac_domain()}/{label}"


def _bootout_mac_label(label: str):
    _run(["launchctl", "bootout", _mac_target(label)])


def _mac_screen_executable() -> Path | None:
    screen = shutil.which("screen")
    return Path(screen) if screen else None


def _mac_program_arguments(python_exe: Path, main_py: Path):
    return [str(python_exe), str(main_py), "--autostart"]


def _quit_mac_screen_session():
    screen_exe = _mac_screen_executable()
    if screen_exe:
        _run([str(screen_exe), "-S", MAC_SCREEN_SESSION, "-X", "quit"])


def _mac_plist_payload(bot_dir: Path, python_exe: Path, main_py: Path, logs_dir: Path):
    return {
        "Label": APP_LABEL,
        "ProgramArguments": _mac_program_arguments(python_exe, main_py),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "WorkingDirectory": str(bot_dir),
        "EnvironmentVariables": {
            "PYTHONIOENCODING": "utf-8",
            "PATH": "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "AGENTCOCKPIT_AUTOSTART": "true",
            "HOME": str(Path.home()),
            "USER": os.getenv("USER", Path.home().name),
            "LOGNAME": os.getenv("LOGNAME", os.getenv("USER", Path.home().name)),
        },
        "StandardOutPath": str(logs_dir / "launchd.log"),
        "StandardErrorPath": str(logs_dir / "launchd_err.log"),
        "LimitLoadToSessionType": "Aqua",
    }


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _is_mac_privacy_protected_path(path: Path) -> bool:
    home = Path.home()
    return any(
        _is_relative_to(path, home / dirname)
        for dirname in MAC_PROTECTED_DIR_NAMES
    )


def _validate_mac_launch_dir(bot_dir: Path):
    if _is_mac_privacy_protected_path(bot_dir):
        raise RuntimeError(
            "macOS LaunchAgent, Desktop/Documents/Downloads altindaki venv dosyalarini "
            "izin yuzunden okuyamayabilir. Projeyi korumali olmayan bir dizine tasiyin "
            "veya autostart.py register --bot-dir /guvenli/AgentCockpit ile kaydedin."
        )


def register_mac(
    *,
    start_now: bool = True,
    bot_dir: Path | None = None,
    launch_agents_dir: Path | None = None,
):
    """Register via launchd LaunchAgent."""
    bot_dir = Path(bot_dir or get_bot_dir())
    _validate_mac_launch_dir(bot_dir)
    python_exe = _python_executable(bot_dir)
    main_py = bot_dir / "main.py"
    logs_dir = _ensure_log_dir(bot_dir)
    launch_agents_dir = Path(launch_agents_dir or Path.home() / "Library" / "LaunchAgents")
    plist_path = launch_agents_dir / f"{APP_LABEL}.plist"

    launch_agents_dir.mkdir(parents=True, exist_ok=True)

    _quit_mac_screen_session()

    for label in (APP_LABEL, *LEGACY_MAC_LABELS):
        _bootout_mac_label(label)
        legacy_path = launch_agents_dir / f"{label}.plist"
        _run(["launchctl", "unload", str(legacy_path)])
        if label != APP_LABEL and legacy_path.exists():
            legacy_path.unlink()

    with plist_path.open("wb") as plist_file:
        plistlib.dump(
            _mac_plist_payload(bot_dir, python_exe, main_py, logs_dir),
            plist_file,
            sort_keys=False,
        )

    _run(["launchctl", "enable", _mac_target(APP_LABEL)])

    if start_now:
        result = _run(["launchctl", "bootstrap", _mac_domain(), str(plist_path)])
        if result.returncode != 0:
            _bootout_mac_label(APP_LABEL)
            result = _run(["launchctl", "bootstrap", _mac_domain(), str(plist_path)])
        if result.returncode != 0:
            _print_completed("[HATA]", result)
            raise RuntimeError("launchctl bootstrap basarisiz oldu")
        print(f"[OK] '{APP_LABEL}' auto-start kaydedildi ve baslatildi.")
    else:
        print(f"[OK] '{APP_LABEL}' auto-start kaydedildi. Bir sonraki giriste baslayacak.")

    print(f"[INFO] LaunchAgent: {plist_path}")


def unregister_mac(*, launch_agents_dir: Path | None = None):
    launch_agents_dir = Path(launch_agents_dir or Path.home() / "Library" / "LaunchAgents")
    removed = False
    _quit_mac_screen_session()
    for label in (APP_LABEL, *LEGACY_MAC_LABELS):
        plist_path = launch_agents_dir / f"{label}.plist"
        _bootout_mac_label(label)
        _run(["launchctl", "unload", str(plist_path)])
        if plist_path.exists():
            plist_path.unlink()
            print(f"[OK] '{label}' auto-start kaldirildi.")
            removed = True
    if not removed:
        print("[OK] Auto-start plist'i zaten kayitli degildi.")


def status_mac(*, launch_agents_dir: Path | None = None):
    launch_agents_dir = Path(launch_agents_dir or Path.home() / "Library" / "LaunchAgents")
    plist_path = launch_agents_dir / f"{APP_LABEL}.plist"
    if plist_path.exists():
        print(f"[OK] LaunchAgent kayitli: {plist_path}")
    else:
        print(f"[INFO] LaunchAgent kayitli degil: {plist_path}")

    result = _run(["launchctl", "print", _mac_target(APP_LABEL)])
    if result.returncode == 0:
        print(f"[OK] '{APP_LABEL}' su an launchd tarafinda yuklu.")
    elif plist_path.exists():
        print(f"[INFO] '{APP_LABEL}' su an yuklu degil; bir sonraki kullanici girisinde yuklenecek.")
    else:
        print(f"[INFO] '{APP_LABEL}' su an yuklu degil.")


def _systemd_quote(value: Path | str) -> str:
    raw = str(value)
    return '"' + raw.replace("\\", "\\\\").replace('"', '\\"') + '"'


def register_linux(*, start_now: bool = True, bot_dir: Path | None = None):
    """Register via systemd user service."""
    bot_dir = Path(bot_dir or get_bot_dir())
    python_exe = _python_executable(bot_dir)
    main_py = bot_dir / "main.py"
    service_dir = Path.home() / ".config" / "systemd" / "user"
    service_path = service_dir / f"{LINUX_SERVICE_NAME}.service"

    service_content = f"""[Unit]
Description=AgentCockpit Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={_systemd_quote(bot_dir)}
ExecStart={_systemd_quote(python_exe)} {_systemd_quote(main_py)} --autostart
Restart=on-failure
RestartSec=10
Environment=PYTHONIOENCODING=utf-8 AGENTCOCKPIT_AUTOSTART=true

[Install]
WantedBy=default.target
"""

    service_dir.mkdir(parents=True, exist_ok=True)
    for service_name in (*LEGACY_LINUX_SERVICES, LINUX_SERVICE_NAME):
        _run(["systemctl", "--user", "stop", service_name])
        _run(["systemctl", "--user", "disable", service_name])
        legacy_path = service_dir / f"{service_name}.service"
        if service_name != LINUX_SERVICE_NAME and legacy_path.exists():
            legacy_path.unlink()

    service_path.write_text(service_content, encoding="utf-8")
    _run(["systemctl", "--user", "daemon-reload"], check=True)
    _run(["systemctl", "--user", "enable", LINUX_SERVICE_NAME], check=True)
    if start_now:
        _run(["systemctl", "--user", "start", LINUX_SERVICE_NAME], check=True)
        print(f"[OK] '{LINUX_SERVICE_NAME}' auto-start kaydedildi ve baslatildi.")
    else:
        print(f"[OK] '{LINUX_SERVICE_NAME}' auto-start kaydedildi. Bir sonraki giriste baslayacak.")


def unregister_linux():
    removed = False
    for service_name in (LINUX_SERVICE_NAME, *LEGACY_LINUX_SERVICES):
        _run(["systemctl", "--user", "stop", service_name])
        _run(["systemctl", "--user", "disable", service_name])
        service_path = Path.home() / ".config" / "systemd" / "user" / f"{service_name}.service"
        if service_path.exists():
            service_path.unlink()
            print(f"[OK] '{service_name}' auto-start kaldirildi.")
            removed = True
    _run(["systemctl", "--user", "daemon-reload"])
    if not removed:
        print("[OK] Auto-start servisi zaten kayitli degildi.")


def status_linux():
    result = _run(["systemctl", "--user", "is-enabled", LINUX_SERVICE_NAME])
    if result.returncode == 0:
        print(f"[OK] '{LINUX_SERVICE_NAME}' enabled.")
    else:
        print(f"[INFO] '{LINUX_SERVICE_NAME}' enabled degil.")

    result = _run(["systemctl", "--user", "is-active", LINUX_SERVICE_NAME])
    if result.returncode == 0:
        print(f"[OK] '{LINUX_SERVICE_NAME}' aktif.")
    else:
        print(f"[INFO] '{LINUX_SERVICE_NAME}' aktif degil.")


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="AgentCockpit auto-start yonetimi")
    parser.add_argument(
        "action",
        nargs="?",
        choices=("register", "unregister", "status"),
        default="register",
        help="register: kaydet, unregister: kaldir, status: durumu goster",
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Kaydi yap ama mevcut oturumda hemen baslatma.",
    )
    parser.add_argument(
        "--start-now",
        action="store_true",
        help="Kayittan sonra mevcut oturumda hemen baslat.",
    )
    parser.add_argument(
        "--bot-dir",
        default="",
        help="Auto-start icin kullanilacak AgentCockpit dizini. Bos birakilirsa bu dosyanin dizini kullanilir.",
    )
    args = parser.parse_args(argv)
    if args.no_start and args.start_now:
        parser.error("--no-start ve --start-now birlikte kullanilamaz")
    return args


def main(argv=None):
    args = _parse_args(argv)
    bot_dir = Path(args.bot_dir).expanduser().resolve() if args.bot_dir else None

    if sys.platform == "win32":
        if args.action == "unregister":
            unregister_windows()
        elif args.action == "status":
            status_windows()
        else:
            register_windows(start_now=args.start_now, bot_dir=bot_dir)
        return

    if sys.platform == "darwin":
        if args.action == "unregister":
            unregister_mac()
        elif args.action == "status":
            status_mac()
        else:
            register_mac(start_now=not args.no_start, bot_dir=bot_dir)
        return

    if args.action == "unregister":
        unregister_linux()
    elif args.action == "status":
        status_linux()
    else:
        register_linux(start_now=not args.no_start, bot_dir=bot_dir)


if __name__ == "__main__":
    main()

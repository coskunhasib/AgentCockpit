# autostart.py
"""Register/unregister bot for auto-start on system login."""
import sys
import os
import subprocess


def get_bot_dir():
    return os.path.dirname(os.path.abspath(__file__))


def register_windows():
    """Register via Windows Task Scheduler (no admin required)."""
    bot_dir = get_bot_dir()
    python_exe = os.path.join(bot_dir, "venv", "Scripts", "pythonw.exe")
    main_py = os.path.join(bot_dir, "main.py")
    task_name = "AntigravityBot"

    # Remove old task if exists
    subprocess.run(
        ["schtasks", "/Delete", "/TN", task_name, "/F"],
        capture_output=True
    )

    # Create task that runs at logon
    subprocess.run([
        "schtasks", "/Create",
        "/TN", task_name,
        "/TR", f'"{python_exe}" "{main_py}"',
        "/SC", "ONLOGON",
        "/RL", "LIMITED",
        "/F",
    ], check=True)
    print(f"[OK] '{task_name}' auto-start kaydedildi.")


def unregister_windows():
    task_name = "AntigravityBot"
    subprocess.run(
        ["schtasks", "/Delete", "/TN", task_name, "/F"],
        check=True
    )
    print(f"[OK] '{task_name}' auto-start kaldirildi.")


def register_mac():
    """Register via launchd plist."""
    bot_dir = get_bot_dir()
    python_exe = os.path.join(bot_dir, "venv", "bin", "python3")
    main_py = os.path.join(bot_dir, "main.py")
    plist_name = "com.antigravity.bot"
    plist_path = os.path.expanduser(f"~/Library/LaunchAgents/{plist_name}.plist")

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{plist_name}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_exe}</string>
        <string>{main_py}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>{bot_dir}</string>
    <key>StandardOutPath</key>
    <string>{bot_dir}/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>{bot_dir}/logs/launchd_err.log</string>
</dict>
</plist>"""

    os.makedirs(os.path.dirname(plist_path), exist_ok=True)
    with open(plist_path, "w") as f:
        f.write(plist_content)

    subprocess.run(["launchctl", "load", plist_path])
    print(f"[OK] '{plist_name}' auto-start kaydedildi.")


def unregister_mac():
    plist_name = "com.antigravity.bot"
    plist_path = os.path.expanduser(f"~/Library/LaunchAgents/{plist_name}.plist")
    subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
    if os.path.exists(plist_path):
        os.remove(plist_path)
    print(f"[OK] '{plist_name}' auto-start kaldirildi.")


def register_linux():
    """Register via systemd user service."""
    bot_dir = get_bot_dir()
    python_exe = os.path.join(bot_dir, "venv", "bin", "python3")
    main_py = os.path.join(bot_dir, "main.py")
    service_name = "antigravity-bot"
    service_dir = os.path.expanduser("~/.config/systemd/user")
    service_path = os.path.join(service_dir, f"{service_name}.service")

    service_content = f"""[Unit]
Description=Antigravity Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory={bot_dir}
ExecStart={python_exe} {main_py}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""

    os.makedirs(service_dir, exist_ok=True)
    with open(service_path, "w") as f:
        f.write(service_content)

    subprocess.run(["systemctl", "--user", "daemon-reload"])
    subprocess.run(["systemctl", "--user", "enable", service_name])
    subprocess.run(["systemctl", "--user", "start", service_name])
    print(f"[OK] '{service_name}' auto-start kaydedildi.")


def unregister_linux():
    service_name = "antigravity-bot"
    subprocess.run(["systemctl", "--user", "stop", service_name], capture_output=True)
    subprocess.run(["systemctl", "--user", "disable", service_name], capture_output=True)
    service_path = os.path.expanduser(f"~/.config/systemd/user/{service_name}.service")
    if os.path.exists(service_path):
        os.remove(service_path)
    subprocess.run(["systemctl", "--user", "daemon-reload"])
    print(f"[OK] '{service_name}' auto-start kaldirildi.")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "register"

    if sys.platform == "win32":
        unregister_windows() if action == "unregister" else register_windows()
    elif sys.platform == "darwin":
        unregister_mac() if action == "unregister" else register_mac()
    else:
        unregister_linux() if action == "unregister" else register_linux()

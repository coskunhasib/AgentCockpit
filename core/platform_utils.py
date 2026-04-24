"""Cross-platform abstraction for window management and Claude Desktop control."""

import os
import signal
import subprocess
import sys
import time

from core.logger import get_logger

# Lazy platform imports — sadece aktif platform yuklenir
_platform_mod = None


def _get_platform_module():
    global _platform_mod
    if _platform_mod is not None:
        return _platform_mod
    if sys.platform == "win32":
        from core import claude_platform_windows as mod
    elif sys.platform == "darwin":
        from core import claude_platform_macos as mod
    else:
        from core import claude_platform_linux as mod
    _platform_mod = mod
    return mod


def _call(func_name, *args, **kwargs):
    """Call a platform-specific function by name."""
    mod = _get_platform_module()
    fn = getattr(mod, func_name, None)
    if fn is None:
        logger.warning(f"Platform fonksiyonu bulunamadi: {func_name}")
        return None
    return fn(*args, **kwargs)

logger = get_logger("platform_utils")

PLATFORM = sys.platform  # "win32", "darwin", "linux"


def get_claude_exe():
    """Return the Claude executable path for this platform."""
    custom = os.environ.get("CLAUDE_EXE")
    if custom:
        return custom
    home = os.path.expanduser("~")
    if PLATFORM == "win32":
        return os.path.join(home, ".local", "bin", "claude.exe")
    return os.path.join(home, ".local", "bin", "claude")


def get_claude_sessions_meta_dir():
    """Return the Claude Desktop sessions metadata directory."""
    if PLATFORM == "win32":
        base = os.environ.get(
            "APPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        )
    elif PLATFORM == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get(
            "XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")
        )
    return os.path.join(base, "Claude", "claude-code-sessions")


def get_claude_projects_dir():
    """Return the Claude CLI projects directory."""
    return os.path.join(os.path.expanduser("~"), ".claude", "projects")


def kill_process(pid):
    """Kill a process by PID, cross-platform."""
    try:
        if PLATFORM == "win32":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=5
            )
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except (ProcessLookupError, OSError, subprocess.TimeoutExpired):
        return False


def restart_pc():
    """Restart the computer, cross-platform."""
    if PLATFORM == "win32":
        subprocess.run(["shutdown", "/r", "/t", "5"])
    elif PLATFORM == "darwin":
        subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to restart']
        )
    else:
        subprocess.run(["systemctl", "reboot"])


def find_claude_window():
    return _call("find_claude_window")


def focus_window(handle):
    if not handle:
        return False
    return _call("focus_window", handle)


def open_session_in_desktop(title, mode="code"):
    return _call("open_session_in_desktop", title, mode=mode)


def wait_and_read_response(timeout=300, last_prompt=None):
    return _call("wait_and_read_response", timeout, last_prompt)


def ensure_claude_sidebar_open():
    return _call("ensure_claude_sidebar_open")


def set_claude_mode(mode):
    return _call("set_claude_mode", mode)


def set_claude_model(model_key, mode="code"):
    return _call("set_claude_model", model_key, mode=mode)


def set_claude_effort(effort_key):
    return _call("set_claude_effort", effort_key)


def set_claude_permission_mode(mode_key):
    return _call("set_claude_permission_mode", mode_key)


def set_claude_extended_thinking(enabled):
    return _call("set_claude_extended_thinking", enabled)


def list_claude_chat_sessions(limit=10):
    return _call("list_claude_chat_sessions", limit)


def read_visible_claude_chat_history(last_n=10):
    return _call("read_visible_claude_chat_history", last_n)


def focus_claude_input():
    return _call("focus_claude_input")


def detect_permission_prompt():
    return _call("detect_permission_prompt")


def click_permission_button(button_text):
    return _call("click_permission_button", button_text)


def click_new_session():
    clicked = _call("click_new_session")
    if clicked:
        return True
    try:
        import pyautogui
        mod_key = "command" if PLATFORM == "darwin" else "ctrl"
        pyautogui.hotkey(mod_key, "n")
        return True
    except Exception as exc:
        logger.error(f"New session hotkey hatasi: {exc}")
        return False


def paste_and_send(text):
    """Paste text and press Enter in the focused window."""
    try:
        import pyautogui
        import pyperclip
    except Exception as exc:
        logger.error(f"paste_and_send kullanilamiyor (pyautogui/pyperclip): {exc}")
        return

    pyperclip.copy(text)
    mod_key = "command" if PLATFORM == "darwin" else "ctrl"
    pyautogui.hotkey(mod_key, "v")
    time.sleep(0.3)
    pyautogui.press("enter")

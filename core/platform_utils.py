"""Cross-platform abstraction for window management and Claude Desktop control."""

import os
import signal
import subprocess
import sys
import time

from core.claude_platform_linux import (
    click_new_session as linux_click_new_session,
    click_permission_button as linux_click_permission_button,
    detect_permission_prompt as linux_detect_permission_prompt,
    ensure_claude_sidebar_open as linux_ensure_claude_sidebar_open,
    find_claude_window as linux_find_claude_window,
    focus_claude_input as linux_focus_claude_input,
    focus_window as linux_focus_window,
    list_claude_chat_sessions as linux_list_claude_chat_sessions,
    open_session_in_desktop as linux_open_session_in_desktop,
    read_visible_claude_chat_history as linux_read_visible_claude_chat_history,
    set_claude_effort as linux_set_claude_effort,
    set_claude_extended_thinking as linux_set_claude_extended_thinking,
    set_claude_mode as linux_set_claude_mode,
    set_claude_model as linux_set_claude_model,
    set_claude_permission_mode as linux_set_claude_permission_mode,
    wait_and_read_response as linux_wait_and_read_response,
)
from core.claude_platform_macos import (
    click_new_session as mac_click_new_session,
    click_permission_button as mac_click_permission_button,
    detect_permission_prompt as mac_detect_permission_prompt,
    ensure_claude_sidebar_open as mac_ensure_claude_sidebar_open,
    find_claude_window as mac_find_claude_window,
    focus_claude_input as mac_focus_claude_input,
    focus_window as mac_focus_window,
    list_claude_chat_sessions as mac_list_claude_chat_sessions,
    open_session_in_desktop as mac_open_session_in_desktop,
    read_visible_claude_chat_history as mac_read_visible_claude_chat_history,
    set_claude_effort as mac_set_claude_effort,
    set_claude_extended_thinking as mac_set_claude_extended_thinking,
    set_claude_mode as mac_set_claude_mode,
    set_claude_model as mac_set_claude_model,
    set_claude_permission_mode as mac_set_claude_permission_mode,
    wait_and_read_response as mac_wait_and_read_response,
)
from core.claude_platform_windows import (
    click_new_session as win_click_new_session,
    click_permission_button as win_click_permission_button,
    detect_permission_prompt as win_detect_permission_prompt,
    ensure_claude_sidebar_open as win_ensure_claude_sidebar_open,
    find_claude_window as win_find_claude_window,
    focus_claude_input as win_focus_claude_input,
    focus_window as win_focus_window,
    list_claude_chat_sessions as win_list_claude_chat_sessions,
    open_session_in_desktop as win_open_session_in_desktop,
    read_visible_claude_chat_history as win_read_visible_claude_chat_history,
    set_claude_effort as win_set_claude_effort,
    set_claude_extended_thinking as win_set_claude_extended_thinking,
    set_claude_mode as win_set_claude_mode,
    set_claude_model as win_set_claude_model,
    set_claude_permission_mode as win_set_claude_permission_mode,
    wait_and_read_response as win_wait_and_read_response,
)
from core.logger import get_logger

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
    """Find the Claude Desktop window. Returns an opaque handle or None."""
    if PLATFORM == "win32":
        return win_find_claude_window()
    if PLATFORM == "darwin":
        return mac_find_claude_window()
    return linux_find_claude_window()


def focus_window(handle):
    """Bring a window to front. Returns True on success."""
    if not handle:
        return False
    if PLATFORM == "win32":
        return win_focus_window(handle)
    if PLATFORM == "darwin":
        return mac_focus_window(handle)
    return linux_focus_window(handle)


def open_session_in_desktop(title, mode="code"):
    """Open a specific session by title in Claude Desktop."""
    if PLATFORM == "win32":
        return win_open_session_in_desktop(title, mode=mode)
    if PLATFORM == "darwin":
        return mac_open_session_in_desktop(title, mode=mode)
    return linux_open_session_in_desktop(title, mode=mode)


def wait_and_read_response(timeout=300, last_prompt=None):
    """Wait for Claude to finish, then read the response."""
    if PLATFORM == "win32":
        return win_wait_and_read_response(timeout, last_prompt)
    if PLATFORM == "darwin":
        return mac_wait_and_read_response(timeout, last_prompt)
    return linux_wait_and_read_response(timeout, last_prompt)


def ensure_claude_sidebar_open():
    """Open the Claude sidebar if it is currently collapsed."""
    if PLATFORM == "win32":
        return win_ensure_claude_sidebar_open()
    if PLATFORM == "darwin":
        return mac_ensure_claude_sidebar_open()
    return linux_ensure_claude_sidebar_open()


def set_claude_mode(mode):
    """Switch Claude to chat, cowork, or code mode."""
    if PLATFORM == "win32":
        return win_set_claude_mode(mode)
    if PLATFORM == "darwin":
        return mac_set_claude_mode(mode)
    return linux_set_claude_mode(mode)


def set_claude_model(model_key, mode="code"):
    """Pick the active Claude model from the model menu."""
    if PLATFORM == "win32":
        return win_set_claude_model(model_key, mode=mode)
    if PLATFORM == "darwin":
        return mac_set_claude_model(model_key, mode=mode)
    return linux_set_claude_model(model_key, mode=mode)


def set_claude_effort(effort_key):
    """Pick the active reasoning effort from the model menu."""
    if PLATFORM == "win32":
        return win_set_claude_effort(effort_key)
    if PLATFORM == "darwin":
        return mac_set_claude_effort(effort_key)
    return linux_set_claude_effort(effort_key)


def set_claude_permission_mode(mode_key):
    """Change Claude's permission mode."""
    if PLATFORM == "win32":
        return win_set_claude_permission_mode(mode_key)
    if PLATFORM == "darwin":
        return mac_set_claude_permission_mode(mode_key)
    return linux_set_claude_permission_mode(mode_key)


def set_claude_extended_thinking(enabled):
    """Toggle Extended thinking in Chat/Cowork model menus."""
    if PLATFORM == "win32":
        return win_set_claude_extended_thinking(enabled)
    if PLATFORM == "darwin":
        return mac_set_claude_extended_thinking(enabled)
    return linux_set_claude_extended_thinking(enabled)


def list_claude_chat_sessions(limit=10):
    """Return visible Chat recents from Claude Desktop."""
    if PLATFORM == "win32":
        return win_list_claude_chat_sessions(limit)
    if PLATFORM == "darwin":
        return mac_list_claude_chat_sessions(limit)
    return linux_list_claude_chat_sessions(limit)


def read_visible_claude_chat_history(last_n=10):
    """Best-effort read of the currently visible Chat conversation."""
    if PLATFORM == "win32":
        return win_read_visible_claude_chat_history(last_n)
    if PLATFORM == "darwin":
        return mac_read_visible_claude_chat_history(last_n)
    return linux_read_visible_claude_chat_history(last_n)


def focus_claude_input():
    """Focus the Claude input area."""
    if PLATFORM == "win32":
        return win_focus_claude_input()
    if PLATFORM == "darwin":
        return mac_focus_claude_input()
    return linux_focus_claude_input()


def detect_permission_prompt():
    """Detect if Claude Desktop is showing a permission prompt."""
    if PLATFORM == "win32":
        return win_detect_permission_prompt()
    if PLATFORM == "darwin":
        return mac_detect_permission_prompt()
    return linux_detect_permission_prompt()


def click_permission_button(button_text):
    """Click a specific permission button in Claude Desktop."""
    if PLATFORM == "win32":
        return win_click_permission_button(button_text)
    if PLATFORM == "darwin":
        return mac_click_permission_button(button_text)
    return linux_click_permission_button(button_text)


def click_new_session():
    """Click the 'New session' button in Claude Desktop."""
    clicked = False
    if PLATFORM == "win32":
        clicked = win_click_new_session()
    elif PLATFORM == "darwin":
        clicked = mac_click_new_session()
    else:
        clicked = linux_click_new_session()

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
    import pyautogui
    import pyperclip

    pyperclip.copy(text)
    mod_key = "command" if PLATFORM == "darwin" else "ctrl"
    pyautogui.hotkey(mod_key, "v")
    time.sleep(0.3)
    pyautogui.press("enter")

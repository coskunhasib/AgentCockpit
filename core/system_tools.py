# core/system_tools.py
import datetime
import importlib
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import ImageDraw

from core.data_manager import DataManager
from core.logger import get_logger, log_crash
from core.runtime_compat import desktop_automation_help_text

logger = get_logger("system_tools")

_PYAUTOGUI = None
_PYPERCLIP = None
_QUARTZ = None


def _get_pyautogui():
    global _PYAUTOGUI
    if _PYAUTOGUI is not None:
        return _PYAUTOGUI

    try:
        module = importlib.import_module("pyautogui")
        module.FAILSAFE = os.environ.get("FAILSAFE_OFF", "").lower() != "true"
        _PYAUTOGUI = module
        return module
    except Exception as exc:
        logger.error(f"pyautogui kullanilamiyor: {exc}")
        return None


def _get_pyperclip():
    global _PYPERCLIP
    if _PYPERCLIP is not None:
        return _PYPERCLIP

    try:
        _PYPERCLIP = importlib.import_module("pyperclip")
        return _PYPERCLIP
    except Exception as exc:
        logger.error(f"pyperclip kullanilamiyor: {exc}")
        return None


def _get_quartz():
    global _QUARTZ
    if _QUARTZ is not None:
        return _QUARTZ

    try:
        _QUARTZ = importlib.import_module("Quartz")
        return _QUARTZ
    except Exception as exc:
        logger.error(f"Quartz unicode klavye kullanilamiyor: {exc}")
        return None


def _paste_with_system_events(timeout=2):
    if sys.platform != "darwin":
        return False

    script = 'tell application "System Events" to keystroke "v" using command down'
    try:
        completed = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning("System Events yapistirma zaman asimina ugradi.")
        return False
    except Exception as exc:
        logger.warning(f"System Events yapistirma calistirilamadi: {exc}")
        return False

    if completed.returncode == 0:
        return True

    detail = (completed.stderr or completed.stdout or "").strip()
    logger.warning(f"System Events yapistirma basarisiz: {detail}")
    return False


def _mouse_overlay_point(image_size):
    pyautogui = _get_pyautogui()
    if not pyautogui:
        raise RuntimeError(desktop_automation_help_text())

    mouse_x, mouse_y = pyautogui.position()
    logical_width, logical_height = pyautogui.size()
    image_width, image_height = image_size

    scale_x = image_width / logical_width if logical_width else 1.0
    scale_y = image_height / logical_height if logical_height else 1.0
    return mouse_x * scale_x, mouse_y * scale_y


class SystemOps:
    KEY_ALIASES = {
        "escape": "esc",
        "return": "enter",
        "del": "delete",
        "back": "backspace",
    }
    MAC_HOTKEY_COMBOS = {
        ("alt", "tab"): ["command", "tab"],
        ("alt", "shift", "tab"): ["command", "shift", "tab"],
        ("alt", "f4"): ["command", "w"],
        ("ctrl", "shift", "esc"): ["command", "option", "esc"],
        ("ctrl", "alt", "delete"): ["command", "option", "esc"],
        ("win", "d"): ["command", "f3"],
        ("winleft", "d"): ["command", "f3"],
        ("windows", "d"): ["command", "f3"],
        ("win", "l"): ["ctrl", "command", "q"],
        ("winleft", "l"): ["ctrl", "command", "q"],
        ("windows", "l"): ["ctrl", "command", "q"],
    }
    MAC_KEY_ALIASES = {
        "cmd": "command",
        "command": "command",
        "ctrl": "command",
        "control": "command",
        "mac_ctrl": "ctrl",
        "mac_control": "ctrl",
        "win": "command",
        "winleft": "command",
        "windows": "command",
        "alt": "option",
        "option": "option",
    }
    DESKTOP_KEY_ALIASES = {
        "cmd": "ctrl",
        "command": "ctrl",
        "mac_ctrl": "ctrl",
        "mac_control": "ctrl",
        "option": "alt",
        "win": "winleft",
        "windows": "winleft",
    }
    SPECIAL_COMMANDS = {
        "taskmgr-close",
        "close-taskmgr",
        "task-manager-close",
    }

    @staticmethod
    def _normalize_key_name(key_name):
        key = str(key_name or "").strip().lower()
        return SystemOps.KEY_ALIASES.get(key, key)

    @staticmethod
    def close_task_manager():
        if sys.platform != "win32":
            return False

        try:
            result = subprocess.run(
                ["taskkill", "/IM", "Taskmgr.exe", "/F"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.info("Task Manager kapatildi.")
                return True

            combined = f"{result.stdout}\n{result.stderr}".lower()
            if "not found" in combined or "bulunamad" in combined:
                logger.info("Task Manager zaten kapali.")
                return True

            logger.error(f"Task Manager kapatilamadi: {result.stderr or result.stdout}")
            return False
        except Exception as exc:
            logger.error(f"Task Manager kapatma hatasi: {exc}")
            log_crash("system_tools.close_task_manager", str(exc))
            return False

    @staticmethod
    def normalize_hotkey(keys_list):
        normalized = [SystemOps._normalize_key_name(key) for key in keys_list or []]
        if sys.platform == "darwin":
            combo = tuple(normalized)
            if combo in SystemOps.MAC_HOTKEY_COMBOS:
                return list(SystemOps.MAC_HOTKEY_COMBOS[combo])
            return [SystemOps.MAC_KEY_ALIASES.get(key, key) for key in normalized]

        return [SystemOps.DESKTOP_KEY_ALIASES.get(key, key) for key in normalized]

    @staticmethod
    def mouse_move(direction):
        pyautogui = _get_pyautogui()
        if not pyautogui:
            return False

        step = DataManager.get_mouse_speed()
        if not isinstance(step, int):
            step = 50

        if direction == "up":
            pyautogui.moveRel(0, -step)
        elif direction == "down":
            pyautogui.moveRel(0, step)
        elif direction == "left":
            pyautogui.moveRel(-step, 0)
        elif direction == "right":
            pyautogui.moveRel(step, 0)
        return True

    @staticmethod
    def take_screenshot():
        try:
            pyautogui = _get_pyautogui()
            if not pyautogui:
                return None

            PROJECT_ROOT = Path(__file__).resolve().parent.parent
            temp_dir = PROJECT_ROOT / "temp_screens"
            if not temp_dir.exists():
                temp_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = str(temp_dir / f"scr_{timestamp}.png")

            screenshot = pyautogui.screenshot()

            try:
                mouse_x, mouse_y = _mouse_overlay_point(screenshot.size)
                draw = ImageDraw.Draw(screenshot)
                radius = 10
                draw.ellipse(
                    (mouse_x - radius, mouse_y - radius, mouse_x + radius, mouse_y + radius),
                    outline="red",
                    width=3,
                )
                draw.ellipse(
                    (mouse_x - 2, mouse_y - 2, mouse_x + 2, mouse_y + 2),
                    fill="red",
                )
            except Exception:
                pass

            screenshot.save(filename)
            logger.info(f"Screenshot alindi: {filename}")
            return filename
        except Exception as exc:
            logger.error(f"Screenshot hatasi: {exc}")
            log_crash("system_tools.take_screenshot", str(exc))
            return None

    @staticmethod
    def clean_up(filepath):
        if os.path.exists(filepath):
            os.remove(filepath)

    @staticmethod
    def restart_pc():
        from core.platform_utils import restart_pc

        restart_pc()

    @staticmethod
    def restart_script():
        import subprocess

        python_path = sys.executable
        if hasattr(sys, "_MEIPASS"):
            script_path = sys.executable
        else:
            script_path = os.path.abspath(sys.argv[0])

        print("Sistem yeniden baslatiliyor...")
        subprocess.Popen([python_path, script_path] + sys.argv[1:])
        sys.exit(0)

    @staticmethod
    def mouse_click(action="left"):
        pyautogui = _get_pyautogui()
        if not pyautogui:
            return False

        if action == "left":
            pyautogui.click()
        elif action == "right":
            pyautogui.rightClick()
        elif action == "double":
            pyautogui.doubleClick()
        return True

    @staticmethod
    def press_key(key_name):
        try:
            normalized = SystemOps._normalize_key_name(key_name)
            if normalized in SystemOps.SPECIAL_COMMANDS:
                return SystemOps.close_task_manager()

            pyautogui = _get_pyautogui()
            if not pyautogui:
                return False
            pyautogui.press(normalized)
            return True
        except Exception:
            return False

    @staticmethod
    def execute_hotkey(keys_list):
        try:
            normalized_keys = [
                SystemOps._normalize_key_name(key) for key in keys_list or []
            ]
            if normalized_keys and all(
                key in SystemOps.SPECIAL_COMMANDS for key in normalized_keys
            ):
                return SystemOps.close_task_manager()

            pyautogui = _get_pyautogui()
            if not pyautogui:
                return False

            corrected_keys = SystemOps.normalize_hotkey(normalized_keys)
            pyautogui.hotkey(*corrected_keys, interval=0.1)
            logger.debug(f"Hotkey: {corrected_keys}")
            return True
        except Exception as exc:
            logger.error(f"Hotkey hatasi: {exc}")
            log_crash("system_tools.execute_hotkey", str(exc))
            return False

    @staticmethod
    def type_text(text):
        try:
            pyautogui = _get_pyautogui()
            if not pyautogui:
                return False

            if SystemOps.paste_text(text):
                return True

            pyautogui.write(text)
            logger.debug("Metin yazildi.")
            return True
        except Exception as exc:
            logger.error(f"Yazma hatasi: {exc}")
            log_crash("system_tools.type_text", str(exc))
            return False

    @staticmethod
    def paste_text(text, *, restore_clipboard=False):
        try:
            if sys.platform == "darwin":
                permissions = SystemOps.desktop_input_permissions()
                if permissions.get("post_event_access") is False:
                    logger.error(f"Yapistirma izni yok: {permissions}")
                    return False

            pyperclip = _get_pyperclip()
            if not pyperclip:
                return False
            pyautogui = _get_pyautogui()
            if sys.platform != "darwin" and not pyautogui:
                return False

            previous_clipboard = None
            if restore_clipboard:
                try:
                    previous_clipboard = pyperclip.paste()
                except Exception:
                    previous_clipboard = None

            pyperclip.copy(text)
            time.sleep(0.12)
            paste_method = ""
            if sys.platform == "darwin":
                if _paste_with_system_events():
                    paste_method = "system_events"
                elif pyautogui:
                    pyautogui.hotkey("command", "v", interval=0.08)
                    paste_method = "pyautogui"
            else:
                pyautogui.hotkey("ctrl", "v", interval=0.08)
                paste_method = "pyautogui"

            if not paste_method:
                return False

            if restore_clipboard and previous_clipboard is not None:
                time.sleep(0.35)
                pyperclip.copy(previous_clipboard)

            logger.debug(f"Metin yapistirildi: method={paste_method}")
            return True
        except Exception as exc:
            logger.error(f"Yapistirma hatasi: {exc}")
            log_crash("system_tools.paste_text", str(exc))
            return False

    @staticmethod
    def desktop_input_permissions():
        status = {
            "quartz_available": False,
            "post_event_access": None,
            "listen_event_access": None,
            "screen_capture_access": None,
        }
        quartz = _get_quartz()
        if not quartz:
            return status

        status["quartz_available"] = True
        checks = {
            "post_event_access": "CGPreflightPostEventAccess",
            "listen_event_access": "CGPreflightListenEventAccess",
            "screen_capture_access": "CGPreflightScreenCaptureAccess",
        }
        for key, function_name in checks.items():
            function = getattr(quartz, function_name, None)
            if not function:
                continue
            try:
                status[key] = bool(function())
            except Exception as exc:
                status[f"{key}_error"] = str(exc)
        return status

    @staticmethod
    def type_text_unicode(text, interval=0.02):
        if sys.platform != "darwin" or not text:
            return False

        try:
            quartz = _get_quartz()
            if not quartz:
                return False

            pyautogui = _get_pyautogui()
            ascii_buffer = []

            def flush_ascii_buffer():
                if not ascii_buffer:
                    return
                chunk = "".join(ascii_buffer)
                ascii_buffer.clear()
                if pyautogui:
                    pyautogui.write(chunk, interval=interval)
                    return
                _post_unicode_chunk(quartz, chunk, interval)

            for char in str(text):
                if char in ("\n", "\r"):
                    flush_ascii_buffer()
                    if pyautogui:
                        pyautogui.press("enter")
                    else:
                        _post_unicode_chunk(quartz, "\n", interval)
                    continue
                if char == "\t":
                    flush_ascii_buffer()
                    if pyautogui:
                        pyautogui.press("tab")
                    else:
                        _post_unicode_chunk(quartz, "\t", interval)
                    continue

                if 32 <= ord(char) <= 126:
                    ascii_buffer.append(char)
                    continue

                flush_ascii_buffer()
                _post_unicode_chunk(quartz, char, interval)

            flush_ascii_buffer()

            logger.debug("Unicode metin hibrit klavye eventleriyle yazildi.")
            return True
        except Exception as exc:
            logger.error(f"Unicode yazma hatasi: {exc}")
            log_crash("system_tools.type_text_unicode", str(exc))
            return False


def _post_unicode_chunk(quartz, text, interval=0.02):
    for char in str(text):
        down = quartz.CGEventCreateKeyboardEvent(None, 0, True)
        quartz.CGEventKeyboardSetUnicodeString(down, len(char), char)
        quartz.CGEventPost(quartz.kCGHIDEventTap, down)

        up = quartz.CGEventCreateKeyboardEvent(None, 0, False)
        quartz.CGEventPost(quartz.kCGHIDEventTap, up)

        if interval:
            time.sleep(interval)

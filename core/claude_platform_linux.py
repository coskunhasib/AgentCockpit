import subprocess
import time

from core.logger import get_logger

logger = get_logger("claude_platform_linux")


def _linux_run(cmd):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception as exc:
        logger.error(f"Linux cmd hatasi ({cmd[0]}): {exc}")
        return ""


def find_claude_window():
    result = _linux_run(["xdotool", "search", "--name", "Claude"])
    return result.split("\n")[0] if result else None


def focus_window(handle):
    if handle:
        _linux_run(["xdotool", "windowactivate", str(handle)])
        time.sleep(0.3)
        return True
    return False


def open_session_in_desktop(title, mode="code"):
    wid = find_claude_window()
    if not wid:
        logger.error("Claude penceresi bulunamadi (Linux)")
        return False
    focus_window(wid)
    logger.warning("Linux'ta tam session yonetimi sinirli - pencere odaklandi")
    return True


def wait_and_read_response(timeout, last_prompt=None):
    time.sleep(5)
    return "(Linux: Cevap otomatik okunamiyor. Claude Desktop'tan kontrol edin.)"


def ensure_claude_sidebar_open():
    logger.warning("Sidebar control bu platformda desteklenmiyor")
    return False


def set_claude_mode(mode):
    logger.warning("Mode degistirme bu platformda desteklenmiyor")
    return False


def set_claude_model(model_key, mode="code"):
    logger.warning("Model secimi bu platformda desteklenmiyor")
    return False


def set_claude_effort(effort_key):
    logger.warning("Effort secimi bu platformda desteklenmiyor")
    return False


def set_claude_permission_mode(mode_key):
    logger.warning("Permission mode secimi bu platformda desteklenmiyor")
    return False


def set_claude_extended_thinking(enabled):
    logger.warning("Extended thinking bu platformda desteklenmiyor")
    return False


def list_claude_chat_sessions(limit=10):
    logger.warning("Chat session listeleme bu platformda desteklenmiyor")
    return []


def read_visible_claude_chat_history(last_n=10):
    return "(Chat gecmisi bu platformda desteklenmiyor.)"


def focus_claude_input():
    logger.warning("Input focus bu platformda desteklenmiyor")
    return False


def detect_permission_prompt():
    return []


def click_permission_button(button_text):
    logger.warning("Permission click Windows disinda desteklenmiyor")
    return False


def click_new_session():
    return False

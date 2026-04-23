# core/system_tools.py
import pyautogui
import os
import datetime
import pyperclip
import sys
from PIL import ImageDraw
from core.data_manager import DataManager
from core.logger import log_crash, get_logger

logger = get_logger("system_tools")

pyautogui.FAILSAFE = os.environ.get("FAILSAFE_OFF", "").lower() != "true"


def _mouse_overlay_point(image_size):
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
        ("win", "l"): ["control", "command", "q"],
        ("winleft", "l"): ["control", "command", "q"],
        ("windows", "l"): ["control", "command", "q"],
    }
    MAC_KEY_ALIASES = {
        "cmd": "command",
        "command": "command",
        "ctrl": "command",
        "control": "command",
        "mac_ctrl": "control",
        "mac_control": "control",
        "win": "command",
        "winleft": "command",
        "windows": "command",
        "alt": "option",
        "option": "option",
    }
    DESKTOP_KEY_ALIASES = {
        "cmd": "ctrl",
        "command": "ctrl",
        "option": "alt",
        "win": "winleft",
        "windows": "winleft",
    }

    @staticmethod
    def _normalize_key_name(key_name):
        key = str(key_name or "").strip().lower()
        return SystemOps.KEY_ALIASES.get(key, key)

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
        """
        Fareyi belirtilen yöne hareket ettirir.
        Hızı her seferinde 'hotkeys.json' dosyasından canlı okur.
        """
        # HIZ AYARINI BURADA ÇEKİYORUZ
        step = DataManager.get_mouse_speed()

        # Eğer okuyamazsa güvenlik amacıyla 50 yap
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

    @staticmethod
    def take_screenshot():
        """Ekran görüntüsü alır ve imleci çizer."""
        try:
            if not os.path.exists("temp_screens"):
                os.makedirs("temp_screens")

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"temp_screens/scr_{timestamp}.png"

            screenshot = pyautogui.screenshot()

            try:
                mouse_x, mouse_y = _mouse_overlay_point(screenshot.size)
                draw = ImageDraw.Draw(screenshot)
                r = 10
                draw.ellipse(
                    (mouse_x - r, mouse_y - r, mouse_x + r, mouse_y + r),
                    outline="red",
                    width=3,
                )
                draw.ellipse(
                    (mouse_x - 2, mouse_y - 2, mouse_x + 2, mouse_y + 2), fill="red"
                )
            except Exception:
                pass

            screenshot.save(filename)
            logger.info(f"Screenshot alındı: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Screenshot hatası: {e}")
            crash_file = log_crash("system_tools.take_screenshot", str(e))
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
        """Yazılımı yeniden başlatır."""
        import sys
        import subprocess

        # Mevcut Python yolunu al (venv içindeki)
        python_path = sys.executable

        # Ana scriptin tam yolunu bul
        if hasattr(sys, "_MEIPASS"):
            # PyInstaller ile paketlenmişse
            script_path = sys.executable
        else:
            script_path = os.path.abspath(sys.argv[0])

        print("Sistem yeniden başlatılıyor...")

        # Argümanlarla birlikte yeniden başlat
        subprocess.Popen([python_path, script_path] + sys.argv[1:])
        sys.exit(0)

    @staticmethod
    def mouse_click(action="left"):
        if action == "left":
            pyautogui.click()
        elif action == "right":
            pyautogui.rightClick()
        elif action == "double":
            pyautogui.doubleClick()

    @staticmethod
    def press_key(key_name):
        try:
            pyautogui.press(SystemOps._normalize_key_name(key_name))
            return True
        except:
            return False

    @staticmethod
    def execute_hotkey(keys_list):
        """Tuş kombinasyonu (Hız ayarlı ve WinLeft düzeltmeli)"""
        try:
            corrected_keys = SystemOps.normalize_hotkey(keys_list)

            pyautogui.hotkey(*corrected_keys, interval=0.1)
            logger.debug(f"Hotkey: {corrected_keys}")
            return True
        except Exception as e:
            logger.error(f"Hotkey hatası: {e}")
            crash_file = log_crash("system_tools.execute_hotkey", str(e))
            return False

    @staticmethod
    def type_text(text):
        try:
            pyperclip.copy(text)
            mod_key = "command" if sys.platform == "darwin" else "ctrl"
            pyautogui.hotkey(mod_key, "v")
            logger.debug(f"Yazıldı: {text[:20]}...")
            return True
        except Exception as e:
            logger.error(f"Yazma hatası: {e}")
            crash_file = log_crash("system_tools.type_text", str(e))
            return False

# utils/installer.py
import subprocess
import sys
import importlib


def install_and_check():
    print("[SYSTEM] Checking libraries...")

    required_packages = {
        "telegram": "python-telegram-bot",
        "pyautogui": "pyautogui",
        "PIL": "Pillow",
        "dotenv": "python-dotenv",
        "pyperclip": "pyperclip",
        "loguru": "loguru",
        "qrcode": "qrcode",
    }

    # Platform-specific deps
    if sys.platform == "win32":
        required_packages["pywinauto"] = "pywinauto"

    missing = []

    print(" |- Scanning packages...")
    for lib_import, lib_install in required_packages.items():
        try:
            importlib.import_module(lib_import)
            print(f" |   [OK] {lib_install}")
        except ImportError:
            print(f" |   [X]  {lib_install} MISSING")
            missing.append(lib_install)

    if missing:
        print(f" |- {len(missing)} packages to install...")
        try:
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--trusted-host",
                    "pypi.org",
                    "--trusted-host",
                    "pypi.python.org",
                    "--trusted-host",
                    "files.pythonhosted.org",
                ]
                + missing
            )
            print(" \\- [SUCCESS] All packages installed.")
        except Exception as e:
            print(f" \\- [ERROR] Installation failed: {e}")
            sys.exit(1)
    else:
        print(" \\- All requirements already installed.")

    print("-" * 40)

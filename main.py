import asyncio
import os
import sys
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"


__version__ = "2.0.0 (AgentCockpit unified)"


def global_exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    try:
        from core.logger import log_crash

        crash_file = log_crash("main", str(exc_value), error_msg)
        print(f"[COKME] Hata dosyasi: {crash_file}")

        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
        token = os.getenv("TELEGRAM_TOKEN")
        raw_ids = os.getenv("ALLOWED_USER_ID", "")
        user_id = raw_ids.split(",")[0].strip() if raw_ids else None

        if token and user_id:
            from core.logger import notify_crash

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(
                        notify_crash(token, user_id, crash_file, str(exc_value))
                    )
                else:
                    loop.run_until_complete(
                        notify_crash(token, user_id, crash_file, str(exc_value))
                    )
            except Exception:
                pass
    except Exception:
        pass

    sys.__excepthook__(exc_type, exc_value, exc_traceback)


sys.excepthook = global_exception_handler


def is_legacy_mode(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    return any(arg in {"--legacy", "legacy"} for arg in args)


def is_venv():
    from launcher import is_venv as launcher_is_venv

    return launcher_is_venv()


def create_venv_and_restart():
    from launcher import create_venv_and_restart as launcher_create_venv_and_restart

    launcher_create_venv_and_restart(script_path=str(Path(__file__).resolve()))


def run_legacy_application():
    try:
        import pip_system_certs  # noqa: F401

        print("[SISTEM] SSL guvenlik zinciri aktif [OK]")
    except ImportError:
        print("[UYARI] pip_system_certs yuklenemedi. SSL hatalari alinabilir.")

    from utils.installer import install_and_check

    install_and_check()

    from core.bot_engine import run_bot

    print("[START] Legacy core bot aciliyor (--legacy)")
    run_bot()


def run_application(argv=None):
    if is_legacy_mode(argv):
        run_legacy_application()
        return

    from launcher import run_stack

    print("[START] AgentCockpit unified stack aciliyor")
    run_stack()


if __name__ == "__main__":
    if is_venv():
        run_application()
    else:
        create_venv_and_restart()

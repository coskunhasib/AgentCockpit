import asyncio
import os
import subprocess
import sys
import traceback
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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


def is_doctor_mode(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    return any(arg in {"--doctor", "doctor"} for arg in args)


def is_venv():
    return hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )


def _is_venv_valid(venv_dir):
    pyvenv_cfg = venv_dir / "pyvenv.cfg"
    if not pyvenv_cfg.exists():
        return False

    try:
        for line in pyvenv_cfg.read_text(encoding="utf-8").splitlines():
            if line.startswith("home = "):
                return Path(line.split("=", 1)[1].strip()).exists()
    except Exception:
        return False

    return False


def _bootstrap_without_launcher(script_path):
    venv_dir = PROJECT_ROOT / "venv"
    venv_python = (
        venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )

    print(f"[BOOTSTRAP] AgentCockpit hazirlaniyor... (PID: {os.getpid()})")
    print(f"[BOOTSTRAP] Surum: {__version__}")

    if venv_dir.exists() and not _is_venv_valid(venv_dir):
        print("[BOOTSTRAP] Venv gecersiz. Yeniden olusturuluyor...")
        import shutil

        shutil.rmtree(venv_dir, ignore_errors=True)

    if not venv_python.exists():
        subprocess.check_call([sys.executable, "-m", "venv", "venv"], cwd=PROJECT_ROOT)

    requirements_file = PROJECT_ROOT / "requirements.txt"
    try:
        subprocess.call(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=PROJECT_ROOT,
        )
        if requirements_file.exists():
            subprocess.check_call(
                [
                    str(venv_python),
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    str(requirements_file),
                    "--trusted-host",
                    "pypi.org",
                    "--trusted-host",
                    "pypi.python.org",
                    "--trusted-host",
                    "files.pythonhosted.org",
                ],
                cwd=PROJECT_ROOT,
            )
    except Exception as exc:
        print(f"[UYARI] Bagimlilik kurulumunda sorun: {exc}. Devam ediyorum.")

    subprocess.call([str(venv_python), script_path] + sys.argv[1:], cwd=PROJECT_ROOT)
    sys.exit()


def create_venv_and_restart():
    script_path = str(Path(__file__).resolve())
    try:
        from launcher import create_venv_and_restart as launcher_create_venv_and_restart

        launcher_create_venv_and_restart(script_path=script_path)
    except ModuleNotFoundError:
        _bootstrap_without_launcher(script_path)


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


def run_doctor():
    from core.runtime_compat import (
        apply_runtime_defaults,
        detect_runtime_compatibility,
        format_runtime_compatibility,
    )

    print("[DOCTOR] AgentCockpit uyumluluk kontrolu")
    report = apply_runtime_defaults(detect_runtime_compatibility())
    for line in format_runtime_compatibility(report):
        print(line)


def run_application(argv=None):
    if is_doctor_mode(argv):
        run_doctor()
        return

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

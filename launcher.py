import os
import subprocess
import sys
import time
import webbrowser


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"


__version__ = "2.0.0 (AgentCockpit unified launcher)"


def is_venv():
    return hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )


def is_venv_valid(venv_dir):
    pyvenv_cfg = os.path.join(venv_dir, "pyvenv.cfg")
    if not os.path.exists(pyvenv_cfg):
        return False

    try:
        with open(pyvenv_cfg, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("home = "):
                    python_home = line.split("=", 1)[1].strip()
                    return os.path.exists(python_home)
    except Exception:
        return False

    return False


def create_venv_and_restart(script_path=None):
    venv_dir = os.path.join(PROJECT_ROOT, "venv")
    if os.name == "nt":
        venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        venv_python = os.path.join(venv_dir, "bin", "python")

    print(f"[BOOTSTRAP] AgentCockpit hazirlaniyor... (PID: {os.getpid()})")
    print(f"[BOOTSTRAP] Surum: {__version__}")

    needs_recreate = False
    if os.path.exists(venv_dir):
        if not is_venv_valid(venv_dir):
            print("[BOOTSTRAP] Venv gecersiz. Yeniden olusturuluyor...")
            needs_recreate = True
            import shutil

            shutil.rmtree(venv_dir, ignore_errors=True)
    else:
        needs_recreate = True

    if needs_recreate or not os.path.exists(venv_python):
        subprocess.check_call([sys.executable, "-m", "venv", "venv"], cwd=PROJECT_ROOT)

    requirements_file = os.path.join(PROJECT_ROOT, "requirements.txt")
    try:
        subprocess.call(
            [venv_python, "-m", "pip", "install", "--upgrade", "pip"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if os.path.exists(requirements_file):
            subprocess.check_call(
                [
                    venv_python,
                    "-m",
                    "pip",
                    "install",
                    "-r",
                    requirements_file,
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

    restart_script = script_path or os.path.abspath(__file__)
    subprocess.call([venv_python, restart_script] + sys.argv[1:], cwd=PROJECT_ROOT)
    sys.exit()


def _bridge_health():
    from phone_bridge_client import PhoneBridgeClientError, get_bridge_base_url, get_bridge_health

    try:
        health = get_bridge_health()
        return True, get_bridge_base_url(), health
    except PhoneBridgeClientError as exc:
        return False, get_bridge_base_url(), str(exc)


def ensure_bridge_running():
    healthy, base_url, details = _bridge_health()
    if healthy:
        print(f"[PHONE] Mevcut bridge kullaniliyor: {base_url}")
        print(f"[PHONE] Pairing dashboard: {base_url}/pair")
        return None, True, base_url

    print(f"[PHONE] Bridge kapali gorunuyor ({details}). Baslatiliyor...")
    bridge_script = os.path.join(PROJECT_ROOT, "phone_bridge_server.py")
    process = subprocess.Popen(
        [sys.executable, bridge_script],
        cwd=PROJECT_ROOT,
    )

    for _ in range(20):
        time.sleep(0.35)
        healthy, base_url, details = _bridge_health()
        if healthy:
            print(f"[PHONE] Bridge hazir: {base_url}")
            print(f"[PHONE] Pairing dashboard: {base_url}/pair")
            return process, True, base_url
        if process.poll() is not None:
            break

    print("[PHONE] Bridge dogrulanamadi. Bot yine de aciliyor; telefon tarafi sonra toparlanabilir.")
    return process, False, base_url


def open_pairing_dashboard(base_url):
    if not base_url:
        return
    pairing_url = f"{base_url.rstrip('/')}/pair"
    try:
        webbrowser.open(pairing_url, new=2)
        print(f"[PHONE] Tarayici aciliyor: {pairing_url}")
    except Exception as exc:
        print(f"[PHONE] Tarayici otomatik acilamadi: {exc}")


def run_stack():
    try:
        import pip_system_certs  # noqa: F401
    except ImportError:
        pass

    from telegram_setup import ensure_telegram_setup

    if not ensure_telegram_setup(PROJECT_ROOT):
        print("[SETUP] Telegram kurulumu tamamlanamadi. Bot baslatilmiyor.")
        return

    from utils.installer import install_and_check

    install_and_check()

    bridge_process, bridge_ready, bridge_base_url = ensure_bridge_running()
    if bridge_ready:
        open_pairing_dashboard(bridge_base_url)

    try:
        from telegram_ux import run_bot

        print("[START] AgentCockpit stack aciliyor: phone bridge + Telegram UX")
        run_bot()
    finally:
        if bridge_process and bridge_process.poll() is None:
            print("[STOP] Launcher tarafindan acilan phone bridge kapatiliyor...")
            bridge_process.terminate()
            try:
                bridge_process.wait(timeout=5)
            except Exception:
                bridge_process.kill()


if __name__ == "__main__":
    if is_venv():
        run_stack()
    else:
        create_venv_and_restart()

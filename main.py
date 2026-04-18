# main.py
import sys
import os

# Windows UTF-8 environment
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

import subprocess
import time
import traceback
import asyncio
import codecs

# Version
__version__ = "1.2.0 (Portable Venv)"


def global_exception_handler(exc_type, exc_value, exc_traceback):
    """Global hata yakalayıcı - beklenmedik çökmeleri yakalar"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    try:
        from core.logger import log_crash

        crash_file = log_crash("main", str(exc_value), error_msg)
        print(f"[ÇÖKME] Hata dosyası: {crash_file}")

        # Telegram bildirimi
        from dotenv import load_dotenv

        load_dotenv()
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


def is_venv():
    """Kodun sanal ortamda çalışıp çalışmadığını kontrol eder."""
    return hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )


def is_venv_valid(venv_dir):
    """
    Sanal ortamın bu sistemde geçerli olup olmadığını kontrol eder.
    pyvenv.cfg içindeki Python yolunun mevcut olup olmadığına bakar.
    Bu taşınabilirlik için kritik - venv farklı bir PC'de oluşturulmuşsa False döner.
    """
    pyvenv_cfg = os.path.join(venv_dir, "pyvenv.cfg")

    if not os.path.exists(pyvenv_cfg):
        return False

    try:
        with open(pyvenv_cfg, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("home = "):
                    python_home = line.split("=", 1)[1].strip()
                    # Python home dizini mevcut mu kontrol et
                    if not os.path.exists(python_home):
                        print(
                            f"[BOOTSTRAP] Venv geçersiz: Python yolu bulunamadı -> {python_home}"
                        )
                        return False
                    return True
    except Exception as e:
        print(f"[BOOTSTRAP] pyvenv.cfg okunamadı: {e}")
        return False

    return False


def create_venv_and_restart():
    """Sanal ortam oluşturur, SSL yamasını kurar ve scripti oradan yeniden başlatır."""
    venv_dir = os.path.join(os.getcwd(), "venv")

    # Windows için Python yolu
    if os.name == "nt":
        venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        venv_python = os.path.join(venv_dir, "bin", "python")

    print(f"[BOOTSTRAP] Sistem kontrol ediliyor... (PID: {os.getpid()})")
    print(f"[BOOTSTRAP] Sürüm: {__version__}")

    # 1. Sanal Ortam Kontrolü - TAŞINABİLİRLİK DESTEĞİ
    needs_recreate = False

    if os.path.exists(venv_dir):
        if not is_venv_valid(venv_dir):
            print(
                "[BOOTSTRAP] Taşınabilirlik: Venv farklı bir PC'de oluşturulmuş. Yeniden oluşturuluyor..."
            )
            needs_recreate = True
            # Eski venv'i sil
            import shutil

            try:
                shutil.rmtree(venv_dir)
                print("[BOOTSTRAP] Eski venv silindi.")
            except Exception as e:
                print(f"[HATA] Venv silinemedi: {e}")
                sys.exit(1)
        else:
            print("[BOOTSTRAP] Mevcut sanal ortam geçerli.")
    else:
        needs_recreate = True
        print("[BOOTSTRAP] Sanal ortam (venv) bulunamadı.")

    # 2. Sanal Ortam Oluşturma
    if needs_recreate or not os.path.exists(venv_python):
        print("[BOOTSTRAP] Yeni sanal ortam oluşturuluyor...")
        try:
            subprocess.check_call([sys.executable, "-m", "venv", "venv"])
            print("[BOOTSTRAP] Venv oluşturuldu.")
        except Exception as e:
            print(f"[HATA] Venv oluşturulamadı: {e}")
            sys.exit(1)

    # 3. TÜM Bağımlılıkları BOOTSTRAP Aşamasında Kur (SSL sorunu için kritik)
    print("[BOOTSTRAP] Bağımlılıklar kontrol ediliyor...")
    requirements_file = os.path.join(os.getcwd(), "requirements.txt")

    try:
        # Önce pip'i güncelle
        subprocess.call(
            [venv_python, "-m", "pip", "install", "--upgrade", "pip"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # requirements.txt varsa tüm bağımlılıkları kur
        if os.path.exists(requirements_file):
            print("[BOOTSTRAP] requirements.txt bulundu. Paketler kuruluyor...")
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
                ]
            )
            print("[BOOTSTRAP] Tüm bağımlılıklar kuruldu.")
        else:
            # requirements.txt yoksa sadece SSL yamasını kur
            subprocess.check_call(
                [
                    venv_python,
                    "-m",
                    "pip",
                    "install",
                    "pip_system_certs",
                    "--trusted-host",
                    "pypi.org",
                    "--trusted-host",
                    "pypi.python.org",
                    "--trusted-host",
                    "files.pythonhosted.org",
                ],
                stdout=subprocess.DEVNULL,
            )
            print("[BOOTSTRAP] SSL Yaması kuruldu.")
    except Exception as e:
        print(f"[UYARI] Bağımlılık kurulumunda sorun: {e}. Yine de devam ediliyor.")

    # 3. Sanal Ortam ile Yeniden Başlatma
    print(f"[BOOTSTRAP] Yetki devrediliyor -> {venv_python}")
    print("-" * 50)

    # Mevcut argümanları koruyarak yeni python ile çalıştır
    script_path = os.path.abspath(__file__)
    subprocess.call([venv_python, script_path] + sys.argv[1:])
    sys.exit()


def run_application():
    """Asıl uygulama mantığı buradadır (Sanal ortam içindeyiz)."""

    # 1. SSL Yamasını Devreye Al (pip_system_certs otomatik olarak pip'e inject olur)
    try:
        import pip_system_certs

        print("[SİSTEM] SSL Güvenlik Zinciri: pip-system-certs aktif [OK]")
    except ImportError:
        print("[UYARI] pip_system_certs yüklenemedi. SSL hataları alınabilir.")

    # 2. Diğer Kütüphaneleri Kontrol Et (Utils modülünden)
    from utils.installer import install_and_check

    install_and_check()

    # 3. Botu Başlat
    try:
        from core.bot_engine import run_bot

        run_bot()
    except ImportError as e:
        print(f"[KRİTİK] Bot başlatılamadı: {e}")


if __name__ == "__main__":
    if is_venv():
        # Eğer zaten sanal ortamdaysak uygulamayı çalıştır
        run_application()
    else:
        # Değilsek, ortamı kur ve yeniden başlat
        create_venv_and_restart()

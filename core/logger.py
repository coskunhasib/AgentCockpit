import os
import sys
import traceback
import asyncio
from datetime import datetime
from loguru import logger
from telegram import Bot

LOG_DIR = "logs"
CRASH_DIR = "logs/crashes"
APP_LOG_FILE = os.path.join(LOG_DIR, f"app_{os.getpid()}.log")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CRASH_DIR, exist_ok=True)

logger.remove()

# Windows stderr emoji fix: wrap with utf-8 to avoid charmap crash
_stderr_sink = sys.stderr
if sys.platform == "win32":
    import io
    _stderr_sink = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logger.add(
    _stderr_sink,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    level="INFO",
    colorize=True,
)

logger.add(
    APP_LOG_FILE,
    rotation="00:00",
    retention="1 day",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
    encoding="utf-8",
    enqueue=True,
)


def log_crash(module, error, exc_info=None):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    crash_file = f"{CRASH_DIR}/crash_{timestamp}.log"

    with open(crash_file, "w", encoding="utf-8") as f:
        f.write(f"=== ÇÖKME RAPORU ===\n")
        f.write(f"Tarih: {datetime.now()}\n")
        f.write(f"Modül: {module}\n")
        f.write(f"Hata: {error}\n")
        if exc_info:
            f.write(f"\nTraceback:\n{exc_info}")

    logger.critical(f"ÇÖKME [{module}]: {error}")
    return crash_file


def get_logger(name):
    return logger.bind(name=name)


async def notify_crash(token, user_id, crash_file, error_msg):
    """Kullanıcıya crash bildirimi gönder"""
    try:
        bot = Bot(token=token)
        message = f"⚠️ **HATA TESPİT EDİLDİ**\n\n"
        message += f"📅 Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"❌ Hata: {error_msg}\n"
        message += f"📁 Dosya: {crash_file}"

        await bot.send_message(chat_id=user_id, text=message)
        logger.info(f"Crash bildirimi gönderildi: {user_id}")
    except Exception as e:
        logger.error(f"Crash bildirimi gönderilemedi: {e}")

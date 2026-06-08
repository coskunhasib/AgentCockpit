import asyncio
import importlib
import io
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageDraw, ImageStat
from telegram import InputMediaPhoto
from telegram.error import BadRequest

from core.logger import get_logger
from core.runtime_compat import desktop_automation_help_text


logger = get_logger("phone_wan_transport")
_PYAUTOGUI = None

DEFAULT_INTERVAL_SEC = max(0.8, float(os.getenv("PHONE_WAN_INTERVAL_SEC", "1.4")))
DEFAULT_MAX_WIDTH = max(640, int(os.getenv("PHONE_WAN_MAX_WIDTH", "1280")))
DEFAULT_QUALITY = max(25, min(90, int(os.getenv("PHONE_WAN_QUALITY", "45"))))
DEFAULT_CHANGE_THRESHOLD = max(
    1.0, float(os.getenv("PHONE_WAN_CHANGE_THRESHOLD", "5.0"))
)
DEFAULT_IDLE_REFRESH_SEC = max(10.0, float(os.getenv("PHONE_WAN_IDLE_REFRESH_SEC", "20")))


@dataclass
class SnapshotFrame:
    image_bytes: bytes
    width: int
    height: int
    signature: Image.Image


@dataclass
class WanSnapshotSession:
    chat_id: int
    task: asyncio.Task
    message_id: "int | None" = None
    started_at: float = field(default_factory=time.time)
    last_sent_at: float = 0.0
    last_change_score: float = 0.0
    signature: "Image.Image | None" = None


_sessions: dict[int, WanSnapshotSession] = {}


def _safe_error_text(error):
    text = str(error or "").strip()
    text = re.sub(r"(/private)?/var/folders/\S+", "<temp-file>", text)
    text = re.sub(r"(/tmp|/var/tmp)/\S+", "<temp-file>", text)
    text = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot<redacted>", text)
    text = re.sub(r"token=[A-Za-z0-9:_-]+", "token=<redacted>", text)
    text = " ".join(text.split())
    return text[:300]


def _get_pyautogui():
    global _PYAUTOGUI
    if _PYAUTOGUI is not None:
        return _PYAUTOGUI

    try:
        _PYAUTOGUI = importlib.import_module("pyautogui")
        return _PYAUTOGUI
    except Exception as exc:
        logger.error(f"WAN pyautogui kullanilamiyor: {exc}")
        return None


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


def _capture_frame(max_width=DEFAULT_MAX_WIDTH, quality=DEFAULT_QUALITY):
    screenshot = None
    capture_error = None
    if sys.platform == "darwin":
        screenshot = _capture_with_screencapture()
        if screenshot is None:
            capture_error = RuntimeError("screencapture ile ekran alinmadi")
    if screenshot is None:
        pyautogui = _get_pyautogui()
        if not pyautogui:
            raise RuntimeError(desktop_automation_help_text())
        try:
            screenshot = pyautogui.screenshot()
        except Exception as exc:
            capture_error = exc
            raise RuntimeError(
                f"Ekran goruntusu olusturulamadi. Asil hata: {_safe_error_text(exc)}"
            ) from exc

    try:
        mouse_x, mouse_y = _mouse_overlay_point(screenshot.size)
        draw = ImageDraw.Draw(screenshot)
        radius = 10
        draw.ellipse(
            (mouse_x - radius, mouse_y - radius, mouse_x + radius, mouse_y + radius),
            outline="#ff4d4d",
            width=3,
        )
    except Exception:
        pass

    if screenshot.width > max_width:
        ratio = max_width / screenshot.width
        screenshot = screenshot.resize(
            (max_width, int(screenshot.height * ratio)),
            Image.LANCZOS,
        )

    signature = screenshot.convert("L").resize((96, 54), Image.BILINEAR)
    buffer = io.BytesIO()
    screenshot.convert("RGB").save(
        buffer,
        format="JPEG",
        quality=quality,
        optimize=True,
    )
    return SnapshotFrame(
        image_bytes=buffer.getvalue(),
        width=screenshot.width,
        height=screenshot.height,
        signature=signature,
    )


def _capture_with_screencapture():
    if sys.platform != "darwin":
        return None

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            temp_path = tmp.name

        result = subprocess.run(
            ["screencapture", "-x", "-t", "jpg", temp_path],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if result.returncode != 0:
            return None
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) <= 0:
            return None

        with Image.open(temp_path) as captured:
            return captured.convert("RGB")
    except Exception:
        return None
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _change_score(previous, current):
    if previous is None or current is None:
        return 100.0
    diff = ImageChops.difference(previous, current)
    score = ImageStat.Stat(diff).mean[0]
    return float(score)


def _photo_file(frame_bytes):
    payload = io.BytesIO(frame_bytes)
    payload.name = "agentcockpit-wan.jpg"
    payload.seek(0)
    return payload


def _caption(frame, score):
    stamp = time.strftime("%H:%M:%S")
    return (
        "AgentCockpit WAN\n"
        f"{frame.width}x{frame.height} | {stamp}\n"
        f"Degisim: {score:.1f}"
    )


async def _publish_frame(bot, session, frame, score):
    caption = _caption(frame, score)
    photo = _photo_file(frame.image_bytes)

    if session.message_id is None:
        message = await bot.send_photo(
            chat_id=session.chat_id,
            photo=photo,
            caption=caption,
        )
        session.message_id = message.message_id
        return

    media = InputMediaPhoto(media=photo, caption=caption)
    try:
        await bot.edit_message_media(
            chat_id=session.chat_id,
            message_id=session.message_id,
            media=media,
        )
    except BadRequest:
        message = await bot.send_photo(
            chat_id=session.chat_id,
            photo=_photo_file(frame.image_bytes),
            caption=caption,
        )
        session.message_id = message.message_id


async def _run_loop(bot, session):
    try:
        while True:
            frame = await asyncio.to_thread(_capture_frame)
            score = _change_score(session.signature, frame.signature)
            now = time.time()
            should_send = (
                session.message_id is None
                or score >= DEFAULT_CHANGE_THRESHOLD
                or (now - session.last_sent_at) >= DEFAULT_IDLE_REFRESH_SEC
            )

            if should_send:
                await _publish_frame(bot, session, frame, score)
                session.signature = frame.signature
                session.last_sent_at = now
                session.last_change_score = score

            await asyncio.sleep(DEFAULT_INTERVAL_SEC)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        safe_error = _safe_error_text(exc)
        logger.warning(f"WAN snapshot loop failed: {safe_error}")
        try:
            await bot.send_message(
                chat_id=session.chat_id,
                text=f"WAN snapshot oturumu durdu: {safe_error}",
            )
        except Exception:
            pass
    finally:
        current = _sessions.get(session.chat_id)
        if current is session:
            _sessions.pop(session.chat_id, None)


async def start_wan_session(bot, chat_id):
    existing = _sessions.get(chat_id)
    if existing and not existing.task.done():
        return False

    session = WanSnapshotSession(chat_id=chat_id, task=None)
    task = asyncio.create_task(_run_loop(bot, session))
    session.task = task
    _sessions[chat_id] = session
    return True


async def stop_wan_session(chat_id):
    session = _sessions.get(chat_id)
    if not session:
        return False
    session.task.cancel()
    try:
        await session.task
    except asyncio.CancelledError:
        pass
    return True


def is_wan_session_active(chat_id):
    session = _sessions.get(chat_id)
    return bool(session and not session.task.done())


def get_wan_session_status(chat_id):
    session = _sessions.get(chat_id)
    if not session or session.task.done():
        return "Kapali"

    age = int(time.time() - session.started_at)
    minutes, seconds = divmod(age, 60)
    uptime = f"{minutes} dk {seconds} sn" if minutes else f"{seconds} sn"
    return f"Acik | {uptime} | Son degisim: {session.last_change_score:.1f}"

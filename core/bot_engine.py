# core/bot_engine.py
import asyncio
import logging
import os
import sys
import time
import traceback

import core.codex_bridge as codex_bridge
import core.codex_state as codex_state
from dotenv import load_dotenv
from telegram import (
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    constants,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    Updater,
    filters,
)

from core.claude_ui_config import (
    CLAUDE_EFFORT_LABELS,
    CLAUDE_MODE_BUTTONS,
    CLAUDE_MODEL_LABELS,
    CLAUDE_PERMISSION_LABELS,
    CLAUDE_UI_CONFIG_METADATA,
    CLAUDE_UI_CONFIG_WARNINGS,
    CLAUDE_TAB_MODEL_OPTIONS,
)
from core.claude_capabilities import (
    capability_enabled,
    get_capability_summary_lines,
    tab_supports_history_read,
    tab_supports_session_listing,
)
from core.claude_state import (
    clear_permission_cache,
    clear_session_cache,
    get_permission_cache,
    get_session_cache,
    set_state_key,
    set_permission_cache,
    set_session_cache,
)
from core.claude_bridge import (
    clear_session,
    get_cwd,
    get_profile_summary,
    get_transport_mode,
    get_session_title,
    get_tab,
    list_sessions,
    read_session_history,
    run_claude,
    set_cwd,
    set_effort,
    set_extended_thinking,
    set_model,
    set_permission_mode,
    set_session,
    set_tab,
    split_message,
    sync_claude_settings,
)
from core.data_manager import DataManager
from core.logger import get_logger, log_crash, notify_crash
from core.platform_utils import (
    click_new_session,
    click_permission_button,
    find_claude_window,
    focus_window,
    open_session_in_desktop,
)
from core.system_tools import SystemOps

logger = get_logger("bot_engine")
_codex_delivery_tasks = {}
_UPDATER_POLLING_CLEANUP_STATE = {}


def _patch_ptb_updater_slot_bug():
    cleanup_attr = "_Updater__polling_cleanup_cb"
    if hasattr(Updater, cleanup_attr):
        return

    def _get_cleanup_cb(instance):
        return _UPDATER_POLLING_CLEANUP_STATE.get(id(instance))

    def _set_cleanup_cb(instance, value):
        _UPDATER_POLLING_CLEANUP_STATE[id(instance)] = value

    setattr(Updater, cleanup_attr, property(_get_cleanup_cb, _set_cleanup_cb))
    logger.info("Applied PTB Updater slot workaround for Python 3.13 compatibility")

if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

for warning in CLAUDE_UI_CONFIG_WARNINGS:
    logger.warning(f"Claude UI config uyarisi: {warning}")

logger.info(
    "Claude capability matrix: "
    + ", ".join(get_capability_summary_lines(transport_mode=get_transport_mode()))
)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_IDS = set(
    uid.strip() for uid in os.getenv("ALLOWED_USER_ID", "").split(",") if uid.strip()
)

BUTTON_MAIN_ANTIGRAVITY = "AgentCockpit"
BUTTON_MAIN_CLAUDE = "Claude Code"
BUTTON_MAIN_CODEX = "Codex"
BUTTON_MAIN_BACK = {"Ana Menu", "Ana Men\u00fc"}

BUTTON_CLAUDE_SESSIONS = {"Session Sec", "Session Se\u00e7"}
BUTTON_CLAUDE_NEW = {"Yeni Session"}
BUTTON_CLAUDE_TAB = {"Sekme"}
BUTTON_CLAUDE_MODEL = {"Model"}
BUTTON_CLAUDE_EFFORT = {"Effort"}
BUTTON_CLAUDE_PERMISSION = {"Izin Modu", "\u0130zin Modu"}
BUTTON_CLAUDE_THINKING = {"Thinking", "Extended Thinking", "Extended thinking"}
BUTTON_CLAUDE_STATUS = {"Durum"}
BUTTON_SCREENSHOT = {"Ekran Al"}

BUTTON_DISPLAY_LABELS = {
    "AgentCockpit": "🖥️ AgentCockpit",
    "Claude Code": "🤖 Claude Code",
    "Codex": "🧠 Codex",
    "Ekran Al": "📸 Ekran Al",
    "Durum": "📊 Durum",
    "Session Sec": "📋 Session Sec",
    "Yeni Session": "➕ Yeni Session",
    "Sekme": "🧭 Sekme",
    "Model": "🧠 Model",
    "Effort": "⚙️ Effort",
    "Izin Modu": "🔐 Izin Modu",
    "Thinking": "💭 Thinking",
    "PC Restart": "🔄 PC Restart",
    "Bot Restart": "♻️ Bot Restart",
    "Sol Tik": "🖱️ Sol Tik",
    "Sag Tik": "🖱️ Sag Tik",
    "Yukari": "⬆️ Yukari",
    "Asagi": "⬇️ Asagi",
    "Sol": "⬅️ Sol",
    "Sag": "➡️ Sag",
    "Enter": "↩️ Enter",
    "Space": "␣ Space",
    "Esc": "⎋ Esc",
    "Bir Sey Yaz...": "⌨️ Bir Sey Yaz...",
    "Ana Menu": "🏠 Ana Menu",
    "Telefon": "📱 Telefon",
}
BUTTON_CANONICAL_LABELS = {
    display: label for label, display in BUTTON_DISPLAY_LABELS.items()
}

CLAUDE_TAB_OPTIONS = [(key, CLAUDE_MODE_BUTTONS[key]) for key in ("chat", "cowork", "code")]
CLAUDE_CODE_MODEL_OPTIONS = [
    (key, CLAUDE_MODEL_LABELS[key]) for key in CLAUDE_TAB_MODEL_OPTIONS["code"]
]
CLAUDE_CONVERSATION_MODEL_OPTIONS = [
    (key, CLAUDE_MODEL_LABELS[key]) for key in CLAUDE_TAB_MODEL_OPTIONS["chat"]
]
CLAUDE_EFFORT_OPTIONS = list(CLAUDE_EFFORT_LABELS.items())
CLAUDE_PERMISSION_OPTIONS = list(CLAUDE_PERMISSION_LABELS.items())
CLAUDE_THINKING_OPTIONS = [
    (True, "Acik"),
    (False, "Kapali"),
]


def _state_key_from_chat_id(chat_id):
    return str(chat_id) if chat_id is not None else "default"


def _supports(feature_name):
    return capability_enabled(feature_name, transport_mode=get_transport_mode())


def _supports_session_listing(tab=None):
    return tab_supports_session_listing(
        tab or get_tab(), transport_mode=get_transport_mode()
    )


def _supports_history_read(tab=None):
    return tab_supports_history_read(
        tab or get_tab(), transport_mode=get_transport_mode()
    )


def button_label(label):
    if str(label).startswith("Hotkey "):
        return f"⚡ {label}"
    return BUTTON_DISPLAY_LABELS.get(label, label)


def canonical_button_label(label):
    raw = (label or "").strip()
    if raw in BUTTON_CANONICAL_LABELS:
        return BUTTON_CANONICAL_LABELS[raw]
    if raw in BUTTON_DISPLAY_LABELS:
        return raw
    if raw.startswith("⚡ "):
        rest = raw[2:].strip()
        if rest.startswith("Hotkey "):
            return rest
    parts = raw.split(" ", 1)
    if len(parts) == 2:
        rest = parts[1].strip()
        if rest in BUTTON_DISPLAY_LABELS or rest.startswith("Hotkey "):
            return rest
    return raw


def _display_keyboard(rows):
    return [[button_label(label) for label in row] for row in rows]


def _save_user_id_to_env(user_id):
    """Append user ID to the .env ALLOWED_USER_ID field."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    lines = []
    found = False
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        pass

    new_lines = []
    for line in lines:
        if line.startswith("ALLOWED_USER_ID="):
            existing = line.strip().split("=", 1)[1]
            ids = [uid.strip() for uid in existing.split(",") if uid.strip()]
            if user_id not in ids:
                ids.append(user_id)
            new_lines.append(f"ALLOWED_USER_ID={','.join(ids)}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"ALLOWED_USER_ID={user_id}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    ALLOWED_IDS.add(user_id)
    logger.info(f"Yeni kullanici kaydedildi: {user_id}")


async def check_auth(update: Update):
    user_id = str(update.effective_user.id)

    if not ALLOWED_IDS:
        _save_user_id_to_env(user_id)
        name = update.effective_user.first_name or "Kullanici"
        await update.message.reply_text(
            f"Hosgeldin {name}! Sahip olarak kaydedildin.\nID: {user_id}"
        )
        return True

    if user_id not in ALLOWED_IDS:
        logger.warning(
            f"Yetkisiz erisim: {user_id} ({update.effective_user.first_name})"
        )
        await update.message.reply_text(f"Yetkisiz Erisim! ID: {user_id}")
        return False
    return True


def get_mode_keyboard():
    return ReplyKeyboardMarkup(
        _display_keyboard([[BUTTON_MAIN_ANTIGRAVITY, BUTTON_MAIN_CLAUDE], [BUTTON_MAIN_CODEX]]),
        resize_keyboard=True,
    )


def get_dynamic_keyboard():
    keyboard = [
        ["Ekran Al", "PC Restart"],
        ["Bot Restart"],
        ["Sol Tik", "Yukari", "Sag Tik"],
        ["Sol", "Asagi", "Sag"],
        ["Enter", "Space", "Esc"],
        ["Bir Sey Yaz..."],
    ]
    custom_hotkeys = DataManager.get_hotkeys()
    temp_row = []
    for name in custom_hotkeys:
        temp_row.append(f"Hotkey {name}")
        if len(temp_row) == 2:
            keyboard.append(temp_row)
            temp_row = []
    if temp_row:
        keyboard.append(temp_row)
    keyboard.append(["Ana Menu"])
    return ReplyKeyboardMarkup(_display_keyboard(keyboard), resize_keyboard=True)


def get_claude_keyboard():
    tab = get_tab()
    keyboard = [["Ekran Al", "Durum"]]

    session_row = []
    if _supports_session_listing(tab):
        session_row.append("Session Sec")
    session_row.append("Yeni Session")
    keyboard.append(session_row)

    selector_row = []
    if _supports("tab_selection"):
        selector_row.append("Sekme")
    if _supports("model_selection"):
        selector_row.append("Model")
    if selector_row:
        keyboard.append(selector_row)

    control_row = []
    if tab == "code":
        if _supports("code_effort"):
            control_row.append("Effort")
        if _supports("permission_mode"):
            control_row.append("Izin Modu")
    else:
        if _supports("extended_thinking"):
            control_row.append("Thinking")
    if control_row:
        keyboard.append(control_row)

    keyboard.append(["Ana Menu"])
    return ReplyKeyboardMarkup(_display_keyboard(keyboard), resize_keyboard=True)


def get_codex_keyboard():
    keyboard = [
        ["Ekran Al", "Durum"],
        ["Session Sec", "Yeni Session"],
        ["Ana Menu"],
    ]
    return ReplyKeyboardMarkup(_display_keyboard(keyboard), resize_keyboard=True)


def get_model_options_for_tab(tab=None):
    return (
        CLAUDE_CODE_MODEL_OPTIONS
        if (tab or get_tab()) == "code"
        else CLAUDE_CONVERSATION_MODEL_OPTIONS
    )


def get_codex_session_inline_keyboard():
    codex_state.clear_session_cache()
    session_cache = {}
    sessions = codex_bridge.list_sessions(15)
    buttons = []
    lines = []
    for index, session in enumerate(sessions, start=1):
        workspace = os.path.basename((session.get("cwd", "") or "").rstrip("\\/")) or "Genel"
        label_title = session.get("display_title") or session["title"]
        button_label = f"{index}. {workspace}"
        session_id = session.get("id") or session["title"]
        cb_data = f"codses:{session_id}"
        session_cache[cb_data] = {
            "id": session.get("id"),
            "title": session["title"],
            "display_title": label_title,
            "cwd": session.get("cwd", ""),
            "source": session.get("source", "codex"),
        }
        buttons.append([InlineKeyboardButton(button_label, callback_data=cb_data)])
        lines.append(f"{index}. [{workspace}] {label_title}")

    codex_state.set_session_cache(session_cache)
    buttons.append([InlineKeyboardButton("Yeni Session", callback_data="codses:new")])
    summary = (
        "Mevcut Codex session'lar:\n\n" + "\n".join(lines)
        if lines
        else "Listelenebilir Codex session bulunamadi. Yeni Session ile devam edebilirsin."
    )
    return InlineKeyboardMarkup(buttons), len(sessions), summary


def _resolve_codex_session_info(callback_data):
    session_cache = codex_state.get_session_cache()
    if callback_data in session_cache:
        return session_cache[callback_data]

    if not callback_data.startswith("codses:"):
        return None

    token = callback_data.split(":", 1)[1]
    if not token:
        return None

    for info in session_cache.values():
        session_id = info.get("id") or ""
        if session_id.startswith(token):
            return info

    for session in codex_bridge.list_sessions(30):
        session_id = session.get("id") or ""
        if session_id.startswith(token):
            return {
                "id": session.get("id"),
                "title": session.get("title"),
                "display_title": session.get("display_title") or session.get("title"),
                "cwd": session.get("cwd", ""),
                "source": session.get("source", "codex"),
            }

    return None


def _build_inline_keyboard(prefix, options):
    rows = []
    for key, label in options:
        rows.append([InlineKeyboardButton(label, callback_data=f"{prefix}:{key}")])
    return InlineKeyboardMarkup(rows)


def get_session_inline_keyboard(mode=None):
    clear_session_cache()
    session_cache = {}
    active_tab = mode or get_tab()
    sessions = list_sessions(8, mode=active_tab) if _supports_session_listing(active_tab) else []
    buttons = []
    for session in sessions:
        short = session["title"][:35]
        session_id = session.get("id") or session["title"]
        cb_data = f"ses:{session_id[:20]}"
        session_cache[cb_data] = {
            "id": session.get("id"),
            "title": session["title"],
            "cwd": session.get("cwd", ""),
            "source": session.get("source", "code"),
        }
        buttons.append([InlineKeyboardButton(short, callback_data=cb_data)])

    set_session_cache(session_cache)
    buttons.append([InlineKeyboardButton("Yeni Session", callback_data="ses:new")])
    return InlineKeyboardMarkup(buttons), len(sessions)


async def _send_claude_panel(update_or_chat, context, include_sessions=False, chat_id=None):
    text = "Claude hazir.\n\n" + get_profile_summary()
    config_path = CLAUDE_UI_CONFIG_METADATA["active_path"]
    text += f"\nConfig: {os.path.basename(config_path)}"
    if hasattr(update_or_chat, "message") and update_or_chat.message:
        await update_or_chat.message.reply_text(text, reply_markup=get_claude_keyboard())
        if include_sessions and not get_session_title():
            if _supports_session_listing(get_tab()):
                session_markup, session_count = get_session_inline_keyboard(get_tab())
                await update_or_chat.message.reply_text(
                    "Mevcut session'lar:" if session_count else "Bu sekmede listelenebilir session bulunamadi. Yeni Session ile devam edebilirsin.",
                    reply_markup=session_markup,
                )
            else:
                await update_or_chat.message.reply_text(
                    "Bu platformda mevcut sekme icin session listeleme desteklenmiyor. Yeni Session ile devam edebilirsin.",
                    reply_markup=get_claude_keyboard(),
                )
        return

    target_chat = chat_id if chat_id is not None else update_or_chat
    await context.bot.send_message(
        chat_id=target_chat,
        text=text,
        reply_markup=get_claude_keyboard(),
    )
    if include_sessions and not get_session_title():
        if _supports_session_listing(get_tab()):
            session_markup, session_count = get_session_inline_keyboard(get_tab())
            await context.bot.send_message(
                chat_id=target_chat,
                text="Mevcut session'lar:" if session_count else "Bu sekmede listelenebilir session bulunamadi. Yeni Session ile devam edebilirsin.",
                reply_markup=session_markup,
            )
        else:
            await context.bot.send_message(
                chat_id=target_chat,
                text="Bu platformda mevcut sekme icin session listeleme desteklenmiyor. Yeni Session ile devam edebilirsin.",
                reply_markup=get_claude_keyboard(),
            )


async def _send_codex_panel(update_or_chat, context, include_sessions=False, chat_id=None):
    text = "Codex hazir.\n\n" + codex_bridge.get_profile_summary()
    if hasattr(update_or_chat, "message") and update_or_chat.message:
        await update_or_chat.message.reply_text(text, reply_markup=get_codex_keyboard())
        if include_sessions and not codex_bridge.get_session_title():
            session_markup, session_count, session_text = get_codex_session_inline_keyboard()
            await update_or_chat.message.reply_text(
                session_text,
                reply_markup=session_markup,
            )
        return

    target_chat = chat_id if chat_id is not None else update_or_chat
    await context.bot.send_message(
        chat_id=target_chat,
        text=text,
        reply_markup=get_codex_keyboard(),
    )
    if include_sessions and not codex_bridge.get_session_title():
        session_markup, session_count, session_text = get_codex_session_inline_keyboard()
        await context.bot.send_message(
            chat_id=target_chat,
            text=session_text,
            reply_markup=session_markup,
        )


async def post_init(application: Application):
    commands = [
        ("start", "Mod secim menusu"),
        ("hiz", "Fare hizini ayarla"),
        ("yaz", "Metin yazdir"),
        ("tus", "Kisayol tusu gonder"),
        ("ekle", "Yeni buton ekle"),
        ("sil", "Buton sil"),
        ("cwd", "Claude calisma dizini"),
    ]
    await application.bot.set_my_commands(commands)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    context.user_data.clear()
    await update.message.reply_text("Mod secin:", reply_markup=get_mode_keyboard())


async def set_speed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    if context.args:
        try:
            DataManager.set_mouse_speed(int(context.args[0]))
            await update.message.reply_text(f"Hiz {context.args[0]} yapildi.")
        except (ValueError, TypeError):
            await update.message.reply_text("Sadece sayi girin.")
    else:
        context.user_data["waiting_for"] = "hiz"
        await update.message.reply_text(
            "Hizi kac yapayim? (Sadece sayiyi gonder)",
            reply_markup=ForceReply(selective=True),
        )


async def type_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    if context.args:
        SystemOps.type_text(" ".join(context.args))
        await update.message.reply_text("Yazildi.")
    else:
        context.user_data["waiting_for"] = "yaz"
        await update.message.reply_text(
            "Ne yazmami istersin?", reply_markup=ForceReply(selective=True)
        )


async def manual_hotkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    if context.args:
        SystemOps.execute_hotkey(context.args)
        await update.message.reply_text(f"Basildi: {' '.join(context.args)}")
    else:
        context.user_data["waiting_for"] = "tus"
        await update.message.reply_text(
            "Hangi tuslara basayim? (Orn: alt f4)",
            reply_markup=ForceReply(selective=True),
        )


async def add_hotkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    if len(context.args) >= 2:
        DataManager.add_hotkey(context.args[0], context.args[1:])
        await update.message.reply_text(
            f"'{context.args[0]}' eklendi.",
            reply_markup=get_dynamic_keyboard(),
        )
    else:
        context.user_data["waiting_for"] = "ekle"
        await update.message.reply_text(
            "Once buton adi, sonra tuslar. Ornek: Kopyala ctrl c",
            reply_markup=ForceReply(selective=True),
        )


async def remove_hotkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    if context.args:
        if DataManager.remove_hotkey(context.args[0]):
            await update.message.reply_text("Silindi.", reply_markup=get_dynamic_keyboard())
    else:
        context.user_data["waiting_for"] = "sil"
        await update.message.reply_text(
            "Silinecek butonun adi ne?", reply_markup=ForceReply(selective=True)
        )


async def cwd_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_state_key(_state_key_from_chat_id(update.effective_chat.id if update.effective_chat else None))
    codex_state.set_state_key(
        _state_key_from_chat_id(update.effective_chat.id if update.effective_chat else None)
    )
    if not await check_auth(update):
        return
    if context.args:
        new_cwd = " ".join(context.args)
        if context.user_data.get("mode") == "codex":
            codex_bridge.set_cwd(new_cwd)
        else:
            set_cwd(new_cwd)
        await update.message.reply_text(f"CWD: `{new_cwd}`")
    else:
        current_cwd = codex_bridge.get_cwd() if context.user_data.get("mode") == "codex" else get_cwd()
        await update.message.reply_text(f"CWD: `{current_cwd}`")


async def _send_permission_buttons(update_or_chat, context, buttons, chat_id=None):
    clear_permission_cache()
    permission_cache = {}
    keyboard = []
    for index, button_text in enumerate(buttons):
        cb = f"perm:{index}"
        permission_cache[cb] = button_text
        keyboard.append([InlineKeyboardButton(button_text[:40], callback_data=cb)])

    set_permission_cache(permission_cache)
    text = "Claude izin istiyor:"
    if hasattr(update_or_chat, "message") and update_or_chat.message:
        await update_or_chat.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    target = chat_id if chat_id is not None else update_or_chat
    await context.bot.send_message(
        chat_id=target, text=text, reply_markup=InlineKeyboardMarkup(keyboard)
    )


def _get_option_label(options, key):
    for item_key, label in options:
        if item_key == key:
            return label
    return key


def _has_running_codex_task(chat_id):
    task = _codex_delivery_tasks.get(str(chat_id))
    return bool(task and not task.done())


def _clear_finished_codex_task(chat_id, task):
    key = str(chat_id)
    current = _codex_delivery_tasks.get(key)
    if current is task:
        _codex_delivery_tasks.pop(key, None)


async def _run_codex_and_deliver(bot, chat_id, prompt):
    task = asyncio.current_task()
    try:
        result = await codex_bridge.run_codex(prompt)
        if result is None:
            await bot.send_message(
                chat_id=chat_id,
                text="Codex istegi islenmedi ya da tekrar eden bir gonderim olarak atlandi.",
                reply_markup=get_codex_keyboard(),
            )
            return
        logger.info(f"[CODEX] Arka plan cevap ({len(result)} karakter): {result[:200]}")
        for chunk in split_message(result):
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                reply_markup=get_codex_keyboard(),
            )
    except Exception as exc:
        logger.exception(f"Codex arka plan teslim hatasi: {exc}")
        await bot.send_message(
            chat_id=chat_id,
            text=f"Codex sonucu gonderirken hata oldu: {exc}",
            reply_markup=get_codex_keyboard(),
        )
    finally:
        _clear_finished_codex_task(chat_id, task)


async def _apply_claude_setting(query, setter, value, options, context=None):
    if not setter(value):
        await query.edit_message_text("Secim kaydedilemedi.")
        return

    synced, sync_message = await asyncio.to_thread(sync_claude_settings)
    label = _get_option_label(options, value)
    status = "canli uygulandi" if synced else "kaydedildi"
    detail = sync_message if synced else "Claude acikken sonraki promptta uygulanacak."
    await query.edit_message_text(f"{label} secildi, {status}.\n{detail}")
    if context:
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=get_profile_summary(),
            reply_markup=get_claude_keyboard(),
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_state_key(_state_key_from_chat_id(update.effective_chat.id if update.effective_chat else None))
    codex_state.set_state_key(
        _state_key_from_chat_id(update.effective_chat.id if update.effective_chat else None)
    )
    if not await check_auth(update):
        return

    raw_msg = update.message.text
    msg = canonical_button_label(raw_msg)
    mode = context.user_data.get("mode")
    logger.info(f"[MSG] [{mode or 'menu'}] Gelen: {raw_msg} -> {msg}")

    if msg in {
        BUTTON_MAIN_ANTIGRAVITY,
        "🖥️ AgentCockpit",
        "Antigravity",
        "🖥️ Antigravity",
    }:
        context.user_data["mode"] = "antigravity"
        await update.message.reply_text(
            "Remote Cockpit hazir!", reply_markup=get_dynamic_keyboard()
        )
        return

    if msg in {BUTTON_MAIN_CLAUDE, "🤖 Claude Code"}:
        context.user_data["mode"] = "claude"
        await _send_claude_panel(
            update, context, include_sessions=not bool(get_session_title())
        )
        return

    if msg in BUTTON_MAIN_BACK or msg in {"🔙 Ana Menu", "🔙 Ana Menü"}:
        context.user_data.clear()
        await update.message.reply_text("Mod secin:", reply_markup=get_mode_keyboard())
        return

    if msg == BUTTON_MAIN_CODEX:
        context.user_data["mode"] = "codex"
        await _send_codex_panel(
            update,
            context,
            include_sessions=not bool(codex_bridge.get_session_title()),
        )
        return

    if mode == "claude":
        if msg in BUTTON_SCREENSHOT or msg == "📸 Ekran Al":
            status = await update.message.reply_text("Screenshot aliniyor...")
            path = SystemOps.take_screenshot()
            try:
                if path:
                    with open(path, "rb") as photo_file:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id, photo=photo_file
                        )
                else:
                    await update.message.reply_text("Screenshot alinamadi.")
            finally:
                if path:
                    SystemOps.clean_up(path)
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=status.message_id
                )
            return

        if msg in BUTTON_CLAUDE_SESSIONS or msg == "📋 Session Sec":
            if not _supports_session_listing(get_tab()):
                await update.message.reply_text(
                    "Bu platformda mevcut sekme icin session listeleme desteklenmiyor. Yeni Session kullanabilir veya baska bir sekmeye gecebilirsin.",
                    reply_markup=get_claude_keyboard(),
                )
                return
            session_markup, session_count = get_session_inline_keyboard(get_tab())
            await update.message.reply_text(
                "Session sec:"
                if session_count
                else "Bu sekmede listelenebilir session bulunamadi. Yeni Session ile devam edebilirsin.",
                reply_markup=session_markup,
            )
            return

        if msg in BUTTON_CLAUDE_NEW or msg == "🆕 Yeni Session":
            clear_session()
            if get_transport_mode() == "cli":
                await update.message.reply_text(
                    "Yeni session secildi. Sonraki prompt Claude CLI tarafinda yeni bir oturum baslatacak.",
                    reply_markup=get_claude_keyboard(),
                )
                return
            handle = find_claude_window()
            if handle and focus_window(handle):
                if click_new_session():
                    await asyncio.to_thread(sync_claude_settings)
                    await update.message.reply_text(
                        "Yeni session acildi.", reply_markup=get_claude_keyboard()
                    )
                else:
                    await update.message.reply_text(
                        "Yeni session acilamadi.", reply_markup=get_claude_keyboard()
                    )
            else:
                await update.message.reply_text(
                    "Claude Desktop bulunamadi.", reply_markup=get_claude_keyboard()
                )
            return

        if msg in BUTTON_CLAUDE_TAB or msg == "🧭 Sekme":
            await update.message.reply_text(
                "Sekme sec:",
                reply_markup=_build_inline_keyboard("cfg:tab", CLAUDE_TAB_OPTIONS),
            )
            return

        if msg in BUTTON_CLAUDE_MODEL or msg == "🧠 Model":
            if not _supports("model_selection"):
                await update.message.reply_text(
                    "Model secimi bu platform/transport kombinasyonunda desteklenmiyor.",
                    reply_markup=get_claude_keyboard(),
                )
                return
            await update.message.reply_text(
                "Model sec:",
                reply_markup=_build_inline_keyboard(
                    "cfg:model", get_model_options_for_tab(get_tab())
                ),
            )
            return

        if msg in BUTTON_CLAUDE_EFFORT or msg == "⚙️ Effort":
            if not _supports("code_effort"):
                await update.message.reply_text(
                    "Effort secimi bu platform/transport kombinasyonunda desteklenmiyor.",
                    reply_markup=get_claude_keyboard(),
                )
                return
            if get_tab() != "code":
                await update.message.reply_text(
                    "Bu sekmede Effort yok. Burada sadece Extended thinking kullaniliyor.",
                    reply_markup=get_claude_keyboard(),
                )
                return
            await update.message.reply_text(
                "Effort sec:",
                reply_markup=_build_inline_keyboard("cfg:effort", CLAUDE_EFFORT_OPTIONS),
            )
            return

        if msg in BUTTON_CLAUDE_THINKING:
            if not _supports("extended_thinking"):
                await update.message.reply_text(
                    "Extended thinking bu platform/transport kombinasyonunda desteklenmiyor.",
                    reply_markup=get_claude_keyboard(),
                )
                return
            if get_tab() == "code":
                await update.message.reply_text(
                    "Extended thinking sadece Chat ve Cowork sekmelerinde kullaniliyor.",
                    reply_markup=get_claude_keyboard(),
                )
                return
            await update.message.reply_text(
                "Thinking sec:",
                reply_markup=_build_inline_keyboard(
                    "cfg:thinking", CLAUDE_THINKING_OPTIONS
                ),
            )
            return

        if msg in BUTTON_CLAUDE_PERMISSION or msg in {"🔐 Izin Modu", "🔐 İzin Modu"}:
            if not _supports("permission_mode"):
                await update.message.reply_text(
                    "Izin modu secimi bu platform/transport kombinasyonunda desteklenmiyor.",
                    reply_markup=get_claude_keyboard(),
                )
                return
            if get_tab() != "code":
                await update.message.reply_text(
                    "Izin modu sadece Code sekmesinde gecerli.",
                    reply_markup=get_claude_keyboard(),
                )
                return
            await update.message.reply_text(
                "Izin modu sec:",
                reply_markup=_build_inline_keyboard("cfg:perm", CLAUDE_PERMISSION_OPTIONS),
            )
            return

        if msg in BUTTON_CLAUDE_STATUS or msg == "📊 Durum":
            await update.message.reply_text(
                get_profile_summary(), reply_markup=get_claude_keyboard()
            )
            return

        waiting = context.user_data.get("waiting_for")
        if waiting == "cwd":
            set_cwd(msg)
            context.user_data.pop("waiting_for", None)
            await update.message.reply_text(
                f"CWD: `{msg}`", reply_markup=get_claude_keyboard()
            )
            return

        logger.info(f"[CLAUDE] Kullanici prompt: {msg}")
        status = await update.message.reply_text("Claude'a gonderildi, cevap bekleniyor...")
        result = await run_claude(msg)

        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id, message_id=status.message_id
            )
        except Exception:
            pass

        if result is None:
            return

        if isinstance(result, dict) and result.get("type") == "permission":
            if not _supports("runtime_permission_buttons"):
                await update.message.reply_text(
                    "Claude izin istedi ama bu platformda Telegram uzerinden anlik izin butonu desteklenmiyor. Claude penceresinden manuel onay ver.",
                    reply_markup=get_claude_keyboard(),
                )
                return
            await _send_permission_buttons(update, context, result["buttons"])
            return

        logger.info(f"[CLAUDE] Cevap ({len(result)} karakter): {result[:200]}")
        for chunk in split_message(result):
            await update.message.reply_text(chunk, reply_markup=get_claude_keyboard())
        return

    if mode == "codex":
        if msg in BUTTON_SCREENSHOT or msg == "ğŸ“¸ Ekran Al":
            status = await update.message.reply_text("Screenshot aliniyor...")
            path = SystemOps.take_screenshot()
            try:
                if path:
                    with open(path, "rb") as photo_file:
                        await context.bot.send_photo(
                            chat_id=update.effective_chat.id, photo=photo_file
                        )
                else:
                    await update.message.reply_text("Screenshot alinamadi.")
            finally:
                if path:
                    SystemOps.clean_up(path)
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=status.message_id
                )
            return

        if msg in BUTTON_CLAUDE_SESSIONS or msg == "ğŸ“‹ Session Sec":
            session_markup, session_count, session_text = get_codex_session_inline_keyboard()
            await update.message.reply_text(session_text, reply_markup=session_markup)
            return

        if msg in BUTTON_CLAUDE_NEW or msg == "ğŸ†• Yeni Session":
            codex_bridge.clear_session()
            handle = codex_bridge.ensure_codex_window()
            if handle and codex_bridge.focus_codex_window(handle):
                if codex_bridge.click_new_session():
                    await update.message.reply_text(
                        "Yeni Codex session acildi.", reply_markup=get_codex_keyboard()
                    )
                else:
                    await update.message.reply_text(
                        "Yeni Codex session acilamadi.", reply_markup=get_codex_keyboard()
                    )
            else:
                await update.message.reply_text(
                    "Codex Desktop bulunamadi.", reply_markup=get_codex_keyboard()
                )
            return

        if msg in BUTTON_CLAUDE_STATUS or msg == "ğŸ“Š Durum":
            await update.message.reply_text(
                codex_bridge.get_profile_summary(), reply_markup=get_codex_keyboard()
            )
            return

        waiting = context.user_data.get("waiting_for")
        if waiting == "cwd":
            codex_bridge.set_cwd(msg)
            context.user_data.pop("waiting_for", None)
            await update.message.reply_text(
                f"CWD: `{msg}`", reply_markup=get_codex_keyboard()
            )
            return

        chat_id = update.effective_chat.id
        if _has_running_codex_task(chat_id):
            await update.message.reply_text(
                "Codex su an baska bir istek uzerinde calisiyor. Is bitince sonucu buraya otomatik birakacagim.",
                reply_markup=get_codex_keyboard(),
            )
            return

        logger.info(f"[CODEX] Kullanici prompt: {msg}")
        status = await update.message.reply_text(
            "Codex'e gonderildi. Uretim tamamlaninca sonucu sana otomatik mesaj olarak atacagim.",
            reply_markup=get_codex_keyboard(),
        )
        task = asyncio.create_task(_run_codex_and_deliver(context.bot, chat_id, msg))
        _codex_delivery_tasks[str(chat_id)] = task
        return

    waiting = context.user_data.get("waiting_for")
    if waiting:
        keyboard = get_dynamic_keyboard()

        if waiting == "hiz":
            try:
                DataManager.set_mouse_speed(int(msg))
                await update.message.reply_text(
                    f"Hiz {msg} olarak ayarlandi.", reply_markup=keyboard
                )
            except Exception:
                await update.message.reply_text(
                    "Lutfen sayi girin.", reply_markup=keyboard
                )

        elif waiting == "yaz":
            SystemOps.type_text(msg)
            await update.message.reply_text(f"Yazildi: {msg}", reply_markup=keyboard)

        elif waiting == "tus":
            keys = msg.split()
            SystemOps.execute_hotkey(keys)
            await update.message.reply_text(f"Basildi: {msg}", reply_markup=keyboard)

        elif waiting == "ekle":
            parts = msg.split()
            if len(parts) >= 2:
                name = parts[0]
                keys = parts[1:]
                DataManager.add_hotkey(name, keys)
                await update.message.reply_text(
                    f"'{name}' butonu eklendi.", reply_markup=get_dynamic_keyboard()
                )
            else:
                await update.message.reply_text(
                    "Hatali format. Islem iptal edildi.", reply_markup=keyboard
                )

        elif waiting == "sil":
            if DataManager.remove_hotkey(msg):
                await update.message.reply_text(
                    f"'{msg}' silindi.", reply_markup=get_dynamic_keyboard()
                )
            else:
                await update.message.reply_text("Bulunamadi.", reply_markup=keyboard)

        context.user_data.pop("waiting_for", None)
        return

    if msg.startswith("Hotkey "):
        name = msg.replace("Hotkey ", "")
        keys = DataManager.get_hotkeys().get(name)
        if keys:
            SystemOps.execute_hotkey(keys)
            await update.message.reply_text(f"{name} tetiklendi.", quote=False)
        return

    if msg in BUTTON_SCREENSHOT or msg == "📸 Ekran Al":
        status = await update.message.reply_text("Screenshot aliniyor...")
        path = SystemOps.take_screenshot()
        if path:
            try:
                with open(path, "rb") as photo_file:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id, photo=photo_file
                    )
            finally:
                SystemOps.clean_up(path)
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id, message_id=status.message_id
                )

    elif msg in {"PC Restart", "🔄 PC Restart"}:
        await update.message.reply_text("PC yeniden baslatiliyor...")
        SystemOps.restart_pc()
    elif msg in {"Bot Restart", "♻️ Bot Restart"}:
        await update.message.reply_text("Yazilim yeniden basliyor...")
        SystemOps.restart_script()
    elif msg in {"Yukari", "⬆️ Yukari"}:
        SystemOps.mouse_move("up")
    elif msg in {"Asagi", "⬇️ Asagi"}:
        SystemOps.mouse_move("down")
    elif msg in {"Sol", "⬅️ Sol"}:
        SystemOps.mouse_move("left")
    elif msg in {"Sag", "➡️ Sag"}:
        SystemOps.mouse_move("right")
    elif msg in {"Sol Tik", "🖱️ Sol Tik"}:
        SystemOps.mouse_click("left")
        await update.message.reply_text("Sol tik.", quote=False)
    elif msg in {"Sag Tik", "🖱️ Sag Tik"}:
        SystemOps.mouse_click("right")
        await update.message.reply_text("Sag tik.", quote=False)
    elif msg in {"Enter", "⌨️ Enter"}:
        SystemOps.press_key("enter")
    elif msg in {"Space", "⌨️ Space"}:
        SystemOps.press_key("space")
    elif msg in {"Esc", "⌨️ Esc"}:
        SystemOps.press_key("esc")
    elif msg in {"Bir Sey Yaz...", "📝 Bir Sey Yaz..."}:
        context.user_data["waiting_for"] = "yaz"
        await update.message.reply_text(
            "Ne yazayim?", reply_markup=ForceReply(selective=True)
        )


async def update_software(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_auth(update):
        return
    document = update.message.document
    raw_name = update.message.caption if update.message.caption else document.file_name
    safe_name = os.path.basename(raw_name)
    updates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "updates")
    os.makedirs(updates_dir, exist_ok=True)
    target_path = os.path.join(updates_dir, safe_name)
    try:
        file_info = await document.get_file()
        await file_info.download_to_drive(custom_path=target_path)
        await update.message.reply_text(f"Guncellendi: `{safe_name}`\nBot restart yap.")
    except Exception as exc:
        await update.message.reply_text(f"Hata: {exc}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    set_state_key(
        _state_key_from_chat_id(query.message.chat_id if query and query.message else None)
    )
    codex_state.set_state_key(
        _state_key_from_chat_id(query.message.chat_id if query and query.message else None)
    )
    await query.answer()
    data = query.data
    logger.info(f"[CALLBACK] data={data}")

    user_id = str(query.from_user.id)
    if ALLOWED_IDS and user_id not in ALLOWED_IDS:
        return

    permission_cache = get_permission_cache()
    if data.startswith("perm:") and data in permission_cache:
        button_text = permission_cache[data]
        await query.edit_message_text(f"Tiklandi: {button_text}")

        clicked = await asyncio.to_thread(click_permission_button, button_text)
        if not clicked:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Button Desktop'ta bulunamadi: {button_text}",
            )
            return

        from core.claude_bridge import continue_after_permission

        status = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Izin verildi, cevap bekleniyor...",
        )
        result = await continue_after_permission()
        try:
            await context.bot.delete_message(
                chat_id=query.message.chat_id, message_id=status.message_id
            )
        except Exception:
            pass

        if isinstance(result, dict) and result.get("type") == "permission":
            if not _supports("runtime_permission_buttons"):
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="Claude yeni bir izin istedi ama bu platformda Telegram uzerinden anlik izin butonu desteklenmiyor. Claude penceresinden manuel onay ver.",
                )
                return
            await _send_permission_buttons(
                query.message.chat_id,
                context,
                result["buttons"],
                chat_id=query.message.chat_id,
            )
            return

        if result:
            for chunk in split_message(result):
                await context.bot.send_message(chat_id=query.message.chat_id, text=chunk)
        return

    if data == "ses:new":
        clear_session()
        if get_transport_mode() == "cli":
            await query.edit_message_text(
                "Yeni session secildi. Sonraki prompt Claude CLI tarafinda yeni bir oturum baslatacak."
            )
            return
        handle = find_claude_window()
        if handle and focus_window(handle):
            if click_new_session():
                await asyncio.to_thread(sync_claude_settings)
                await query.edit_message_text("Yeni session acildi.")
            else:
                await query.edit_message_text("Yeni session acilamadi.")
        else:
            await query.edit_message_text("Claude Desktop bulunamadi.")
        return

    session_cache = get_session_cache()
    if data.startswith("ses:") and data in session_cache:
        info = session_cache[data]
        sid = info["id"]
        title = info["title"]
        session_cwd = info.get("cwd", "")
        set_session(sid, title=title)
        if session_cwd:
            set_cwd(session_cwd)
        context.user_data["mode"] = "claude"
        transport = get_transport_mode()

        await query.edit_message_text(f"{title}\nSession aciliyor...")
        opened = False
        if transport == "desktop":
            opened = await asyncio.to_thread(open_session_in_desktop, title, get_tab())
            await asyncio.to_thread(sync_claude_settings)

        status_text = f"Session: {title}\n"
        if transport == "desktop":
            status_text += (
                "Claude Desktop'ta acildi." if opened else "Desktop'ta acilamadi."
            )
        elif transport == "cli":
            status_text += "Claude CLI icin aktif oturum olarak secildi."
        else:
            status_text += "Aktif oturum olarak kaydedildi, ancak canli transport bulunamadi."
        await query.edit_message_text(status_text)

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=get_profile_summary(),
            reply_markup=get_claude_keyboard(),
        )

        if sid and _supports_history_read(get_tab()):
            history = read_session_history(session_id=sid, last_n=10)
            for chunk in split_message(history):
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=chunk,
                    parse_mode=constants.ParseMode.HTML,
                )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Bu sekme/platform kombinasyonu icin yerel transcript okuma desteklenmiyor. Session acildi ve yeni mesajlar gondermeye hazir.",
            )
        return

    if data == "codses:new":
        codex_bridge.clear_session()
        handle = codex_bridge.ensure_codex_window()
        if handle and codex_bridge.focus_codex_window(handle):
            if codex_bridge.click_new_session():
                await query.edit_message_text("Yeni Codex session acildi.")
            else:
                await query.edit_message_text("Yeni Codex session acilamadi.")
        else:
            await query.edit_message_text("Codex Desktop bulunamadi.")
        return

    if data.startswith("codses:"):
        info = _resolve_codex_session_info(data)
        if not info:
            session_markup, session_count, session_text = get_codex_session_inline_keyboard()
            await query.edit_message_text(
                "Codex session listesi eskimis ya da bulunamadi.\n\n" + session_text,
                reply_markup=session_markup if session_count else None,
            )
            return

        sid = info["id"]
        title = info.get("display_title") or info["title"]
        session_cwd = info.get("cwd", "")
        codex_bridge.set_session(sid, title=title)
        if session_cwd:
            codex_bridge.set_cwd(session_cwd)
        context.user_data["mode"] = "codex"

        await query.edit_message_text(f"{title}\nCodex session aciliyor...")
        opened = await asyncio.to_thread(
            codex_bridge.open_session_in_desktop, title, session_cwd
        )
        status_text = f"Session: {title}\n"
        status_text += "Codex Desktop'ta acildi." if opened else "Desktop'ta acilamadi."
        await query.edit_message_text(status_text)

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=codex_bridge.get_profile_summary(),
            reply_markup=get_codex_keyboard(),
        )

        if sid:
            history = codex_bridge.read_session_history(session_id=sid, last_n=10)
            for chunk in split_message(history):
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=chunk,
                    parse_mode=constants.ParseMode.HTML,
                )
        return

    if data.startswith("cfg:tab:"):
        await _apply_claude_setting(
            query,
            set_tab,
            data.split(":")[-1],
            CLAUDE_TAB_OPTIONS,
            context=context,
        )
        return

    if data.startswith("cfg:model:"):
        if not _supports("model_selection"):
            await query.edit_message_text("Model secimi bu platform/transport kombinasyonunda desteklenmiyor.")
            return
        await _apply_claude_setting(
            query,
            set_model,
            data.split(":")[-1],
            get_model_options_for_tab(get_tab()),
            context=context,
        )
        return

    if data.startswith("cfg:effort:"):
        if not _supports("code_effort"):
            await query.edit_message_text("Effort secimi bu platform/transport kombinasyonunda desteklenmiyor.")
            return
        await _apply_claude_setting(
            query,
            set_effort,
            data.split(":")[-1],
            CLAUDE_EFFORT_OPTIONS,
            context=context,
        )
        return

    if data.startswith("cfg:perm:"):
        if not _supports("permission_mode"):
            await query.edit_message_text("Izin modu secimi bu platform/transport kombinasyonunda desteklenmiyor.")
            return
        await _apply_claude_setting(
            query,
            set_permission_mode,
            data.split(":")[-1],
            CLAUDE_PERMISSION_OPTIONS,
            context=context,
        )
        return

    if data.startswith("cfg:thinking:"):
        if not _supports("extended_thinking"):
            await query.edit_message_text("Extended thinking bu platform/transport kombinasyonunda desteklenmiyor.")
            return
        await _apply_claude_setting(
            query,
            set_extended_thinking,
            data.split(":")[-1].lower() == "true",
            CLAUDE_THINKING_OPTIONS,
            context=context,
        )
        return


LOCK_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot.lock")


def _cleanup_lock():
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(LOCK_FILE)
    except Exception:
        pass


def _kill_old_instances():
    from core.platform_utils import kill_process

    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                old_pid = int(f.read().strip())
            if old_pid != os.getpid():
                kill_process(old_pid)
                logger.info(f"Eski bot process kapatildi: PID {old_pid}")
                time.sleep(2)
        except (ValueError, OSError):
            pass

    with open(LOCK_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    import atexit
    import signal

    atexit.register(_cleanup_lock)

    def _signal_handler(sig, frame):
        _cleanup_lock()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGBREAK, _signal_handler)
        except (AttributeError, OSError):
            pass


def run_bot():
    global restart_counter
    restart_counter = 0
    max_restart = 3

    _patch_ptb_updater_slot_bug()

    if not TOKEN:
        logger.error("TOKEN bulunamadi!")
        print("HATA: Token yok.")
        return

    _kill_old_instances()
    logger.info("Bot baslatiliyor...")

    try:
        import httpx

        httpx.post(
            f"https://api.telegram.org/bot{TOKEN}/deleteWebhook",
            params={"drop_pending_updates": "true"},
            timeout=10,
        )
        logger.info("Telegram cache temizlendi (drop_pending_updates)")
        time.sleep(1)
    except Exception as exc:
        logger.warning(f"Cache temizleme atlandi: {exc}")

    while restart_counter < max_restart:
        try:
            app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

            app.add_handler(CommandHandler("start", start))
            app.add_handler(CommandHandler("hiz", set_speed_command))
            app.add_handler(CommandHandler("yaz", type_command))
            app.add_handler(CommandHandler("tus", manual_hotkey_command))
            app.add_handler(CommandHandler("ekle", add_hotkey_command))
            app.add_handler(CommandHandler("sil", remove_hotkey_command))
            app.add_handler(CommandHandler("cwd", cwd_command))

            app.add_handler(CallbackQueryHandler(handle_callback))
            app.add_handler(MessageHandler(filters.Document.ALL, update_software))
            app.add_handler(
                MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
            )

            logger.info("AgentCockpit baslatildi")
            print("AgentCockpit baslatildi...")
            app.run_polling()

        except Exception as exc:
            from telegram.error import Conflict

            if isinstance(exc, Conflict):
                restart_counter += 1
                logger.warning(
                    f"Baska bot calisiyor ({restart_counter}/{max_restart}). 30s bekleniyor..."
                )
                print(
                    f"[UYARI] Conflict ({restart_counter}/{max_restart}). 30s bekleniyor..."
                )
                time.sleep(30)
                if restart_counter >= max_restart:
                    logger.critical("Conflict cozulemedi. Durduruluyor.")
                    break
                continue

            restart_counter += 1
            crash_file = log_crash("bot_engine", str(exc), traceback.format_exc())
            logger.error(f"Bot coktu ({restart_counter}/{max_restart}): {exc}")

            try:
                first_id = next(iter(ALLOWED_IDS), None)
                if first_id:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(
                            notify_crash(TOKEN, first_id, crash_file, str(exc))
                        )
                    else:
                        loop.run_until_complete(
                            notify_crash(TOKEN, first_id, crash_file, str(exc))
                        )
            except Exception as notify_err:
                logger.error(f"Bildirim hatasi: {notify_err}")

            if restart_counter < max_restart:
                logger.warning(
                    f"Yeniden baslatiliyor... ({restart_counter}/{max_restart})"
                )
                print(f"[HATA] Bot coktu: {exc}")
                print("5 saniye icinde yeniden baslatiliyor...")
                time.sleep(5)
            else:
                logger.critical("Bot 3 kez ust uste coktu. Durduruluyor.")
                print("Bot 3 kez coktu. Durduruluyor.")
                break

import asyncio
import json
import os
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import core.bot_engine as legacy
import core.claude_bridge as claude_bridge
import core.claude_state as claude_state
import core.codex_bridge as codex_bridge
import core.codex_state as codex_state
from phone_bridge_client import (
    PhoneBridgeClientError,
    create_phone_link,
    get_bridge_base_url,
    get_bridge_health,
)
from phone_wan_transport import (
    get_wan_session_status,
    is_wan_session_active,
    start_wan_session,
    stop_wan_session,
)
from phone_runtime_config import PHONE_NOTIFICATION_STATE_FILE


_ORIGINAL_HANDLE_MESSAGE = legacy.handle_message
_ORIGINAL_HANDLE_CALLBACK = legacy.handle_callback
_ORIGINAL_CLAUDE_PROFILE_SUMMARY = legacy.get_profile_summary
_ORIGINAL_CODEX_PROFILE_SUMMARY = codex_bridge.get_profile_summary
_ORIGINAL_GET_MODE_KEYBOARD = legacy.get_mode_keyboard
_ORIGINAL_GET_DYNAMIC_KEYBOARD = legacy.get_dynamic_keyboard
_ORIGINAL_GET_CLAUDE_KEYBOARD = legacy.get_claude_keyboard
_ORIGINAL_GET_CODEX_KEYBOARD = legacy.get_codex_keyboard
_ORIGINAL_POST_INIT = legacy.post_init

_CTX_CLAUDE_READY = "ux_claude_session_ready"
_CTX_CODEX_READY = "ux_codex_session_ready"
_PATCHED = False

BUTTON_PHONE = "Telefon"
PHONE_CALLBACK_OPTIONS = (
    ("0", "Yeni Link"),
)


def _set_provider_ready(context, provider, ready):
    key = _CTX_CLAUDE_READY if provider == "claude" else _CTX_CODEX_READY
    context.user_data[key] = bool(ready)


def _clear_provider_ready(context, provider):
    key = _CTX_CLAUDE_READY if provider == "claude" else _CTX_CODEX_READY
    context.user_data.pop(key, None)


def _has_provider_context(context, provider):
    if provider == "claude":
        return bool(
            claude_bridge.get_session_title()
            or context.user_data.get(_CTX_CLAUDE_READY, False)
        )
    return bool(
        codex_bridge.get_session_title()
        or context.user_data.get(_CTX_CODEX_READY, False)
    )


def _format_last_activity(value):
    if value in (None, "", 0):
        return ""

    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        else:
            text = str(value).strip()
            if text.isdigit():
                dt = datetime.fromtimestamp(float(text) / 1000.0, tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%d.%m %H:%M")
    except Exception:
        return str(value)


def _workspace_label(cwd, fallback="Genel"):
    value = (cwd or "").rstrip("\\/")
    if not value:
        return fallback
    return os.path.basename(value) or value


def _transport_label(value):
    mapping = {
        "desktop": "Desktop UI",
        "cli": "CLI",
        "none": "Yok",
    }
    return mapping.get(value, value)


def _keyboard_rows(markup):
    rows = []
    for row in getattr(markup, "keyboard", []) or []:
        rows.append([getattr(button, "text", str(button)) for button in row])
    return rows


def _add_phone_row(markup):
    rows = _keyboard_rows(markup)
    if not rows:
        rows = [[legacy.button_label(BUTTON_PHONE)]]
    elif not any(legacy.canonical_button_label(cell) == BUTTON_PHONE for row in rows for cell in row):
        insert_at = len(rows)
        if rows and any(legacy.canonical_button_label(cell) in legacy.BUTTON_MAIN_BACK for cell in rows[-1]):
            insert_at = max(0, len(rows) - 1)
        rows.insert(insert_at, [legacy.button_label(BUTTON_PHONE)])
    return legacy.ReplyKeyboardMarkup(rows, resize_keyboard=True)


def get_mode_keyboard():
    return _add_phone_row(_ORIGINAL_GET_MODE_KEYBOARD())


def get_dynamic_keyboard():
    return _add_phone_row(_ORIGINAL_GET_DYNAMIC_KEYBOARD())


def get_claude_keyboard():
    return _add_phone_row(_ORIGINAL_GET_CLAUDE_KEYBOARD())


def get_codex_keyboard():
    return _add_phone_row(_ORIGINAL_GET_CODEX_KEYBOARD())


def _phone_bridge_status_text(chat_id=None):
    base_url = get_bridge_base_url()
    lines = [
        "Telefon UX",
        f"Bridge: {base_url}",
    ]
    try:
        health = get_bridge_health()
        lines.append(f"Durum: Hazir ({health.get('screen', '?')})")
        if health.get("session_unlimited"):
            lines.append("Varsayilan Link: Sinirsiz")
        else:
            lines.append(
                f"Varsayilan Link: {health.get('session_minutes', '?')} dk"
            )
        if health.get("wan_pwa_available"):
            lines.append("Uzak PWA: Hazir")
            lines.append(f"Public URL: {health.get('public_url')}")
        elif health.get("public_tunnel_enabled"):
            lines.append(f"Uzak PWA: {health.get('public_tunnel_status', 'hazirlaniyor')}")
            if health.get("public_tunnel_error"):
                lines.append(f"Uzak Hata: {health.get('public_tunnel_error')}")
        else:
            lines.append("Uzak PWA: Kapali")
    except PhoneBridgeClientError as exc:
        lines.append("Durum: Erisilemiyor")
        lines.append(f"Neden: {exc}")
    if os.getenv("PHONE_ADMIN_TOKEN") or os.getenv("PHONE_TOKEN"):
        lines.append("Admin Token: Tanimli")
    else:
        lines.append("Admin Token: Eksik")
    if chat_id is not None:
        lines.append(f"WAN Snapshot: {get_wan_session_status(chat_id)}")
    return "\n".join(lines)


def _phone_link_markup(link_payload, *, chat_id=None):
    lan_urls = list(link_payload.get("lan_urls") or [])
    if not lan_urls and link_payload.get("lan_url"):
        lan_urls = [link_payload["lan_url"]]
    rows = []
    wan_url = link_payload.get("wan_url") or ""
    if wan_url:
        rows.append([InlineKeyboardButton("Uzak Ac", url=wan_url)])
    rows.append(
        [
            InlineKeyboardButton("Yerel Ac", url=lan_urls[0] if lan_urls else link_payload["lan_url"]),
            InlineKeyboardButton("Local", url=link_payload["local_url"]),
        ]
    )
    if len(lan_urls) > 1:
        extra_row = []
        for index, url in enumerate(lan_urls[1:3], start=2):
            extra_row.append(InlineKeyboardButton(f"LAN {index}", url=url))
        if extra_row:
            rows.append(extra_row)
    rows.append(
        [
            InlineKeyboardButton(label, callback_data=f"phone:new:{minutes}")
            for minutes, label in PHONE_CALLBACK_OPTIONS
        ]
    )
    if chat_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    "WAN Kapat" if is_wan_session_active(chat_id) else "WAN Baslat",
                    callback_data="phone:wan:stop" if is_wan_session_active(chat_id) else "phone:wan:start",
                )
            ]
        )
    rows.append([InlineKeyboardButton("Durum", callback_data="phone:status")])
    return InlineKeyboardMarkup(rows)


def _phone_status_markup(chat_id=None):
    rows = [
        [
            InlineKeyboardButton(label, callback_data=f"phone:new:{minutes}")
            for minutes, label in PHONE_CALLBACK_OPTIONS
        ]
    ]
    if chat_id is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    "WAN Kapat" if is_wan_session_active(chat_id) else "WAN Baslat",
                    callback_data="phone:wan:stop" if is_wan_session_active(chat_id) else "phone:wan:start",
                )
            ]
        )
    rows.append([InlineKeyboardButton("Durum", callback_data="phone:status")])
    return InlineKeyboardMarkup(rows)


def _phone_link_text(link_payload):
    lan_urls = list(link_payload.get("lan_urls") or [])
    if not lan_urls and link_payload.get("lan_url"):
        lan_urls = [link_payload["lan_url"]]
    lan_lines = [f"LAN: {lan_urls[0]}"] if lan_urls else ["LAN: "]
    if len(lan_urls) > 1:
        lan_lines.extend(
            f"LAN {index}: {url}"
            for index, url in enumerate(lan_urls[1:], start=2)
        )
    return (
        "Telefon linki hazir.\n\n"
        f"Sure: {link_payload.get('expires_in_text', '?')}\n"
        f"Etiket: {link_payload.get('label', 'phone-client')}\n"
        + (
            f"Uzak: {link_payload.get('wan_url')}\n"
            if link_payload.get("wan_url")
            else "Uzak: Hazirlaniyor veya kapali\n"
        )
        + "\n".join(lan_lines)
        + "\n"
        f"Local: {link_payload.get('local_url', '')}"
    )


def _load_phone_notification_state():
    try:
        data = json.loads(PHONE_NOTIFICATION_STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        legacy.logger.warning("Telefon bildirim state okunamadi", exc_info=True)
        return {}


def _save_phone_notification_state(state):
    try:
        PHONE_NOTIFICATION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PHONE_NOTIFICATION_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        legacy.logger.warning("Telefon bildirim state yazilamadi", exc_info=True)


def _remember_phone_chat(chat_id):
    if chat_id is None:
        return
    state = _load_phone_notification_state()
    chat_ids = {str(value) for value in state.get("chat_ids", []) if str(value).strip()}
    chat_ids.add(str(chat_id))
    state["chat_ids"] = sorted(chat_ids)
    _save_phone_notification_state(state)


def _remember_notified_public_url(public_url):
    if not public_url:
        return
    state = _load_phone_notification_state()
    state["last_public_url"] = public_url
    _save_phone_notification_state(state)


def _notification_target_chat_ids():
    state = _load_phone_notification_state()
    targets = {str(value) for value in state.get("chat_ids", []) if str(value).strip()}
    targets.update(str(value) for value in getattr(legacy, "ALLOWED_IDS", set()) if str(value).strip())
    return sorted(targets)


def _phone_notification_interval_seconds():
    try:
        return max(10, int(os.getenv("PHONE_NOTIFY_TUNNEL_INTERVAL_SEC", "20")))
    except ValueError:
        return 20


def _phone_repair_text(link_payload, old_url=None):
    old_line = f"Eski uzak adres: {old_url}\n" if old_url else ""
    return (
        "Uzak baglanti adresi degisti.\n\n"
        "Tekrar QR okutmana gerek yok. Bu yeni linke dokununca ayni PWA yeniden eslesir ve devam eder.\n\n"
        f"{old_line}"
        + _phone_link_text(link_payload)
    )


async def _send_phone_repair_link(bot, chat_id, old_url=None):
    link_payload = await asyncio.to_thread(create_phone_link, 0, label="telegram-repair")
    await bot.send_message(
        chat_id=chat_id,
        text=_phone_repair_text(link_payload, old_url=old_url),
        reply_markup=_phone_link_markup(link_payload, chat_id=chat_id),
    )
    public_url = link_payload.get("public_url") or ""
    _remember_notified_public_url(public_url)
    return public_url


async def _watch_public_phone_link(application):
    if os.getenv("PHONE_NOTIFY_TUNNEL_CHANGES", "1").strip().lower() in {"0", "false", "no", "off"}:
        return

    interval = _phone_notification_interval_seconds()
    last_seen = _load_phone_notification_state().get("last_public_url", "")
    await asyncio.sleep(3)

    while True:
        try:
            health = await asyncio.to_thread(get_bridge_health)
            current_url = (health.get("public_url") or "").strip()
            if current_url and current_url != last_seen:
                targets = _notification_target_chat_ids()
                if not last_seen:
                    _remember_notified_public_url(current_url)
                    last_seen = current_url
                elif targets:
                    sent_any = False
                    for chat_id in targets:
                        try:
                            await _send_phone_repair_link(
                                application.bot,
                                chat_id,
                                old_url=last_seen,
                            )
                            sent_any = True
                        except Exception as exc:
                            legacy.logger.warning(
                                f"Telefon uzak link bildirimi gonderilemedi ({chat_id}): {exc}"
                            )
                    if sent_any:
                        _remember_notified_public_url(current_url)
                        last_seen = current_url
                else:
                    legacy.logger.debug("Telefon uzak link degisti ama bildirim hedefi yok.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            legacy.logger.debug(f"Telefon uzak link watcher beklemede: {exc}")

        await asyncio.sleep(interval)


async def _send_phone_panel(update_or_chat, context, *, minutes=0, label="telegram", chat_id=None):
    _remember_phone_chat(chat_id)
    status_text = _phone_bridge_status_text(chat_id=chat_id)
    try:
        link_payload = await asyncio.to_thread(create_phone_link, minutes, label=label)
        _remember_notified_public_url(link_payload.get("public_url") or "")
        text = status_text + "\n\n" + _phone_link_text(link_payload)
        reply_markup = _phone_link_markup(link_payload, chat_id=chat_id)
    except PhoneBridgeClientError as exc:
        text = (
            status_text
            + "\n\nTelefon linki olusturulamadi.\n"
            + f"Neden: {exc}\n\n"
            + "Bridge acik degilse once phone bridge'i baslatalim."
        )
        reply_markup = get_mode_keyboard()

    await _send_text(update_or_chat, context, text, reply_markup, chat_id=chat_id)


def _claude_status_summary(chat_id=None):
    tab = claude_bridge.get_tab()
    model_key = claude_bridge.get_model(tab)
    lines = [
        "Provider: Claude",
        f"Is: {'Hazir'}",
        f"Sekme: {legacy.CLAUDE_MODE_BUTTONS.get(tab, tab)}",
        f"Session: {claude_bridge.get_session_title() or '(session secilmedi)'}",
        f"CWD: {claude_bridge.get_cwd()}",
        f"Transport: {_transport_label(claude_bridge.get_transport_mode())}",
        f"Model: {legacy.CLAUDE_MODEL_LABELS.get(model_key, model_key)}",
    ]
    if tab == "code":
        effort = claude_bridge.get_effort()
        permission_mode = claude_bridge.get_permission_mode()
        lines.append(
            f"Effort: {legacy.CLAUDE_EFFORT_LABELS.get(effort, effort)}"
        )
        lines.append(
            f"Izin: {legacy.CLAUDE_PERMISSION_LABELS.get(permission_mode, permission_mode)}"
        )
    else:
        lines.append(
            "Thinking: "
            + ("Acik" if claude_bridge.get_extended_thinking() else "Kapali")
        )
    return "\n".join(lines)


def _codex_status_summary(chat_id=None):
    busy = "Calisiyor" if chat_id is not None and legacy._has_running_codex_task(chat_id) else "Hazir"
    lines = [
        "Provider: Codex",
        f"Is: {busy}",
        f"Session: {codex_bridge.get_session_title() or '(session secilmedi)'}",
        f"CWD: {codex_bridge.get_cwd()}",
        f"Transport: {_transport_label(codex_bridge.get_transport_mode())}",
    ]
    return "\n".join(lines)


def _build_claude_session_browser(mode=None):
    legacy.clear_session_cache()
    session_cache = {}
    active_tab = mode or claude_bridge.get_tab()
    sessions = (
        claude_bridge.list_sessions(8, mode=active_tab)
        if legacy._supports_session_listing(active_tab)
        else []
    )
    active_session_id = claude_state.get_state().session_id
    active_title = claude_bridge.get_session_title()
    buttons = []
    lines = []

    for index, session in enumerate(sessions, start=1):
        session_id = session.get("id") or session["title"]
        title = session.get("title") or "(isimsiz)"
        source = session.get("source", active_tab)
        workspace = _workspace_label(session.get("cwd", ""), fallback=str(source).capitalize())
        is_active = bool(
            (active_session_id and session.get("id") == active_session_id)
            or (active_title and title == active_title)
        )
        marker = "●" if is_active else "○"
        cb_data = f"ses:{session_id}"
        session_cache[cb_data] = {
            "id": session.get("id"),
            "title": title,
            "cwd": session.get("cwd", ""),
            "source": source,
        }
        button_label = f"{marker} {index}. {workspace}"
        buttons.append([InlineKeyboardButton(button_label, callback_data=cb_data)])
        last_activity = _format_last_activity(
            session.get("lastActivity") or session.get("updated_at")
        )
        suffix = f" | {last_activity}" if last_activity else ""
        lines.append(f"{marker} {index}. [{workspace}] {title}{suffix}")

    legacy.set_session_cache(session_cache)
    buttons.append([InlineKeyboardButton("Yeni Session", callback_data="ses:new")])
    summary = (
        _claude_status_summary()
        + "\n\nOturumlar:\n"
        + "\n".join(lines)
        if lines
        else _claude_status_summary()
        + "\n\nBu sekmede listelenebilir session bulunamadi. Yeni Session ile devam edebilirsin."
    )
    return InlineKeyboardMarkup(buttons), len(sessions), summary


def get_session_inline_keyboard(mode=None):
    markup, count, _summary = _build_claude_session_browser(mode=mode)
    return markup, count


def get_codex_session_inline_keyboard():
    codex_state.clear_session_cache()
    session_cache = {}
    sessions = codex_bridge.list_sessions(15)
    active_session_id = codex_state.get_state().session_id
    active_title = codex_bridge.get_session_title()
    buttons = []
    lines = []

    for index, session in enumerate(sessions, start=1):
        workspace = _workspace_label(session.get("cwd", ""), fallback="Genel")
        title = session.get("display_title") or session.get("title") or "(isimsiz)"
        session_id = session.get("id") or session.get("title")
        is_active = bool(
            (active_session_id and session.get("id") == active_session_id)
            or (active_title and title == active_title)
        )
        marker = "●" if is_active else "○"
        cb_data = f"codses:{session_id}"
        session_cache[cb_data] = {
            "id": session.get("id"),
            "title": session.get("title"),
            "display_title": title,
            "cwd": session.get("cwd", ""),
            "source": session.get("source", "codex"),
        }
        button_label = f"{marker} {index}. {workspace}"
        buttons.append([InlineKeyboardButton(button_label, callback_data=cb_data)])
        last_activity = _format_last_activity(session.get("updated_at"))
        suffix = f" | {last_activity}" if last_activity else ""
        lines.append(f"{marker} {index}. [{workspace}] {title}{suffix}")

    codex_state.set_session_cache(session_cache)
    buttons.append([InlineKeyboardButton("Yeni Session", callback_data="codses:new")])
    summary = (
        _codex_status_summary()
        + "\n\nOturumlar:\n"
        + "\n".join(lines)
        if lines
        else _codex_status_summary()
        + "\n\nListelenebilir Codex session bulunamadi. Yeni Session ile devam edebilirsin."
    )
    return InlineKeyboardMarkup(buttons), len(sessions), summary


async def _send_text(update_or_chat, context, text, reply_markup, chat_id=None):
    if hasattr(update_or_chat, "message") and update_or_chat.message:
        await update_or_chat.message.reply_text(text, reply_markup=reply_markup)
        return

    target_chat = chat_id if chat_id is not None else update_or_chat
    await context.bot.send_message(
        chat_id=target_chat,
        text=text,
        reply_markup=reply_markup,
    )


async def _send_claude_panel(update_or_chat, context, include_sessions=False, chat_id=None):
    text = "Claude hazir.\n\n" + _claude_status_summary(chat_id=chat_id)
    config_path = legacy.CLAUDE_UI_CONFIG_METADATA["active_path"]
    text += f"\nConfig: {os.path.basename(config_path)}"
    await _send_text(
        update_or_chat, context, text, legacy.get_claude_keyboard(), chat_id=chat_id
    )
    if include_sessions and not claude_bridge.get_session_title():
        if legacy._supports_session_listing(claude_bridge.get_tab()):
            session_markup, _session_count, session_text = _build_claude_session_browser(
                mode=claude_bridge.get_tab()
            )
            await _send_text(
                update_or_chat,
                context,
                session_text,
                session_markup,
                chat_id=chat_id,
            )
        else:
            await _send_text(
                update_or_chat,
                context,
                _claude_status_summary(chat_id=chat_id)
                + "\n\nBu sekmede session listeleme yok. Yeni Session ile devam edebilirsin.",
                legacy.get_claude_keyboard(),
                chat_id=chat_id,
            )


async def _send_codex_panel(update_or_chat, context, include_sessions=False, chat_id=None):
    text = "Codex hazir.\n\n" + _codex_status_summary(chat_id=chat_id)
    await _send_text(
        update_or_chat, context, text, legacy.get_codex_keyboard(), chat_id=chat_id
    )
    if include_sessions and not codex_bridge.get_session_title():
        session_markup, _session_count, session_text = get_codex_session_inline_keyboard()
        await _send_text(
            update_or_chat,
            context,
            session_text,
            session_markup,
            chat_id=chat_id,
        )


def _is_claude_control_message(msg):
    controls = (
        legacy.BUTTON_CLAUDE_SESSIONS
        | legacy.BUTTON_CLAUDE_NEW
        | legacy.BUTTON_CLAUDE_TAB
        | legacy.BUTTON_CLAUDE_MODEL
        | legacy.BUTTON_CLAUDE_EFFORT
        | legacy.BUTTON_CLAUDE_PERMISSION
        | legacy.BUTTON_CLAUDE_THINKING
        | legacy.BUTTON_CLAUDE_STATUS
        | legacy.BUTTON_SCREENSHOT
        | legacy.BUTTON_MAIN_BACK
    )
    controls |= {
        "📋 Session Sec",
        "🆕 Yeni Session",
        "🧭 Sekme",
        "🧠 Model",
        "⚙️ Effort",
        "🔐 Izin Modu",
        "🔐 İzin Modu",
        "📊 Durum",
        "📸 Ekran Al",
        "🔙 Ana Menu",
        "🔙 Ana Menü",
    }
    return msg in controls


def _is_codex_control_message(msg):
    controls = legacy.BUTTON_CLAUDE_SESSIONS | legacy.BUTTON_CLAUDE_NEW | legacy.BUTTON_CLAUDE_STATUS | legacy.BUTTON_SCREENSHOT | legacy.BUTTON_MAIN_BACK
    controls |= {
        "📋 Session Sec",
        "🆕 Yeni Session",
        "📊 Durum",
        "📸 Ekran Al",
        "🔙 Ana Menu",
        "🔙 Ana Menü",
    }
    return msg in controls


async def _send_claude_guard(update, context):
    if legacy._supports_session_listing(claude_bridge.get_tab()):
        session_markup, _session_count, session_text = _build_claude_session_browser(
            mode=claude_bridge.get_tab()
        )
        await update.message.reply_text(
            "Bu promptu gondermeden once bir session sec veya Yeni Session ile fresh oturum baslat.\n\n"
            + session_text,
            reply_markup=session_markup,
        )
        return

    await update.message.reply_text(
        "Bu promptu gondermeden once Yeni Session ile bir oturum baslat.",
        reply_markup=legacy.get_claude_keyboard(),
    )


async def _send_codex_guard(update, context):
    session_markup, _session_count, session_text = get_codex_session_inline_keyboard()
    await update.message.reply_text(
        "Bu promptu gondermeden once bir session sec veya Yeni Session ile fresh oturum baslat.\n\n"
        + session_text,
        reply_markup=session_markup,
    )


async def _run_codex_and_deliver(bot, chat_id, prompt):
    task = asyncio.current_task()
    try:
        result = await codex_bridge.run_codex(prompt)
        if result is None:
            await bot.send_message(
                chat_id=chat_id,
                text="Codex istegi islenmedi veya tekrar eden bir gonderim olarak atlandi.",
                reply_markup=legacy.get_codex_keyboard(),
            )
            return

        await bot.send_message(
            chat_id=chat_id,
            text="Codex tamamlandi.",
            reply_markup=legacy.get_codex_keyboard(),
        )
        for chunk in legacy.split_message(result):
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                reply_markup=legacy.get_codex_keyboard(),
            )
    except Exception as exc:
        legacy.logger.exception(f"Codex UX teslim hatasi: {exc}")
        await bot.send_message(
            chat_id=chat_id,
            text=f"Codex sonucu gonderilirken hata oldu: {exc}",
            reply_markup=legacy.get_codex_keyboard(),
        )
    finally:
        legacy._clear_finished_codex_task(chat_id, task)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    legacy.set_state_key(
        legacy._state_key_from_chat_id(
            update.effective_chat.id if update.effective_chat else None
        )
    )
    codex_state.set_state_key(
        legacy._state_key_from_chat_id(
            update.effective_chat.id if update.effective_chat else None
        )
    )

    if not await legacy.check_auth(update):
        return

    raw_msg = update.message.text
    msg = legacy.canonical_button_label(raw_msg)
    mode = context.user_data.get("mode")
    waiting = context.user_data.get("waiting_for")

    if msg in legacy.BUTTON_MAIN_BACK or msg in {"🔙 Ana Menu", "🔙 Ana Menü"}:
        _clear_provider_ready(context, "claude")
        _clear_provider_ready(context, "codex")
        context.user_data.clear()
        await update.message.reply_text("Mod secin:", reply_markup=legacy.get_mode_keyboard())
        return

    if msg in {legacy.BUTTON_MAIN_CLAUDE, "🤖 Claude Code"}:
        context.user_data["mode"] = "claude"
        _set_provider_ready(context, "claude", bool(claude_bridge.get_session_title()))
        await _send_claude_panel(
            update, context, include_sessions=not bool(claude_bridge.get_session_title())
        )
        return

    if msg == legacy.BUTTON_MAIN_CODEX:
        context.user_data["mode"] = "codex"
        _set_provider_ready(context, "codex", bool(codex_bridge.get_session_title()))
        await _send_codex_panel(
            update, context, include_sessions=not bool(codex_bridge.get_session_title())
        )
        return

    if msg == BUTTON_PHONE:
        await _send_phone_panel(
            update,
            context,
            minutes=0,
            label=f"telegram-{update.effective_user.id}",
            chat_id=update.effective_chat.id if update.effective_chat else None,
        )
        return

    if mode == "claude":
        if msg in legacy.BUTTON_CLAUDE_SESSIONS or msg == "📋 Session Sec":
            if not legacy._supports_session_listing(claude_bridge.get_tab()):
                await update.message.reply_text(
                    _claude_status_summary()
                    + "\n\nBu sekmede session listeleme desteklenmiyor. Yeni Session ile devam edebilirsin.",
                    reply_markup=legacy.get_claude_keyboard(),
                )
                return
            session_markup, _session_count, session_text = _build_claude_session_browser(
                mode=claude_bridge.get_tab()
            )
            await update.message.reply_text(session_text, reply_markup=session_markup)
            return

        if msg in legacy.BUTTON_CLAUDE_NEW or msg == "🆕 Yeni Session":
            _set_provider_ready(context, "claude", True)
            await _ORIGINAL_HANDLE_MESSAGE(update, context)
            return

        if msg in legacy.BUTTON_CLAUDE_STATUS or msg == "📊 Durum":
            await update.message.reply_text(
                _claude_status_summary(chat_id=update.effective_chat.id),
                reply_markup=legacy.get_claude_keyboard(),
            )
            return

        if (
            not waiting
            and not _is_claude_control_message(msg)
        ):
            if not _has_provider_context(context, "claude"):
                await _send_claude_guard(update, context)
                return

            status = await update.message.reply_text(
                "Claude istegi gonderildi.\nAsama: Calisiyor",
                reply_markup=legacy.get_claude_keyboard(),
            )
            _clear_provider_ready(context, "claude")
            result = await claude_bridge.run_claude(msg)

            if result is None:
                await status.edit_text("Claude istegi islenmedi ya da tekrar eden gonderim olarak atlandi.")
                return

            if isinstance(result, dict) and result.get("type") == "permission":
                await status.edit_text("Claude izin bekliyor.")
                if not legacy._supports("runtime_permission_buttons"):
                    await update.message.reply_text(
                        "Claude yeni bir izin istedi ama bu platformda Telegram uzerinden anlik izin butonu desteklenmiyor.",
                        reply_markup=legacy.get_claude_keyboard(),
                    )
                    return
                await legacy._send_permission_buttons(update, context, result["buttons"])
                return

            await status.edit_text("Claude tamamlandi.")
            for chunk in legacy.split_message(result):
                await update.message.reply_text(
                    chunk,
                    reply_markup=legacy.get_claude_keyboard(),
                )
            return

    if mode == "codex":
        if msg in legacy.BUTTON_CLAUDE_SESSIONS or msg == "📋 Session Sec":
            session_markup, _session_count, session_text = get_codex_session_inline_keyboard()
            await update.message.reply_text(session_text, reply_markup=session_markup)
            return

        if msg in legacy.BUTTON_CLAUDE_NEW or msg == "🆕 Yeni Session":
            _set_provider_ready(context, "codex", True)
            await _ORIGINAL_HANDLE_MESSAGE(update, context)
            return

        if msg in legacy.BUTTON_CLAUDE_STATUS or msg == "📊 Durum":
            await update.message.reply_text(
                _codex_status_summary(chat_id=update.effective_chat.id),
                reply_markup=legacy.get_codex_keyboard(),
            )
            return

        if (
            not waiting
            and not _is_codex_control_message(msg)
        ):
            if not _has_provider_context(context, "codex"):
                await _send_codex_guard(update, context)
                return

            chat_id = update.effective_chat.id
            if legacy._has_running_codex_task(chat_id):
                await update.message.reply_text(
                    "Codex su an baska bir istek uzerinde calisiyor. Is bitince sonucu buraya otomatik birakacagim.",
                    reply_markup=legacy.get_codex_keyboard(),
                )
                return

            await update.message.reply_text(
                "Codex istegi gonderildi.\nAsama: Calisiyor",
                reply_markup=legacy.get_codex_keyboard(),
            )
            _clear_provider_ready(context, "codex")
            task = asyncio.create_task(_run_codex_and_deliver(context.bot, chat_id, msg))
            legacy._codex_delivery_tasks[str(chat_id)] = task
            return

    await _ORIGINAL_HANDLE_MESSAGE(update, context)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data if query else ""
    if query and isinstance(data, str) and data.startswith("phone:"):
        chat_id = query.message.chat_id if query and query.message else None
        _remember_phone_chat(chat_id)
        await query.answer()
        if data == "phone:status":
            try:
                text = _phone_bridge_status_text(chat_id=chat_id)
                await query.edit_message_text(
                    text,
                    reply_markup=_phone_status_markup(chat_id=chat_id),
                )
            except Exception:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=_phone_bridge_status_text(chat_id=chat_id),
                    reply_markup=_phone_status_markup(chat_id=chat_id),
                )
            return

        if data.startswith("phone:new:"):
            try:
                minutes = int(data.rsplit(":", 1)[-1])
            except ValueError:
                minutes = 0
            try:
                link_payload = await asyncio.to_thread(
                    create_phone_link,
                    minutes,
                    label=f"telegram-{query.from_user.id}",
                )
                _remember_notified_public_url(link_payload.get("public_url") or "")
                text = _phone_bridge_status_text(chat_id=chat_id) + "\n\n" + _phone_link_text(link_payload)
                markup = _phone_link_markup(link_payload, chat_id=chat_id)
            except PhoneBridgeClientError as exc:
                text = (
                    _phone_bridge_status_text(chat_id=chat_id)
                    + "\n\nTelefon linki yenilenemedi.\n"
                    + f"Neden: {exc}"
                )
                markup = _phone_status_markup(chat_id=chat_id)

            try:
                await query.edit_message_text(text, reply_markup=markup)
            except Exception:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=text,
                    reply_markup=markup,
                )
            return

        if data == "phone:wan:start":
            started = await start_wan_session(context.bot, chat_id)
            text = (
                _phone_bridge_status_text(chat_id=chat_id)
                + "\n\n"
                + (
                    "WAN snapshot oturumu baslatildi. Ekran degistikce ayni Telegram mesajini guncelleyecegim."
                    if started
                    else "WAN snapshot zaten calisiyor."
                )
            )
            markup = _phone_status_markup(chat_id=chat_id)
            try:
                await query.edit_message_text(text, reply_markup=markup)
            except Exception:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=text,
                    reply_markup=markup,
                )
            return

        if data == "phone:wan:stop":
            stopped = await stop_wan_session(chat_id)
            text = (
                _phone_bridge_status_text(chat_id=chat_id)
                + "\n\n"
                + ("WAN snapshot durduruldu." if stopped else "WAN snapshot zaten kapali.")
            )
            markup = _phone_status_markup(chat_id=chat_id)
            try:
                await query.edit_message_text(text, reply_markup=markup)
            except Exception:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=text,
                    reply_markup=markup,
                )
            return

    if data == "ses:new" or (isinstance(data, str) and data.startswith("ses:")):
        _set_provider_ready(context, "claude", True)
    if data == "codses:new" or (isinstance(data, str) and data.startswith("codses:")):
        _set_provider_ready(context, "codex", True)
    await _ORIGINAL_HANDLE_CALLBACK(update, context)


async def post_init(application):
    await _ORIGINAL_POST_INIT(application)
    application.create_task(_watch_public_phone_link(application))


def _install_overrides():
    global _PATCHED
    if _PATCHED:
        return

    legacy.get_session_inline_keyboard = get_session_inline_keyboard
    legacy.get_codex_session_inline_keyboard = get_codex_session_inline_keyboard
    legacy.get_mode_keyboard = get_mode_keyboard
    legacy.get_dynamic_keyboard = get_dynamic_keyboard
    legacy.get_claude_keyboard = get_claude_keyboard
    legacy.get_codex_keyboard = get_codex_keyboard
    legacy._send_claude_panel = _send_claude_panel
    legacy._send_codex_panel = _send_codex_panel
    legacy.handle_message = handle_message
    legacy.handle_callback = handle_callback
    legacy.post_init = post_init
    legacy.get_profile_summary = _claude_status_summary
    codex_bridge.get_profile_summary = _codex_status_summary

    _PATCHED = True


def run_bot():
    _install_overrides()
    legacy.logger.info("AgentCockpit UX motoru yuklendi")
    legacy.run_bot()

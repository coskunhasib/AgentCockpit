# core/claude_bridge.py
import asyncio
import contextvars
import functools
import html
import json
import os
import subprocess
import sys
import time
import uuid


async def _run_in_thread_with_context(func, *args, **kwargs):
    """asyncio.to_thread replacement that copies ContextVars (Python <3.12 safe)."""
    ctx = contextvars.copy_context()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, functools.partial(ctx.run, func, *args, **kwargs)
    )

from core.claude_state import get_state, get_state_key, save_profile
from core.claude_ui_config import (
    CLAUDE_EFFORT_LABELS,
    CLAUDE_MODE_BUTTONS,
    CLAUDE_MODEL_LABELS,
    CLAUDE_PERMISSION_LABELS,
    CLAUDE_TAB_MODEL_OPTIONS,
)
from core.logger import get_logger
from core.platform_utils import (
    ensure_claude_sidebar_open,
    find_claude_window,
    focus_claude_input,
    focus_window,
    get_claude_exe,
    get_claude_projects_dir,
    get_claude_sessions_meta_dir,
    list_claude_chat_sessions,
    open_session_in_desktop,
    paste_and_send,
    read_visible_claude_chat_history,
    set_claude_effort,
    set_claude_extended_thinking,
    set_claude_mode,
    set_claude_model,
    set_claude_permission_mode,
    wait_and_read_response,
)

logger = get_logger("claude_bridge")

CLAUDE_EXE = get_claude_exe()
TIMEOUT = 180

MODE_LABELS = CLAUDE_MODE_BUTTONS
MODEL_LABELS = CLAUDE_MODEL_LABELS
TAB_MODEL_OPTIONS = {
    key: tuple(values) for key, values in CLAUDE_TAB_MODEL_OPTIONS.items()
}
EFFORT_LABELS = CLAUDE_EFFORT_LABELS
PERMISSION_LABELS = CLAUDE_PERMISSION_LABELS
CLI_MODEL_LABELS = {
    "opus": "opus",
    "opus_1m": "claude-opus-4-6[1m]",
    "sonnet": "sonnet",
    "haiku": "haiku",
}
CLI_EFFORT_LABELS = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "max": "high",
}
CLI_PERMISSION_LABELS = {
    "ask": "default",
    "accept_edits": "acceptEdits",
    "plan": "plan",
    "bypass": "bypassPermissions",
}
DEDUP_WINDOW = 5  # seconds

_chat_storage_entries_cache = {"signature": None, "entries": []}
_chat_conversations_cache = {"signature": None, "items": []}
_chat_message_cache = {}
_CHAT_MESSAGE_CACHE_MAX = 500


def _claude_cli_available():
    return bool(CLAUDE_EXE and os.path.exists(CLAUDE_EXE))


def _get_chat_storage_dir():
    if sys.platform == "win32":
        base = os.environ.get(
            "APPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        )
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get(
            "XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config")
        )
    return os.path.join(base, "Claude", "Local Storage", "leveldb")


def _get_chat_storage_files():
    storage_dir = _get_chat_storage_dir()
    if not os.path.isdir(storage_dir):
        return []

    files = []
    for name in os.listdir(storage_dir):
        if not name.endswith((".log", ".ldb")):
            continue
        path = os.path.join(storage_dir, name)
        if os.path.isfile(path):
            files.append(path)
    return sorted(files, key=os.path.getmtime, reverse=True)


def _get_chat_storage_signature(files=None):
    files = files or _get_chat_storage_files()
    signature = []
    for path in files:
        try:
            stat = os.stat(path)
        except OSError:
            continue
        signature.append((os.path.basename(path), stat.st_size, int(stat.st_mtime)))
    return tuple(signature)


def _get_chat_storage_entries():
    files = _get_chat_storage_files()
    signature = _get_chat_storage_signature(files)
    if _chat_storage_entries_cache["signature"] == signature:
        return _chat_storage_entries_cache["entries"], signature

    entries = []
    for path in files:
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue

        text = raw.decode("utf-16le", errors="ignore")
        if text:
            entries.append((path, text))

    if _chat_storage_entries_cache["signature"] != signature:
        _chat_message_cache.clear()

    _chat_storage_entries_cache["signature"] = signature
    _chat_storage_entries_cache["entries"] = entries
    return entries, signature


def _extract_json_object(text, start_index):
    if start_index < 0 or start_index >= len(text) or text[start_index] != "{":
        return None

    depth = 0
    in_string = False
    escaped = False
    for idx in range(start_index, len(text)):
        char = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start_index : idx + 1]
    return None


def _iter_chat_storage_objects(entries):
    seen = set()

    for path, text in entries:
        start = 0
        while True:
            idx = text.find('{"uuid":"', start)
            if idx == -1:
                break
            raw = _extract_json_object(text, idx)
            if not raw:
                start = idx + 1
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                start = idx + 1
                continue
            end = len(raw)

            if isinstance(obj, dict) and obj.get("uuid"):
                marker = (obj.get("uuid"), obj.get("sender"), obj.get("updated_at"))
                if marker not in seen:
                    seen.add(marker)
                    yield path, obj
            start = idx + max(end, 1)


def _load_chat_conversations():
    entries, signature = _get_chat_storage_entries()
    if _chat_conversations_cache["signature"] == signature:
        return _chat_conversations_cache["items"]

    conversations = {}
    for _path, obj in _iter_chat_storage_objects(entries):
        if not isinstance(obj, dict):
            continue
        if not obj.get("uuid") or not obj.get("name") or not obj.get(
            "current_leaf_message_uuid"
        ):
            continue

        conv = {
            "uuid": obj.get("uuid"),
            "title": obj.get("name") or "(isimsiz)",
            "summary": obj.get("summary", "") or "",
            "model": obj.get("model", "") or "",
            "updated_at": obj.get("updated_at") or "",
            "created_at": obj.get("created_at") or "",
            "current_leaf_message_uuid": obj.get("current_leaf_message_uuid") or "",
            "project_uuid": obj.get("project_uuid") or "",
            "source": "chat",
        }

        previous = conversations.get(conv["uuid"])
        if not previous or conv["updated_at"] >= previous["updated_at"]:
            conversations[conv["uuid"]] = conv

    items = sorted(
        conversations.values(),
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )
    _chat_conversations_cache["signature"] = signature
    _chat_conversations_cache["items"] = items
    return items


def _find_chat_conversation(chat_uuid=None, title=None):
    conversations = _load_chat_conversations()
    if chat_uuid:
        for conversation in conversations:
            if conversation.get("uuid") == chat_uuid:
                return conversation

    if title:
        for conversation in conversations:
            if conversation.get("title") == title:
                return conversation
    return None


def _find_chat_message_by_uuid(message_uuid):
    if not message_uuid:
        return None

    entries, signature = _get_chat_storage_entries()
    cache_key = (signature, message_uuid)
    if cache_key in _chat_message_cache:
        return _chat_message_cache[cache_key]

    pattern = f'{{"uuid":"{message_uuid}"'
    for _path, text in entries:
        idx = text.find(pattern)
        if idx == -1:
            continue
        raw = _extract_json_object(text, idx)
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("uuid") == message_uuid:
            if len(_chat_message_cache) >= _CHAT_MESSAGE_CACHE_MAX:
                _chat_message_cache.clear()
            _chat_message_cache[cache_key] = obj
            return obj

    if len(_chat_message_cache) >= _CHAT_MESSAGE_CACHE_MAX:
        _chat_message_cache.clear()
    _chat_message_cache[cache_key] = None
    return None


def _extract_chat_message_text(message):
    if not isinstance(message, dict):
        return ""

    parts = []
    content = message.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = (item.get("text") or "").strip()
            if text:
                parts.append(text)

    if parts:
        return "\n".join(parts)
    return (message.get("text") or "").strip()


def _format_history_messages(messages, source_label="Session", total_count=None):
    if not messages:
        return f"({source_label}'da okunabilir mesaj yok)"

    recent = messages
    total = total_count if total_count is not None else len(messages)
    header = f"\U0001f4dc Son {len(recent)} mesaj (toplam {total}):\n{'-' * 30}\n"
    start_index = total - len(recent) + 1
    formatted = []

    for offset, item in enumerate(recent, start=start_index):
        role = item.get("role", "?")
        text = item.get("text", "").strip()
        role_label = "SEN" if role == "user" else "CLAUDE" if role == "assistant" else role.upper()
        label = f"──── [{offset}] {role_label} ────"
        safe_text = html.escape(text)
        if role == "user":
            formatted.append(f"<b>{html.escape(label)}\n{safe_text}</b>")
        else:
            formatted.append(f"{html.escape(label)}\n{safe_text}")

    return header + "\n\n".join(formatted)


def _read_chat_history_from_storage(chat_uuid, last_n=10):
    conversation = _find_chat_conversation(chat_uuid=chat_uuid)
    if not conversation:
        return None

    current_uuid = conversation.get("current_leaf_message_uuid")
    seen = set()
    messages = []
    while current_uuid and current_uuid not in seen:
        seen.add(current_uuid)
        message = _find_chat_message_by_uuid(current_uuid)
        if not message:
            break

        sender = (message.get("sender") or "").lower()
        text = _extract_chat_message_text(message)
        if sender in {"human", "assistant"} and text:
            role = "user" if sender == "human" else "assistant"
            messages.append({"role": role, "text": text})

        parent_uuid = message.get("parent_message_uuid")
        if not parent_uuid or parent_uuid == "00000000-0000-4000-8000-000000000000":
            break
        current_uuid = parent_uuid

    if not messages:
        return None

    messages.reverse()
    return _format_history_messages(
        messages[-last_n:], source_label="Chat", total_count=len(messages)
    )


def _normalized_tab(tab=None):
    state = get_state()
    value = (tab or state.tab or "code").lower()
    return value if value in MODE_LABELS else "code"


def _tab_supports_code_controls(tab=None):
    return _normalized_tab(tab) == "code"


def _tab_supports_extended_thinking(tab=None):
    return _normalized_tab(tab) in {"chat", "cowork"}


def _supported_models_for_tab(tab=None):
    return TAB_MODEL_OPTIONS.get(_normalized_tab(tab), TAB_MODEL_OPTIONS["code"])


def _get_model_store_for_tab(tab=None):
    state = get_state()
    normalized = _normalized_tab(tab)
    if normalized == "chat":
        return state.chat_model
    if normalized == "cowork":
        return state.cowork_model
    return state.code_model


def _set_model_store_for_tab(tab, model):
    state = get_state()
    normalized = _normalized_tab(tab)
    if normalized == "chat":
        state.chat_model = model
    elif normalized == "cowork":
        state.cowork_model = model
    else:
        state.code_model = model


def _effective_model(tab=None):
    model = _get_model_store_for_tab(tab)
    if model in _supported_models_for_tab(tab):
        return model
    fallback = "opus"
    _set_model_store_for_tab(tab, fallback)
    return fallback


def _get_transport_mode():
    forced = os.environ.get("CLAUDE_TRANSPORT", "").strip().lower()
    handle = find_claude_window()
    desktop_available = bool(handle)
    cli_available = _claude_cli_available()

    if forced == "desktop":
        if desktop_available:
            return "desktop"
        if cli_available:
            return "cli"
        return "none"

    if forced == "cli":
        return "cli" if cli_available else ("desktop" if desktop_available else "none")

    if sys.platform == "linux" and cli_available:
        return "cli"

    if desktop_available:
        return "desktop"
    if cli_available:
        return "cli"
    return "none"


def get_transport_mode():
    return _get_transport_mode()


def _find_session_meta(session_id):
    for session in list_sessions(limit=200, mode="code"):
        if session.get("id") == session_id:
            return session
    return None


def _refresh_session_from_meta(session_id):
    session = _find_session_meta(session_id)
    if not session:
        return False

    set_session(session_id, title=session.get("title") or session_id)
    session_cwd = session.get("cwd")
    if session_cwd:
        set_cwd(session_cwd)
    return True


def _run_claude_cli(prompt, cwd=None):
    state = get_state()
    if not _claude_cli_available():
        return "[HATA] Claude CLI bulunamadi."

    target_cwd = cwd or state.cwd or os.getcwd()
    session_id = state.session_id or str(uuid.uuid4())
    args = [
        CLAUDE_EXE,
        "-p",
        "--output-format",
        "text",
        "--model",
        CLI_MODEL_LABELS.get(_effective_model(), "sonnet"),
        "--resume" if state.session_id else "--session-id",
        session_id,
        prompt,
    ]
    if _tab_supports_code_controls():
        args[6:6] = [
            "--effort",
            CLI_EFFORT_LABELS.get(state.effort, "high"),
            "--permission-mode",
            CLI_PERMISSION_LABELS.get(state.permission_mode, "default"),
        ]

    try:
        completed = subprocess.run(
            args,
            cwd=target_cwd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT + 30,
        )
    except subprocess.TimeoutExpired:
        return "[TIMEOUT] Claude CLI cevap vermedi."
    except Exception as exc:
        logger.error(f"Claude CLI hata: {exc}")
        return f"[HATA] Claude CLI calistirilamadi: {exc}"

    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()

    if completed.returncode != 0:
        detail = stderr or stdout or f"returncode={completed.returncode}"
        logger.error(f"Claude CLI hata dondu: {detail}")
        return f"[HATA] Claude CLI: {detail}"

    set_session(session_id, title=state.session_title or session_id)
    set_cwd(target_cwd)
    time.sleep(0.5)
    _refresh_session_from_meta(session_id)

    return stdout or "(Cevap bos)"


def set_cwd(path):
    get_state().cwd = path


def get_cwd():
    return get_state().cwd


def set_session(session_id, title=None):
    state = get_state()
    state.session_id = session_id
    state.session_title = title
    logger.info(f"Session ayarlandi: {title or session_id}")


def get_session():
    return get_state().session_id


def get_session_title():
    return get_state().session_title


def clear_session():
    state = get_state()
    state.session_id = None
    state.session_title = None
    logger.info("Session temizlendi (fresh mode)")


def _persist_profile():
    save_profile()


def set_tab(tab):
    if tab in MODE_LABELS:
        get_state().tab = tab
        _persist_profile()
        return True
    return False


def get_tab():
    return get_state().tab


def set_model(model):
    target_tab = _normalized_tab()
    if model in _supported_models_for_tab(target_tab):
        _set_model_store_for_tab(target_tab, model)
        _persist_profile()
        return True
    return False


def get_model(tab=None):
    return _effective_model(tab)


def set_effort(effort):
    if effort in EFFORT_LABELS:
        get_state().effort = effort
        _persist_profile()
        return True
    return False


def get_effort():
    return get_state().effort


def set_permission_mode(mode):
    if mode in PERMISSION_LABELS:
        get_state().permission_mode = mode
        _persist_profile()
        return True
    return False


def get_permission_mode():
    return get_state().permission_mode


def set_extended_thinking(enabled):
    get_state().extended_thinking = bool(enabled)
    _persist_profile()
    return True


def get_extended_thinking():
    return get_state().extended_thinking


def get_profile_summary():
    state = get_state()
    session_line = state.session_title or "(session secilmedi)"
    transport = _get_transport_mode()
    transport_label = {
        "desktop": "Desktop UI",
        "cli": "Claude CLI",
        "none": "Yok",
    }.get(transport, transport)
    summary = (
        f"Session: {session_line}\n"
        f"CWD: {state.cwd}\n"
        f"Transport: {transport_label}\n"
        f"Sekme: {MODE_LABELS.get(state.tab, state.tab)}\n"
        f"Model: {MODEL_LABELS.get(_effective_model(), _effective_model())}"
    )
    if _tab_supports_code_controls():
        summary += (
            f"\nEffort: {EFFORT_LABELS.get(state.effort, state.effort)}\n"
            f"Izin modu: {PERMISSION_LABELS.get(state.permission_mode, state.permission_mode)}"
        )
    elif _tab_supports_extended_thinking():
        summary += (
            "\nExtended thinking: "
            + ("Acik" if state.extended_thinking else "Kapali")
        )
    return summary


def sync_claude_settings(focus_input=False):
    """Apply the current stored Claude profile to the live desktop window."""
    state = get_state()
    transport = _get_transport_mode()
    logger.info(
        f"[sync] state={get_state_key()} transport={transport} tab={state.tab} model={_effective_model()}"
    )
    if transport != "desktop":
        if transport == "cli":
            return False, "Desktop bulunamadi. Ayarlar Claude CLI ile sonraki promptta uygulanacak."
        return False, "Claude Desktop veya CLI bulunamadi."

    handle = find_claude_window()
    if not focus_window(handle):
        return False, "Claude Desktop penceresi bulunamadi."

    ensure_claude_sidebar_open()

    results = []
    if state.tab:
        results.append(set_claude_mode(state.tab))
    current_model = _effective_model()
    if current_model:
        results.append(set_claude_model(current_model, mode=state.tab))
    if _tab_supports_code_controls() and state.effort:
        results.append(set_claude_effort(state.effort))
    if _tab_supports_code_controls() and state.permission_mode:
        results.append(set_claude_permission_mode(state.permission_mode))
    if _tab_supports_extended_thinking():
        results.append(set_claude_extended_thinking(state.extended_thinking))
    if focus_input:
        results.append(focus_claude_input())

    if any(results):
        return True, "Claude ayarlari senkronize edildi."
    return False, "Claude acik ama ayarlar tam uygulanamadi."


async def continue_after_permission():
    """Continue reading after a permission button was pressed."""
    if _get_transport_mode() != "desktop":
        return "[HATA] Anlik izin devami sadece Desktop modunda destekleniyor."
    state = get_state()
    logger.info(f"[permission-continue] state={get_state_key()} prompt_len={len(state.last_prompt or '')}")
    response = await _run_in_thread_with_context(
        wait_and_read_response, 300, state.last_prompt or None
    )
    return response


async def run_claude(prompt, cwd=None):
    """Send prompt to Claude Desktop via platform-native automation."""
    state = get_state()

    now = time.time()
    if prompt == state.last_prompt and (now - state.last_prompt_time) < DEDUP_WINDOW:
        logger.warning("Dedup: ayni mesaj tekrar geldi, atlaniyor")
        return None
    state.last_prompt = prompt
    state.last_prompt_time = now

    try:
        target_cwd = cwd or state.cwd
        if target_cwd:
            set_cwd(target_cwd)

        transport = _get_transport_mode()
        logger.info(
            f"[run] state={get_state_key()} transport={transport} tab={state.tab} cwd={target_cwd}"
        )
        if transport == "cli":
            logger.info("Claude CLI fallback kullaniliyor")
            return await _run_in_thread_with_context(_run_claude_cli, prompt, target_cwd)
        if transport == "none":
            return "[HATA] Claude Desktop veya Claude CLI bulunamadi."

        if state.session_title:
            if not open_session_in_desktop(state.session_title, mode=state.tab):
                if _claude_cli_available():
                    logger.warning("Desktop session acilamadi, Claude CLI fallback kullaniliyor")
                    return await _run_in_thread_with_context(_run_claude_cli, prompt, target_cwd)
                return "[HATA] Claude Desktop'ta session acilamadi. Claude acik mi?"
        else:
            handle = find_claude_window()
            if not focus_window(handle):
                if _claude_cli_available():
                    logger.warning("Desktop bulunamadi, Claude CLI fallback kullaniliyor")
                    return await _run_in_thread_with_context(_run_claude_cli, prompt, target_cwd)
                return "[HATA] Claude Desktop penceresi bulunamadi. Claude acik mi?"
            await asyncio.sleep(0.5)

        await _run_in_thread_with_context(sync_claude_settings, True)

        paste_and_send(prompt)
        logger.info(f"Prompt gonderildi ({len(prompt)} karakter)")

        response = await _run_in_thread_with_context(wait_and_read_response, TIMEOUT, prompt)
        return response
    except Exception as exc:
        logger.error(f"SendKeys hata: {exc}")
        return f"[HATA] {exc}"


# --- Session metadata -------------------------------------------------------

SESSIONS_META_DIR = get_claude_sessions_meta_dir()
PROJECTS_DIR = get_claude_projects_dir()
LOCAL_AGENT_SESSIONS_DIR = os.path.join(
    os.path.dirname(SESSIONS_META_DIR), "local-agent-mode-sessions"
)


def _list_code_sessions(limit=10):
    sessions = []
    if not os.path.isdir(SESSIONS_META_DIR):
        return _list_sessions_from_project_logs(limit)

    for root, _dirs, files in os.walk(SESSIONS_META_DIR):
        for fname in files:
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                title = data.get("title", "(isimsiz)")
                cli_sid = data.get("cliSessionId", "")
                last_activity = data.get("lastActivityAt", 0)
                cwd = data.get("cwd", "") or data.get("originCwd", "")
                if cli_sid and not data.get("isArchived", False):
                    sessions.append(
                        {
                            "id": cli_sid,
                            "title": title,
                            "lastActivity": last_activity,
                            "cwd": cwd,
                        }
                    )
            except Exception:
                continue

    sessions.sort(key=lambda session: session["lastActivity"], reverse=True)
    if sessions:
        return sessions[:limit]
    return _list_sessions_from_project_logs(limit)


def _list_cowork_sessions(limit=10):
    sessions = []
    if not os.path.isdir(LOCAL_AGENT_SESSIONS_DIR):
        return sessions

    for root, _dirs, files in os.walk(LOCAL_AGENT_SESSIONS_DIR):
        for fname in files:
            if not fname.endswith(".json"):
                continue
            if f"{os.sep}agent{os.sep}" not in os.path.join(root, fname):
                continue

            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue

            if data.get("sessionType") != "agent" or data.get("isArchived", False):
                continue

            session_id = data.get("cliSessionId") or data.get("sessionId")
            if not session_id:
                continue

            title = (
                data.get("title")
                or data.get("initialMessage")
                or data.get("processName")
                or session_id
            )
            sessions.append(
                {
                    "id": session_id,
                    "title": title[:80],
                    "lastActivity": data.get("lastActivityAt", 0),
                    "cwd": data.get("cwd", ""),
                    "source": "cowork",
                }
            )

    sessions.sort(key=lambda session: session["lastActivity"], reverse=True)
    return sessions[:limit]


def _list_chat_sessions(limit=10):
    visible_sessions = list_claude_chat_sessions(limit)
    conversations = _load_chat_conversations()

    if visible_sessions:
        by_title = {}
        for conversation in conversations:
            by_title.setdefault(conversation.get("title"), []).append(conversation)

        matched_sessions = []
        unmatched_sessions = []
        for session in visible_sessions:
            title = session.get("title") or ""
            matches = by_title.get(title) or []
            conversation = matches.pop(0) if matches else None
            normalized = {
                "id": f"chat::{conversation['uuid']}"
                if conversation
                else session.get("id") or f"chat::{title}",
                "title": title,
                "lastActivity": conversation.get("updated_at", "") if conversation else 0,
                "cwd": "",
                "source": "chat",
            }
            (matched_sessions if conversation else unmatched_sessions).append(
                normalized
            )
        if matched_sessions:
            return matched_sessions[:limit]
        return unmatched_sessions[:limit]

    fallback = []
    for conversation in conversations[:limit]:
        fallback.append(
            {
                "id": f"chat::{conversation['uuid']}",
                "title": conversation.get("title") or "(isimsiz)",
                "lastActivity": conversation.get("updated_at", ""),
                "cwd": "",
                "source": "chat",
            }
        )
    return fallback


def list_sessions(limit=10, mode=None):
    """List recent sessions using the storage that matches the active Claude tab."""
    normalized = _normalized_tab(mode)
    if normalized == "cowork":
        return _list_cowork_sessions(limit)
    if normalized == "chat":
        return _list_chat_sessions(limit)
    return _list_code_sessions(limit)


def _list_sessions_from_project_logs(limit=10):
    sessions = []
    if not os.path.isdir(PROJECTS_DIR):
        return sessions

    for root, _dirs, files in os.walk(PROJECTS_DIR):
        if "subagents" in root:
            continue

        for fname in files:
            if not fname.endswith(".jsonl"):
                continue

            sid = fname[:-6]
            fpath = os.path.join(root, fname)
            title = sid
            cwd = ""

            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    for line in fh:
                        data = json.loads(line.strip())
                        cwd = data.get("cwd") or cwd
                        if data.get("type") != "user":
                            continue
                        message = data.get("message", {})
                        content = message.get("content")
                        if isinstance(content, str) and content.strip():
                            title = content.strip().splitlines()[0][:80]
                            break
            except Exception:
                continue

            sessions.append(
                {
                    "id": sid,
                    "title": title or sid,
                    "lastActivity": int(os.path.getmtime(fpath) * 1000),
                    "cwd": cwd,
                }
            )

    sessions.sort(key=lambda session: session["lastActivity"], reverse=True)
    return sessions[:limit]


def _find_session_jsonl(sid):
    """Search all project dirs for a session JSONL file."""
    if not os.path.isdir(PROJECTS_DIR):
        return None
    for root, _dirs, files in os.walk(PROJECTS_DIR):
        if "subagents" in root:
            continue
        target = f"{sid}.jsonl"
        if target in files:
            return os.path.join(root, target)
    return None


def _find_cowork_audit_jsonl(sid):
    if not os.path.isdir(LOCAL_AGENT_SESSIONS_DIR):
        return None

    for root, _dirs, files in os.walk(LOCAL_AGENT_SESSIONS_DIR):
        if "agent" not in root or "audit.jsonl" not in files:
            continue

        parent_dir = os.path.dirname(root)
        session_folder = os.path.basename(root)
        meta_candidates = []
        sibling_meta = os.path.join(parent_dir, f"{session_folder}.json")
        if os.path.exists(sibling_meta):
            meta_candidates.append(sibling_meta)
        meta_candidates.extend(
            os.path.join(root, name)
            for name in files
            if name.endswith(".json") and name != "manifest.json"
        )
        for meta_path in meta_candidates:
            try:
                with open(meta_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            if sid in {data.get("cliSessionId"), data.get("sessionId")}:
                return os.path.join(root, "audit.jsonl")
    return None


def _extract_message_text(message):
    if not isinstance(message, dict):
        return ""

    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()

    if not isinstance(content, list):
        return ""

    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text" and item.get("text"):
            parts.append(item["text"].strip())
    return "\n".join(part for part in parts if part)


def read_session_history(session_id=None, last_n=10):
    """Read conversation messages from session storage."""
    sid = session_id or get_state().session_id
    if not sid:
        return "Session ID yok. Once session bagla."

    if isinstance(sid, str) and sid.startswith("chat::"):
        chat_uuid = sid.split("chat::", 1)[-1].strip()
        history = _read_chat_history_from_storage(chat_uuid, last_n=last_n)
        if history:
            return history
        time.sleep(0.6)
        return read_visible_claude_chat_history(last_n)

    filepath = _find_session_jsonl(sid)
    source = "code"
    if not filepath:
        filepath = _find_cowork_audit_jsonl(sid)
        source = "cowork" if filepath else source
    if not filepath:
        return f"Session gecmisi bulunamadi: {sid}"

    messages = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                data = json.loads(line.strip())
                msg_type = data.get("type", "")
                if msg_type not in ("user", "assistant"):
                    continue

                message = data.get("message", {})
                role = message.get("role", "?")
                text = _extract_message_text(message)
                if text:
                    messages.append({"role": role, "text": text})
    except Exception as exc:
        return f"Session okunamadi: {exc}"

    if not messages:
        empty_label = "Cowork session'inda" if source == "cowork" else "Session'da"
        return f"({empty_label} okunabilir mesaj yok)"

    source_label = "Cowork session" if source == "cowork" else "Session"
    return _format_history_messages(
        messages[-last_n:], source_label=source_label, total_count=len(messages)
    )


def split_message(text, limit=4000):
    """Split long text into chunks for Telegram's message limit."""
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks

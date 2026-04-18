import asyncio
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.codex_state import get_state, get_state_key, save_profile
from core.logger import get_logger
from core.platform_utils import paste_and_send

logger = get_logger("codex_bridge")

CODEX_HOME = Path(os.path.expanduser("~")) / ".codex"
CODEX_GLOBAL_STATE = CODEX_HOME / ".codex-global-state.json"
CODEX_SESSION_INDEX = CODEX_HOME / "session_index.jsonl"
CODEX_SESSIONS_DIR = CODEX_HOME / "sessions"
DEDUP_WINDOW = 5
TIMEOUT = 240

CODEX_WINDOW_TITLE = "Codex"
CODEX_NEW_SESSION_LABEL = "Yeni mesaj dizisi"
CODEX_INPUT_PLACEHOLDER = "Takip değişikliklerini iste"


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalize_text(value):
    return " ".join((value or "").replace("\r", "\n").split()).strip()


def _session_root_name(path_value):
    normalized = (path_value or "").rstrip("\\/")
    if not normalized:
        return ""
    return os.path.basename(normalized)


def _extract_content_text(items):
    parts = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = (
            item.get("text")
            or item.get("output_text")
            or item.get("input_text")
            or item.get("content")
            or ""
        )
        text = text.strip()
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _is_environment_message(text):
    normalized = (text or "").strip()
    return normalized.startswith("<environment_context>")


def _read_jsonl(path):
    entries = []
    if not path or not os.path.exists(path):
        return entries
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except OSError:
        return []
    return entries


def _derive_session_title(entries):
    for entry in entries:
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload", {})
        if payload.get("type") != "message" or payload.get("role") != "user":
            continue
        text = _extract_content_text(payload.get("content", []))
        if not text or _is_environment_message(text):
            continue
        return text.replace("\n", " ").strip()
    return "Yeni mesaj dizisi"


def _parse_rollout_entries(path):
    return _read_jsonl(path)


def _load_session_index():
    index = {}
    for entry in _read_jsonl(CODEX_SESSION_INDEX):
        session_id = entry.get("id")
        if session_id:
            index[session_id] = entry
    return index


def _find_rollout_file(session_id):
    if not session_id:
        return None
    pattern = f"rollout-*{session_id}.jsonl"
    for path in CODEX_SESSIONS_DIR.rglob(pattern):
        return str(path)
    return None


def _get_recent_rollout_files():
    if not CODEX_SESSIONS_DIR.exists():
        return []
    files = list(CODEX_SESSIONS_DIR.rglob("rollout-*.jsonl"))
    files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return files


def _extract_session_record(path, session_index=None):
    entries = _parse_rollout_entries(path)
    if not entries:
        return None

    meta = entries[0].get("payload", {}) if entries[0].get("type") == "session_meta" else {}
    session_id = meta.get("id")
    if not session_id:
        return None

    cwd = meta.get("cwd", "") or ""
    title = _derive_session_title(entries)
    session_meta = (session_index or {}).get(session_id, {})
    display_title = (session_meta.get("thread_name") or title or "Yeni mesaj dizisi").strip()
    updated_at = ""
    for entry in reversed(entries):
        if entry.get("timestamp"):
            updated_at = entry["timestamp"]
            break
    if not updated_at:
        updated_at = session_meta.get("updated_at", "")

    return {
        "id": session_id,
        "title": title,
        "display_title": display_title,
        "cwd": cwd,
        "updated_at": updated_at,
        "path": str(path),
        "source": "codex",
    }


def _list_rollout_sessions(preferred_cwd=None):
    sessions = []
    seen = set()
    session_index = _load_session_index()
    for path in _get_recent_rollout_files():
        record = _extract_session_record(path, session_index=session_index)
        if not record:
            continue
        if record["id"] in seen:
            continue
        seen.add(record["id"])
        sessions.append(record)

    preferred_cwd = (preferred_cwd or "").rstrip("\\/")
    if preferred_cwd:
        matching_ids = set()
        matching = [item for item in sessions if item["cwd"].rstrip("\\/") == preferred_cwd]
        if not matching:
            preferred_name = _session_root_name(preferred_cwd).lower()
            matching = [
                item
                for item in sessions
                if _session_root_name(item["cwd"]).lower() == preferred_name
            ]
        matching_ids = {item["id"] for item in matching}
        non_matching = [item for item in sessions if item["id"] not in matching_ids]
        sessions = matching + non_matching

    if preferred_cwd:
        preferred_name = _session_root_name(preferred_cwd).lower()

        def _is_preferred(item):
            item_cwd = item["cwd"].rstrip("\\/")
            return item_cwd == preferred_cwd or _session_root_name(item["cwd"]).lower() == preferred_name

        def _updated_timestamp(item):
            updated_at = item.get("updated_at") or ""
            if not updated_at:
                return 0.0
            try:
                return datetime.fromisoformat(updated_at.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return 0.0

        sessions.sort(
            key=lambda item: (
                0 if _is_preferred(item) else 1,
                -_updated_timestamp(item),
            )
        )
    else:
        sessions.sort(key=lambda item: item["updated_at"] or "", reverse=True)
    return sessions


def _format_history_messages(messages, total_count=None):
    if not messages:
        return "(Codex oturumunda okunabilir mesaj yok)"

    recent = messages
    total = total_count if total_count is not None else len(messages)
    header = f"\U0001f4dc Son {len(recent)} mesaj (toplam {total}):\n{'-' * 30}\n"
    start_index = total - len(recent) + 1
    formatted = []
    for offset, item in enumerate(recent, start=start_index):
        role = item.get("role", "?")
        text = html.escape(item.get("text", "").strip())
        if role == "SEN":
            formatted.append(f"<b>---- [{offset}] {role} ----\n{text}</b>")
        else:
            formatted.append(f"---- [{offset}] {role} ----\n{text}")
    return header + "\n\n".join(formatted)


def _strip_session_age_suffix(text):
    normalized = _normalize_text(text)
    return re.sub(
        r"\s*\d+\s*(sn|s|dk|min|sa|h|gün|gun|day|days)$",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()


def _read_rollout_messages(path):
    entries = _parse_rollout_entries(path)
    messages = []
    for entry in entries:
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload", {})
        if payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            continue
        text = _extract_content_text(payload.get("content", []))
        if not text or _is_environment_message(text):
            continue
        messages.append(
            {
                "role": "SEN" if role == "user" else "CODEX",
                "text": text,
                "timestamp": entry.get("timestamp", ""),
                "phase": payload.get("phase", ""),
            }
        )
    return messages


def split_message(text, limit=3800):
    chunks = []
    current = []
    length = 0
    for line in (text or "").splitlines(True):
        if length + len(line) > limit and current:
            chunks.append("".join(current))
            current = [line]
            length = len(line)
        else:
            current.append(line)
            length += len(line)
    if current:
        chunks.append("".join(current))
    return chunks or [text or ""]


def _load_global_state():
    if not CODEX_GLOBAL_STATE.exists():
        return {}
    try:
        with open(CODEX_GLOBAL_STATE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _get_active_workspace_roots():
    data = _load_global_state()
    return data.get("active-workspace-roots") or []


def _get_transport_mode():
    if sys.platform != "win32":
        return "none"
    return "desktop" if find_codex_window() else "none"


def get_transport_mode():
    return _get_transport_mode()


def get_cwd():
    return get_state().cwd


def set_cwd(cwd):
    state = get_state()
    if not cwd:
        return False
    state.cwd = cwd
    save_profile()
    return True


def clear_session():
    state = get_state()
    state.session_id = None
    state.session_title = None


def set_session(session_id, title=None):
    state = get_state()
    state.session_id = session_id
    state.session_title = title
    return True


def get_session_title():
    return get_state().session_title


def list_sessions(limit=10):
    state = get_state()
    return _list_rollout_sessions(state.cwd)[:limit]


def read_session_history(session_id=None, last_n=10):
    state = get_state()
    target_session_id = session_id or state.session_id
    if not target_session_id:
        return "(Codex session secilmedi)"
    path = _find_rollout_file(target_session_id)
    if not path:
        return "(Codex rollout dosyasi bulunamadi)"
    messages = _read_rollout_messages(path)
    if not messages:
        return "(Codex session gecmisi bulunamadi)"
    return _format_history_messages(messages[-last_n:], total_count=len(messages))


def _get_ui_window():
    from pywinauto import Desktop

    return Desktop(backend="uia").window(title=CODEX_WINDOW_TITLE)


def find_codex_window():
    if sys.platform != "win32":
        return None
    try:
        import pyautogui

        for window in pyautogui.getWindowsWithTitle(CODEX_WINDOW_TITLE):
            if window.left > -10000:
                return window
    except Exception as exc:
        logger.error(f"Codex pencere arama hatasi: {exc}")
    return None


def focus_codex_window(handle=None):
    handle = handle or find_codex_window()
    if not handle:
        return False
    try:
        try:
            handle.activate()
        except Exception:
            if handle.isMinimized:
                handle.restore()
        time.sleep(0.3)
        return True
    except Exception as exc:
        logger.error(f"Codex focus hatasi: {exc}")
        return False


def _descendants(window, class_name=None):
    for elem in window.descendants():
        try:
            if class_name and elem.friendly_class_name() != class_name:
                continue
            yield elem
        except Exception:
            continue


def _click_matching(window, class_names, matcher):
    for class_name in class_names:
        for elem in _descendants(window, class_name=class_name):
            try:
                text = elem.window_text()
                rect = elem.rectangle()
                if matcher(text, rect, elem):
                    elem.click_input()
                    time.sleep(0.3)
                    return True
            except Exception:
                continue
    return False


def ensure_codex_sidebar_open():
    if sys.platform != "win32":
        return False
    try:
        window = _get_ui_window()
        for elem in _descendants(window, class_name="Button"):
            try:
                text = elem.window_text()
                if text == "Kenar çubuğunu gizle":
                    return True
                if text in {"Kenar çubuğunu göster", "Kenar çubuğunu aç"}:
                    elem.click_input()
                    time.sleep(0.3)
                    return True
            except Exception:
                continue
        return False
    except Exception as exc:
        logger.error(f"Codex sidebar hatasi: {exc}")
        return False


def _same_sidebar_row(rect_a, rect_b):
    return abs(rect_a.top - rect_b.top) <= 12


def _ensure_project_group_open(window, session_cwd):
    project_name = _session_root_name(session_cwd)
    if not project_name:
        return False

    sidebar_buttons = []
    for elem in _descendants(window, class_name="Button"):
        try:
            text = elem.window_text()
            rect = elem.rectangle()
            if rect.left > 700:
                continue
            sidebar_buttons.append((elem, text, rect))
        except Exception:
            continue

    project_row = None
    for elem, text, rect in sidebar_buttons:
        if text == project_name:
            project_row = (elem, rect)
            break

    if not project_row:
        return False

    _, project_rect = project_row
    for elem, text, rect in sidebar_buttons:
        if not _same_sidebar_row(project_rect, rect):
            continue
        if text == "Klasörü daralt":
            return True
        if text == "Klasörü genişlet":
            elem.click_input()
            time.sleep(0.3)
            return True

    return True


def click_new_session():
    if sys.platform != "win32":
        return False
    try:
        window = _get_ui_window()
        ensure_codex_sidebar_open()
        preferred_root = _session_root_name(get_state().cwd)
        if preferred_root:
            exact = f"{preferred_root} klasöründe yeni mesaj dizisi başlat"
            if _click_matching(
                window,
                ("Button",),
                lambda text, rect, elem: text == exact,
            ):
                return True
        return _click_matching(
            window,
            ("Button",),
            lambda text, rect, elem: text == CODEX_NEW_SESSION_LABEL,
        )
    except Exception as exc:
        logger.error(f"Codex yeni session hatasi: {exc}")
        return False


def open_session_in_desktop(title, session_cwd=None):
    if sys.platform != "win32":
        return False
    try:
        handle = find_codex_window()
        if not focus_codex_window(handle):
            return False
        ensure_codex_sidebar_open()
        window = _get_ui_window()
        _ensure_project_group_open(window, session_cwd)
        normalized = _strip_session_age_suffix(title)
        short = normalized[:90]

        def _matches_session_text(text):
            cleaned = _strip_session_age_suffix(text)
            return (
                cleaned == normalized
                or cleaned.startswith(short)
                or normalized.startswith(cleaned[:90])
            )

        return _click_matching(
            window,
            ("ListItem", "Button", "Static"),
            lambda text, rect, elem: rect.left <= 700
            and _matches_session_text(text),
        )
    except Exception as exc:
        logger.error(f"Codex session acma hatasi: {exc}")
        return False


def focus_codex_input():
    if sys.platform != "win32":
        return False
    try:
        window = _get_ui_window()
        if _click_matching(
            window,
            ("GroupBox", "Static"),
            lambda text, rect, elem: CODEX_INPUT_PLACEHOLDER in (text or ""),
        ):
            return True

        handle = find_codex_window()
        if not handle:
            return False
        import pyautogui

        pyautogui.click(handle.left + handle.width // 2, handle.top + handle.height - 90)
        time.sleep(0.2)
        return True
    except Exception as exc:
        logger.error(f"Codex input focus hatasi: {exc}")
        return False


def _latest_session_after(timestamp_iso, preferred_cwd=None):
    sessions = _list_rollout_sessions(preferred_cwd)
    for session in sessions:
        if session["updated_at"] and session["updated_at"] >= timestamp_iso:
            return session
    return sessions[0] if sessions else None


def _collect_assistant_messages_since(path, since_iso):
    messages = []
    completed = False
    for entry in _parse_rollout_entries(path):
        ts = entry.get("timestamp", "")
        if ts and ts < since_iso:
            continue

        if entry.get("type") == "event_msg":
            payload = entry.get("payload", {})
            if payload.get("type") == "task_complete":
                completed = True

        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload", {})
        if payload.get("type") != "message" or payload.get("role") != "assistant":
            continue
        text = _extract_content_text(payload.get("content", []))
        if text:
            messages.append(text)
    return messages, completed


def get_profile_summary():
    state = get_state()
    transport_label = "Desktop UI" if _get_transport_mode() == "desktop" else "Yok"
    workspace_roots = _get_active_workspace_roots()
    active_root = workspace_roots[0] if workspace_roots else state.cwd
    summary = (
        f"Session: {state.session_title or '(session secilmedi)'}\n"
        f"CWD: {state.cwd}\n"
        f"Aktif Klasor: {active_root}\n"
        f"Transport: {transport_label}"
    )
    return summary


async def run_codex(prompt, cwd=None):
    state = get_state()
    now = time.time()
    if prompt == state.last_prompt and (now - state.last_prompt_time) < DEDUP_WINDOW:
        logger.warning("Codex dedup: ayni mesaj tekrar geldi, atlaniyor")
        return None

    state.last_prompt = prompt
    state.last_prompt_time = now

    target_cwd = cwd or state.cwd
    if target_cwd:
        set_cwd(target_cwd)

    if _get_transport_mode() != "desktop":
        return "[HATA] Codex Desktop penceresi bulunamadi."

    handle = find_codex_window()
    if not focus_codex_window(handle):
        return "[HATA] Codex penceresi odaga getirilemedi."

    if state.session_title:
        open_session_in_desktop(state.session_title)
    else:
        ensure_codex_sidebar_open()

    if not focus_codex_input():
        return "[HATA] Codex prompt alani odaklanamadi."

    send_time = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    paste_and_send(prompt)
    logger.info(f"[run-codex] state={get_state_key()} cwd={target_cwd} prompt_len={len(prompt)}")

    session = None
    if state.session_id:
        session = {
            "id": state.session_id,
            "title": state.session_title,
            "cwd": state.cwd,
            "path": _find_rollout_file(state.session_id),
        }
    else:
        timeout_at = time.time() + 20
        while time.time() < timeout_at:
            candidate = _latest_session_after(send_time, state.cwd)
            if candidate:
                session = candidate
                set_session(candidate["id"], candidate["title"])
                if candidate.get("cwd"):
                    set_cwd(candidate["cwd"])
                break
            await asyncio.sleep(1)

    if not session or not session.get("id"):
        return "[HATA] Codex session tespit edilemedi."

    session_path = session.get("path") or _find_rollout_file(session["id"])
    if not session_path:
        return "[HATA] Codex rollout dosyasi bulunamadi."

    timeout_at = time.time() + TIMEOUT
    last_messages = []
    while time.time() < timeout_at:
        messages, completed = _collect_assistant_messages_since(session_path, send_time)
        if messages:
            last_messages = messages
        if completed and last_messages:
            return "\n\n".join(last_messages)
        await asyncio.sleep(2)

    if last_messages:
        return "\n\n".join(last_messages)
    return "[TIMEOUT] Codex cevap vermedi."

import subprocess
import time

from core.claude_chat_ui_parser import build_chat_sessions, format_visible_chat_history
from core.claude_ui_config import (
    CLAUDE_CHAT_UI,
    CLAUDE_EFFORT_LABELS,
    CLAUDE_MODE_BUTTONS,
    CLAUDE_MODEL_LABELS,
    CLAUDE_NAVIGATION,
    CLAUDE_PERMISSION_BUTTON_PREFIXES,
    CLAUDE_PERMISSION_BUTTONS,
    CLAUDE_PERMISSION_LABELS,
    CLAUDE_TAB_MODEL_OPTIONS,
)
from core.logger import get_logger

logger = get_logger("claude_platform_macos")


def _get_claude_model_labels_for_mode(mode=None):
    normalized = (mode or "code").lower()
    return {
        key: CLAUDE_MODEL_LABELS[key]
        for key in CLAUDE_TAB_MODEL_OPTIONS.get(normalized, CLAUDE_TAB_MODEL_OPTIONS["code"])
        if key in CLAUDE_MODEL_LABELS
    }


def _run_applescript(script):
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception as exc:
        logger.error(f"AppleScript hatasi: {exc}")
        return ""


def _escape(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _element_match(role_desc, target_text, startswith=False, click=False):
    safe_role = _escape(role_desc)
    safe_text = _escape(target_text)
    comparison = (
        f'if elementText starts with "{safe_text}" then'
        if startswith
        else f'if elementText is "{safe_text}" then'
    )
    action = 'click uiElem\n                            return "true"' if click else 'return "true"'

    script = f'''
    tell application "System Events"
        tell process "Claude"
            set frontmost to true
            repeat with uiElem in entire contents of window 1
                try
                    if (role description of uiElem) is "{safe_role}" then
                        set elementText to ""
                        try
                            set elementText to (name of uiElem as text)
                        end try
                        if elementText is "" then
                            try
                                set elementText to (value of attribute "AXDescription" of uiElem as text)
                            end try
                        end if
                        if elementText is "" then
                            try
                                set elementText to (value of uiElem as text)
                            end try
                        end if
                        {comparison}
                            {action}
                        end if
                    end if
                end try
            end repeat
            return "false"
        end tell
    end tell
    '''
    return "true" in _run_applescript(script).lower()


def _click_role_text(role_desc, target_text, startswith=False):
    return _element_match(role_desc, target_text, startswith=startswith, click=True)


def _has_role_text(role_desc, target_text, startswith=False):
    return _element_match(role_desc, target_text, startswith=startswith, click=False)


def _collect_role_texts(role_desc):
    safe_role = _escape(role_desc)
    script = f'''
    tell application "System Events"
        tell process "Claude"
            set frontmost to true
            set outputLines to {{}}
            repeat with uiElem in entire contents of window 1
                try
                    if (role description of uiElem) is "{safe_role}" then
                        set elementText to ""
                        try
                            set elementText to (name of uiElem as text)
                        end try
                        if elementText is "" then
                            try
                                set elementText to (value of attribute "AXDescription" of uiElem as text)
                            end try
                        end if
                        if elementText is "" then
                            try
                                set elementText to (value of uiElem as text)
                            end try
                        end if
                        if elementText is not "" then
                            set end of outputLines to elementText
                        end if
                    end if
                end try
            end repeat
            return outputLines as text
        end tell
    end tell
    '''
    raw = _run_applescript(script)
    if not raw:
        return []
    return [item.strip() for item in raw.split(", ") if item.strip()]


def _collect_visible_items(role_descriptions):
    roles = ", ".join(f'"{_escape(role)}"' for role in role_descriptions)
    script = f'''
    on normalize_text(valueText)
        set AppleScript's text item delimiters to {{return, linefeed}}
        set parts to text items of valueText
        set AppleScript's text item delimiters to " "
        set cleaned to parts as text
        set AppleScript's text item delimiters to ""
        return cleaned
    end normalize_text

    tell application "System Events"
        tell process "Claude"
            set frontmost to true
            set roleList to {{{roles}}}
            set outputText to ""
            repeat with uiElem in entire contents of window 1
                try
                    set roleDesc to role description of uiElem
                    if roleDesc is in roleList then
                        set isVisible to true
                        try
                            set isVisible to visible of uiElem
                        end try
                        if isVisible then
                            set elementText to ""
                            try
                                set elementText to (name of uiElem as text)
                            end try
                            if elementText is "" then
                                try
                                    set elementText to (value of attribute "AXDescription" of uiElem as text)
                                end try
                            end if
                            if elementText is "" then
                                try
                                    set elementText to (value of uiElem as text)
                                end try
                            end if
                            set elementText to my normalize_text(elementText)
                            if elementText is not "" then
                                set posX to 0
                                set posY to 0
                                set sizeW to 0
                                set sizeH to 0
                                try
                                    set elemPos to position of uiElem
                                    set posX to item 1 of elemPos
                                    set posY to item 2 of elemPos
                                end try
                                try
                                    set elemSize to size of uiElem
                                    set sizeW to item 1 of elemSize
                                    set sizeH to item 2 of elemSize
                                end try
                                set outputText to outputText & roleDesc & "|||" & elementText & "|||" & posX & "|||" & posY & "|||" & sizeW & "|||" & sizeH & linefeed
                            end if
                        end if
                    end if
                end try
            end repeat
            return outputText
        end tell
    end tell
    '''
    raw = _run_applescript(script)
    if not raw:
        return []

    items = []
    for line in raw.splitlines():
        parts = line.split("|||", 5)
        if len(parts) != 6:
            continue
        _role, text, left, top, width, height = parts
        try:
            left_val = int(float(left))
            top_val = int(float(top))
            width_val = int(float(width))
            height_val = int(float(height))
        except ValueError:
            continue
        items.append(
            {
                "text": text.strip(),
                "left": left_val,
                "right": left_val + max(width_val, 0),
                "top": top_val,
                "bottom": top_val + max(height_val, 0),
            }
        )
    return items


def _click_first_prefix(role_desc, prefixes):
    for prefix in prefixes:
        if _click_role_text(role_desc, prefix, startswith=True):
            return True
    return False


def find_claude_window():
    result = _run_applescript(
        'tell application "System Events" to get name of every process whose name contains "Claude"'
    )
    return "Claude" if "Claude" in result else None


def focus_window(handle):
    _run_applescript('tell application "Claude" to activate')
    time.sleep(0.5)
    return True


def ensure_claude_sidebar_open():
    collapse_label = CLAUDE_NAVIGATION["collapse_sidebar_button"]
    expand_label = CLAUDE_NAVIGATION["expand_sidebar_button"]
    menu_label = CLAUDE_NAVIGATION["menu_button"]
    if _has_role_text("button", collapse_label):
        return True
    if _click_role_text("button", expand_label):
        return True
    if _click_role_text("button", menu_label):
        time.sleep(0.3)
        return _has_role_text("button", collapse_label)
    return False


def set_claude_mode(mode):
    label = CLAUDE_MODE_BUTTONS.get((mode or "").lower())
    if not label:
        logger.error(f"Gecersiz Claude modu: {mode}")
        return False
    return _click_role_text("button", label)


def _open_model_menu(mode="code"):
    return _click_first_prefix("button", list(_get_claude_model_labels_for_mode(mode).values()))


def _open_permission_menu(mode="code"):
    return _click_first_prefix("button", list(CLAUDE_PERMISSION_LABELS.values()))


def _set_menu_radio(menu_opener, label_map, key, mode="code"):
    label = label_map.get((key or "").lower())
    if not label:
        logger.error(f"Gecersiz secim anahtari: {key}")
        return False
    if not menu_opener(mode=mode):
        return False
    time.sleep(0.3)
    return _click_role_text("radio button", label, startswith=True)


def set_claude_model(model_key, mode="code"):
    return _set_menu_radio(_open_model_menu, _get_claude_model_labels_for_mode(mode), model_key, mode=mode)


def set_claude_effort(effort_key):
    return _set_menu_radio(_open_model_menu, CLAUDE_EFFORT_LABELS, effort_key)


def set_claude_permission_mode(mode_key):
    return _set_menu_radio(_open_permission_menu, CLAUDE_PERMISSION_LABELS, mode_key)


def _get_toggle_state(role_desc, target_text):
    safe_role = _escape(role_desc)
    safe_text = _escape(target_text)
    script = f'''
    tell application "System Events"
        tell process "Claude"
            set frontmost to true
            repeat with uiElem in entire contents of window 1
                try
                    if (role description of uiElem) is "{safe_role}" then
                        set elementText to ""
                        try
                            set elementText to (name of uiElem as text)
                        end try
                        if elementText is "" then
                            try
                                set elementText to (value of attribute "AXDescription" of uiElem as text)
                            end try
                        end if
                        if elementText is "{safe_text}" then
                            try
                                return (value of attribute "AXValue" of uiElem) as text
                            end try
                            try
                                return (value of uiElem) as text
                            end try
                        end if
                    end if
                end try
            end repeat
            return ""
        end tell
    end tell
    '''
    raw = _run_applescript(script).strip().lower()
    if raw in {"1", "true", "yes"}:
        return True
    if raw in {"0", "false", "no"}:
        return False
    return None


def set_claude_extended_thinking(enabled):
    if not _open_model_menu(mode="chat"):
        return False
    time.sleep(0.3)

    current_state = _get_toggle_state("button", "Extended thinking")
    if current_state is enabled:
        return True
    return _click_role_text("button", "Extended thinking")


def list_claude_chat_sessions(limit=10):
    focus_window("Claude")
    time.sleep(0.2)
    ensure_claude_sidebar_open()
    set_claude_mode("chat")
    time.sleep(0.3)
    button_items = _collect_visible_items(["button"])
    return build_chat_sessions(button_items, CLAUDE_CHAT_UI, limit=limit)


def read_visible_claude_chat_history(last_n=10):
    focus_window("Claude")
    time.sleep(0.2)
    button_items = _collect_visible_items(["button"])
    text_items = _collect_visible_items(["static text", "text area"])
    texts = [item["text"] for item in text_items]
    page_not_found = any(
        CLAUDE_CHAT_UI["page_not_found_text"] in text for text in texts
    )
    home_greeting = any(
        text == CLAUDE_CHAT_UI["home_greeting_text"] for text in texts
    )
    return format_visible_chat_history(
        text_items,
        button_items,
        CLAUDE_CHAT_UI,
        last_n=last_n,
        page_not_found=page_not_found,
        home_greeting=home_greeting,
    )


def focus_claude_input():
    candidates = [
        ("group", "Type / for commands"),
        ("static text", "Type / for commands"),
        ("text area", "Type / for commands"),
    ]
    for role_desc, label in candidates:
        if _click_role_text(role_desc, label):
            return True
    return False


def detect_permission_prompt():
    buttons = _collect_role_texts("button")
    found = []
    for txt in buttons:
        if txt in CLAUDE_PERMISSION_BUTTONS or txt.startswith(
            CLAUDE_PERMISSION_BUTTON_PREFIXES
        ):
            if txt not in found:
                found.append(txt)
    return found


def click_permission_button(button_text):
    return _click_role_text("button", button_text)


def click_new_session():
    return False


def open_session_in_desktop(title, mode="code"):
    focus_window("Claude")
    time.sleep(0.3)
    ensure_claude_sidebar_open()
    if mode:
        set_claude_mode(mode)
        time.sleep(0.2)

    if _click_role_text("button", title):
        time.sleep(0.5)
        focus_claude_input()
        return True

    if _click_role_text("button", f"Running {title}"):
        time.sleep(0.5)
        focus_claude_input()
        return True

    if _click_role_text("static text", title):
        time.sleep(0.5)
        focus_claude_input()
        return True

    return False


def wait_and_read_response(timeout, last_prompt=None):
    time.sleep(2)
    start = time.time()
    while time.time() - start < timeout:
        buttons = _collect_role_texts("button")
        perm_buttons = [
            button
            for button in buttons
            if button in CLAUDE_PERMISSION_BUTTONS
            or button.startswith(CLAUDE_PERMISSION_BUTTON_PREFIXES)
        ]
        if perm_buttons:
            return {"type": "permission", "buttons": perm_buttons}
        if "Stop" not in buttons:
            break
        time.sleep(3)
    else:
        return "[TIMEOUT] Claude cevap vermedi (5dk)."

    time.sleep(1)
    parts = _collect_role_texts("static text")
    return parts[-1] if parts else "(Cevap okunamadi)"

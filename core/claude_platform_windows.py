import time

from core.claude_chat_ui_parser import build_chat_sessions, format_visible_chat_history
from core.claude_ui_config import (
    CLAUDE_CHAT_UI,
    CLAUDE_EFFORT_LABELS,
    CLAUDE_MODE_BUTTONS,
    CLAUDE_MODEL_LABELS,
    CLAUDE_NAVIGATION,
    CLAUDE_NEW_SESSION_BUTTON_PREFIXES,
    CLAUDE_PERMISSION_BUTTON_PREFIXES,
    CLAUDE_PERMISSION_BUTTONS,
    CLAUDE_PERMISSION_LABELS,
    CLAUDE_TAB_MODEL_OPTIONS,
    CLAUDE_WINDOW_TITLE,
)
from core.logger import get_logger

logger = get_logger("claude_platform_windows")


def _raw_ui_items_to_dicts(raw_items):
    items = []
    for _elem, text, rect in raw_items:
        items.append(
            {
                "text": text,
                "left": rect.left,
                "right": rect.right,
                "top": rect.top,
                "bottom": rect.bottom,
            }
        )
    return items


def _get_claude_model_labels_for_mode(mode=None):
    normalized = (mode or "code").lower()
    return {
        key: CLAUDE_MODEL_LABELS[key]
        for key in CLAUDE_TAB_MODEL_OPTIONS.get(normalized, CLAUDE_TAB_MODEL_OPTIONS["code"])
        if key in CLAUDE_MODEL_LABELS
    }


def _get_window():
    from pywinauto import Desktop as PWDesktop

    return PWDesktop(backend="uia").window(title=CLAUDE_WINDOW_TITLE)


def find_claude_window():
    try:
        import pyautogui

        wins = pyautogui.getWindowsWithTitle(CLAUDE_WINDOW_TITLE)
        for window in wins:
            if window.left > -10000 and "Opera" not in window.title:
                return window
    except Exception as exc:
        logger.error(f"Window arama hatasi: {exc}")
    return None


def focus_window(handle):
    try:
        try:
            handle.activate()
        except Exception:
            try:
                if handle.isMinimized:
                    handle.restore()
                handle.moveTo(handle.left, handle.top)
            except Exception:
                pass
        time.sleep(0.3)
        return True
    except Exception as exc:
        logger.error(f"Focus hatasi: {exc}")
        return False


def _descendants(window, class_name=None):
    for elem in window.descendants():
        try:
            if class_name and elem.friendly_class_name() != class_name:
                continue
            yield elem
        except Exception:
            continue


def _find_elements(window, class_name=None, exact_text=None, startswith=None):
    found = []
    for elem in _descendants(window, class_name=class_name):
        try:
            text = elem.window_text()
            if exact_text is not None and text != exact_text:
                continue
            if startswith is not None and not text.startswith(startswith):
                continue
            found.append(elem)
        except Exception:
            continue
    return found


def _click_first(window, class_name=None, exact_text=None, startswith=None):
    for elem in _find_elements(
        window, class_name=class_name, exact_text=exact_text, startswith=startswith
    ):
        try:
            elem.click_input()
            time.sleep(0.3)
            return True
        except Exception as exc:
            logger.warning(f"UI click hatasi: {exc}")
    return False


def _button_texts(window):
    texts = []
    for elem in _descendants(window, class_name="Button"):
        try:
            text = elem.window_text()
            if text:
                texts.append(text)
        except Exception:
            continue
    return texts


def _find_button_by_prefixes(window, prefixes):
    for elem in _descendants(window, class_name="Button"):
        try:
            text = elem.window_text()
            if any(text.startswith(prefix) for prefix in prefixes):
                return elem
        except Exception:
            continue
    return None


def _find_radio_by_prefix(window, prefix):
    for elem in _descendants(window, class_name="RadioButton"):
        try:
            if elem.window_text().startswith(prefix):
                return elem
        except Exception:
            continue
    return None


def _get_visible_texts(window, class_names):
    items = []
    for elem in _descendants(window):
        try:
            if elem.friendly_class_name() not in class_names:
                continue
            text = elem.window_text()
            if not text:
                continue
            rect = elem.rectangle()
            if not elem.is_visible():
                continue
            items.append((elem, text, rect))
        except Exception:
            continue
    return items


def ensure_claude_sidebar_open():
    try:
        w = _get_window()
        collapse_label = CLAUDE_NAVIGATION["collapse_sidebar_button"]
        expand_label = CLAUDE_NAVIGATION["expand_sidebar_button"]
        menu_label = CLAUDE_NAVIGATION["menu_button"]
        if _find_elements(w, class_name="Button", exact_text=collapse_label):
            return True
        if _click_first(w, class_name="Button", exact_text=expand_label):
            return True
        if _click_first(w, class_name="Button", exact_text=menu_label):
            time.sleep(0.3)
            w = _get_window()
            return bool(_find_elements(w, class_name="Button", exact_text=collapse_label))
        logger.warning("Sidebar acik hale getirilemedi")
        return False
    except Exception as exc:
        logger.error(f"Sidebar acma hatasi: {exc}")
        return False


def set_claude_mode(mode):
    label = CLAUDE_MODE_BUTTONS.get((mode or "").lower())
    if not label:
        logger.error(f"Gecersiz Claude modu: {mode}")
        return False

    try:
        w = _get_window()
        if _click_first(w, class_name="Button", exact_text=label):
            logger.info(f"Claude modu secildi: {label}")
            return True
        logger.error(f"Claude modu bulunamadi: {label}")
        return False
    except Exception as exc:
        logger.error(f"Mode degistirme hatasi: {exc}")
        return False


def _prepare_chat_sidebar():
    try:
        w = _get_window()
        try:
            w.set_focus()
        except Exception:
            pass
        time.sleep(0.3)

        ensure_claude_sidebar_open()
        set_claude_mode("chat")
        time.sleep(0.6)

        go_back_home = CLAUDE_NAVIGATION["go_back_home_link"]
        page_not_found = CLAUDE_CHAT_UI["page_not_found_text"]
        new_chat_prefixes = tuple(CLAUDE_CHAT_UI.get("new_chat_button_prefixes", ("New chat",)))
        for _ in range(2):
            w = _get_window()
            if _find_elements(w, class_name="Hyperlink", exact_text=go_back_home):
                _click_first(w, class_name="Hyperlink", exact_text=go_back_home)
                time.sleep(0.8)
                continue
            if _find_button_by_prefixes(w, new_chat_prefixes):
                return True
            if _find_elements(w, class_name="Static", exact_text=page_not_found):
                _click_first(
                    w, class_name="Button", exact_text=CLAUDE_NAVIGATION["back_button"]
                )
                time.sleep(0.8)

        w = _get_window()
        return bool(_find_button_by_prefixes(w, new_chat_prefixes))
    except Exception as exc:
        logger.error(f"Chat sidebar hazirlama hatasi: {exc}")
        return False


def list_claude_chat_sessions(limit=10):
    if not _prepare_chat_sidebar():
        return []

    try:
        w = _get_window()
        button_items = _raw_ui_items_to_dicts(_get_visible_texts(w, {"Button"}))
        return build_chat_sessions(button_items, CLAUDE_CHAT_UI, limit=limit)
    except Exception as exc:
        logger.error(f"Chat session listeleme hatasi: {exc}")
        return []


def read_visible_claude_chat_history(last_n=10):
    try:
        w = _get_window()
        button_items = _raw_ui_items_to_dicts(_get_visible_texts(w, {"Button"}))
        text_items = _raw_ui_items_to_dicts(
            _get_visible_texts(w, {"Static", "Edit", "Document", "Text"})
        )
        page_not_found = bool(
            _find_elements(
                w,
                class_name="Static",
                exact_text=CLAUDE_CHAT_UI["page_not_found_text"],
            )
        )
        home_greeting = bool(
            _find_elements(
                w,
                class_name="Static",
                exact_text=CLAUDE_CHAT_UI["home_greeting_text"],
            )
        )
        return format_visible_chat_history(
            text_items,
            button_items,
            CLAUDE_CHAT_UI,
            last_n=last_n,
            page_not_found=page_not_found,
            home_greeting=home_greeting,
        )
    except Exception as exc:
        logger.error(f"Chat gecmisi okuma hatasi: {exc}")
        return f"(Chat gecmisi okunamadi: {exc})"


def _open_model_menu(mode="code"):
    try:
        w = _get_window()
        btn = _find_button_by_prefixes(w, list(_get_claude_model_labels_for_mode(mode).values()))
        if not btn:
            logger.error("Model menusu butonu bulunamadi")
            return None
        btn.click_input()
        time.sleep(0.5)
        return _get_window()
    except Exception as exc:
        logger.error(f"Model menusu acma hatasi: {exc}")
        return None


def _open_permission_menu(mode="code"):
    try:
        w = _get_window()
        btn = _find_button_by_prefixes(w, list(CLAUDE_PERMISSION_LABELS.values()))
        if not btn:
            logger.error("Permission menu butonu bulunamadi")
            return None
        btn.click_input()
        time.sleep(0.5)
        return _get_window()
    except Exception as exc:
        logger.error(f"Permission menu acma hatasi: {exc}")
        return None


def _set_menu_radio(menu_opener, label_map, key, mode="code"):
    label = label_map.get((key or "").lower())
    if not label:
        logger.error(f"Gecersiz secim anahtari: {key}")
        return False

    menu_window = menu_opener(mode=mode)
    if not menu_window:
        return False

    radio = _find_radio_by_prefix(menu_window, label)
    if not radio:
        logger.error(f"Secenek bulunamadi: {label}")
        return False

    try:
        radio.click_input()
        time.sleep(0.3)
        logger.info(f"Menu secimi yapildi: {label}")
        return True
    except Exception as exc:
        logger.error(f"Radio click hatasi: {exc}")
        return False


def set_claude_model(model_key, mode="code"):
    return _set_menu_radio(_open_model_menu, _get_claude_model_labels_for_mode(mode), model_key, mode=mode)


def set_claude_effort(effort_key):
    return _set_menu_radio(_open_model_menu, CLAUDE_EFFORT_LABELS, effort_key)


def set_claude_permission_mode(mode_key):
    return _set_menu_radio(_open_permission_menu, CLAUDE_PERMISSION_LABELS, mode_key)


def _set_menu_toggle(menu_opener, label, enabled):
    menu_window = menu_opener(mode="chat")
    if not menu_window:
        return False

    candidates = []
    for class_name in ("Button", "CheckBox"):
        candidates.extend(
            _find_elements(menu_window, class_name=class_name, exact_text=label)
        )

    if not candidates:
        logger.error(f"Toggle secenegi bulunamadi: {label}")
        return False

    toggle = candidates[0]
    try:
        current_state = toggle.get_toggle_state()
    except Exception:
        current_state = None

    desired_state = 1 if enabled else 0
    if current_state == desired_state:
        logger.info(f"Toggle zaten istenen durumda: {label}={enabled}")
        return True

    try:
        toggle.click_input()
        time.sleep(0.3)
        logger.info(f"Toggle guncellendi: {label}={enabled}")
        return True
    except Exception as exc:
        logger.error(f"Toggle click hatasi: {exc}")
        return False


def set_claude_extended_thinking(enabled):
    return _set_menu_toggle(_open_model_menu, "Extended thinking", enabled)


def focus_claude_input():
    try:
        w = _get_window()

        for elem in _find_elements(
            w, class_name="GroupBox", exact_text="Type / for commands\n"
        ):
            try:
                elem.click_input()
                time.sleep(0.3)
                return True
            except Exception:
                pass

        for elem in _find_elements(
            w, class_name="Static", exact_text="Type / for commands"
        ):
            try:
                elem.click_input()
                time.sleep(0.3)
                return True
            except Exception:
                pass

        send_buttons = _find_elements(w, class_name="Button", exact_text="Send")
        if send_buttons:
            send_btn = send_buttons[0]
            rect = send_btn.rectangle()
            target_x = max(rect.left - 180, 50)
            target_y = rect.top + max((rect.bottom - rect.top) // 2, 1)
            send_btn.click_input(coords=(target_x - rect.left, target_y - rect.top))
            time.sleep(0.3)
            return True

        logger.warning("Input area bulunamadi")
        return False
    except Exception as exc:
        logger.error(f"Input focus hatasi: {exc}")
        return False


def open_session_in_desktop(title, mode="code"):
    try:
        attempts = 2 if (mode or "").lower() == "chat" else 1
        session_clicked = False

        for attempt in range(attempts):
            w = _get_window()
            try:
                w.set_focus()
            except Exception:
                pass
            time.sleep(0.3)

            if (mode or "").lower() == "chat":
                if not _prepare_chat_sidebar():
                    logger.error("Chat sidebar acik ve hazir hale getirilemedi")
                    return False
            else:
                ensure_claude_sidebar_open()
                if mode:
                    set_claude_mode(mode)

            w = _get_window()
            for elem in _descendants(w, class_name="Button"):
                try:
                    txt = elem.window_text()
                    if txt == title or txt == f"Running {title}":
                        elem.click_input()
                        session_clicked = True
                        logger.info(f"Session acildi (UIA): {title}")
                        break
                except Exception as exc:
                    logger.error(f"Session tiklanamadi: {exc}")
                    return False

            if session_clicked:
                break

            if (mode or "").lower() == "chat" and attempt == 0:
                logger.warning(
                    f"Chat session ilk denemede bulunamadi, tekrar deneniyor: {title}"
                )
                time.sleep(0.8)

        if not session_clicked:
            logger.error(f"Session bulunamadi: {title}")
            return False

        time.sleep(1.5)
        focus_claude_input()
        return True
    except Exception as exc:
        logger.error(f"Session acma hatasi: {exc}")
        return False


def wait_and_read_response(timeout, last_prompt=None):
    time.sleep(1)

    appear_start = time.time()
    stop_appeared = False
    while time.time() - appear_start < 30:
        try:
            w = _get_window()
            buttons = _button_texts(w)
            if "Stop" in buttons:
                stop_appeared = True
                logger.info("Claude cevap vermeye basladi (Stop gorundu)")
                break
        except Exception:
            pass
        time.sleep(0.5)

    if not stop_appeared:
        logger.warning("Stop butonu 30s icinde gorunmedi")
        return "(Claude cevap vermeye baslamadi. Claude Desktop'u kontrol et.)"

    start = time.time()
    while time.time() - start < timeout:
        try:
            w = _get_window()
            buttons = _button_texts(w)
            if "Stop" not in buttons:
                logger.info("Claude cevabi tamamladi (Stop kayboldu)")
                break
            perm_buttons = [
                button
                for button in buttons
                if button in CLAUDE_PERMISSION_BUTTONS
                or button.startswith(CLAUDE_PERMISSION_BUTTON_PREFIXES)
            ]
            if perm_buttons:
                logger.info(f"Permission prompt tespit edildi: {perm_buttons}")
                return {"type": "permission", "buttons": perm_buttons}
        except Exception:
            pass
        time.sleep(2)
    else:
        return "[TIMEOUT] Claude cevap vermedi (5dk)."

    time.sleep(1)
    try:
        import re

        w = _get_window()
        elements = list(w.descendants())
        start_idx = 0
        prompt_found = False
        if last_prompt:
            prompt_stripped = last_prompt.strip()
            for idx in range(len(elements) - 1, -1, -1):
                elem = elements[idx]
                try:
                    if elem.friendly_class_name() != "Static":
                        continue
                    text = elem.window_text().strip()
                except Exception:
                    continue
                if text == prompt_stripped:
                    start_idx = idx + 1
                    prompt_found = True
                    break

        logger.info(
            f"Response reading: prompt_found={prompt_found}, start_idx={start_idx}/{len(elements)}"
        )
        if not prompt_found and last_prompt:
            logger.warning(f"Prompt UI'da bulunamadi: {last_prompt[:50]}")
            return "(Cevap okunamadi - prompt UI'da bulunamadi.)"

        ui_chrome_exact = {"Chat mode", "Cowork mode", "Code mode"}
        ui_chrome_tokens = {"· Max", "· High", "· Medium", "· Low", "1M", "Opus 4.6"}
        timing_pattern = re.compile(r"^\d+(\.\d+)?[sm]$")
        token_pattern = re.compile(r"^↓?\s*\d+\s+tokens$")

        response_parts = []
        for elem in elements[start_idx:]:
            try:
                ctrl = elem.friendly_class_name()
                txt = elem.window_text()
            except Exception:
                continue
            if ctrl == "GroupBox" and txt == "Type / for commands\n":
                break
            if ctrl != "Static" or not txt:
                continue
            if txt in ui_chrome_exact or txt in ui_chrome_tokens:
                continue
            if timing_pattern.match(txt) or token_pattern.match(txt):
                continue
            if txt == "·":
                continue
            response_parts.append(txt)

        return "\n".join(response_parts) if response_parts else "(Cevap bos)"
    except Exception as exc:
        logger.error(f"Cevap okuma hatasi: {exc}")
        return f"[HATA] Cevap okunamadi: {exc}"


def detect_permission_prompt():
    try:
        w = _get_window()
        buttons = _button_texts(w)
        found = []
        for txt in buttons:
            if txt in CLAUDE_PERMISSION_BUTTONS or txt.startswith(
                CLAUDE_PERMISSION_BUTTON_PREFIXES
            ):
                if txt not in found:
                    found.append(txt)
        return found
    except Exception as exc:
        logger.error(f"Permission tespit hatasi: {exc}")
        return []


def click_permission_button(button_text):
    try:
        w = _get_window()
        if _click_first(w, class_name="Button", exact_text=button_text):
            logger.info(f"Permission button tiklandi: {button_text}")
            return True
        logger.error(f"Permission button bulunamadi: {button_text}")
        return False
    except Exception as exc:
        logger.error(f"Permission click hatasi: {exc}")
        return False


def click_new_session():
    try:
        w = _get_window()
        btn = _find_button_by_prefixes(w, CLAUDE_NEW_SESSION_BUTTON_PREFIXES)
        if btn:
            btn.click_input()
            return True
    except Exception as exc:
        logger.warning(f"New session button bulunamadi, hotkey deneniyor: {exc}")
    return False

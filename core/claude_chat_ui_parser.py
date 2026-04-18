def build_chat_sessions(button_items, chat_ui, limit=10):
    option_titles = set()
    more_options_prefix = chat_ui["more_options_prefix"]
    for item in button_items:
        cleaned = (item.get("text") or "").strip()
        if not cleaned.startswith(more_options_prefix):
            continue
        if not (10 <= item["left"] <= 40 and item["right"] <= 320 and 260 <= item["top"] <= 920):
            continue
        option_titles.add(cleaned[len(more_options_prefix) :].strip())

    chrome_buttons = set(chat_ui["session_excluded_buttons"])
    new_chat_prefixes = tuple(chat_ui.get("new_chat_button_prefixes", ("New chat",)))

    sessions = []
    seen = set()
    for item in button_items:
        cleaned = (item.get("text") or "").strip()
        if not cleaned or cleaned.startswith(more_options_prefix):
            continue
        if cleaned in chrome_buttons:
            continue
        if any(cleaned.startswith(prefix) for prefix in new_chat_prefixes):
            continue
        if not (10 <= item["left"] <= 30 and item["right"] <= 280 and 300 <= item["top"] <= 900):
            continue
        if option_titles and cleaned not in option_titles:
            continue
        key = (cleaned, item["top"])
        if key in seen:
            continue
        seen.add(key)
        sessions.append(
            {
                "id": f"chat::{len(sessions)+1:03d}::{item['top']}",
                "title": cleaned,
                "lastActivity": 0,
                "cwd": "",
                "source": "chat",
            }
        )
        if len(sessions) >= limit:
            break

    return sessions


def _is_chat_greeting(text, chat_ui):
    lowered = (text or "").strip().lower()
    return lowered.startswith(tuple(chat_ui["history_greeting_prefixes"]))


def _has_nearby_chat_action(button_items, item, chat_ui):
    action_labels = set(chat_ui["history_action_buttons"])
    open_prefixes = tuple(chat_ui["history_open_prefixes"])
    artifact_suffixes = tuple(chat_ui["history_artifact_suffixes"])

    for button in button_items:
        cleaned = (button.get("text") or "").strip()
        if not cleaned:
            continue
        if not (
            any(cleaned.startswith(prefix) for prefix in open_prefixes)
            or any(cleaned.endswith(suffix) for suffix in artifact_suffixes)
            or cleaned in action_labels
        ):
            continue
        same_band = abs(button["top"] - item["top"]) <= 32
        to_the_right = button["left"] >= (item["right"] - 24)
        if same_band and to_the_right:
            return True
    return False


def _group_chat_messages(text_items):
    grouped = []
    for item in text_items:
        text = item["text"]
        left = item["left"]
        top = item["top"]
        if grouped:
            prev = grouped[-1]
            same_lane = abs(prev["left"] - left) <= 140
            close_row = (top - prev["last_top"]) <= 48
            same_content_block = prev["left"] >= 700 and left >= 700 and close_row
            if (same_lane and close_row) or same_content_block:
                prev["parts"].append(text)
                prev["last_top"] = top
                continue
        grouped.append({"left": left, "top": top, "last_top": top, "parts": [text]})

    messages = []
    for group in grouped:
        text = "\n".join(part for part in group["parts"] if part).strip()
        if not text:
            continue
        if len(text) < 8 and "\n" not in text:
            continue
        messages.append((text, group["left"], group["top"]))
    return messages


def format_visible_chat_history(
    text_items,
    button_items,
    chat_ui,
    last_n=10,
    page_not_found=False,
    home_greeting=False,
):
    if page_not_found:
        return (
            "Bu chat acilmadi. Claude Desktop secilen konusma icin "
            f"'{chat_ui['page_not_found_text']}' gosterdigi icin gecmis okunamiyor."
        )
    if home_greeting:
        return "(Yeni chat ekrani acik; onceki mesaj yok.)"

    chrome_texts = set(chat_ui["history_chrome_texts"])
    open_prefixes = tuple(chat_ui["history_open_prefixes"])

    visible = []
    for item in text_items:
        cleaned = (item.get("text") or "").strip()
        if not cleaned:
            continue
        if cleaned in chrome_texts or any(cleaned.startswith(prefix) for prefix in open_prefixes):
            continue
        if _is_chat_greeting(cleaned, chat_ui):
            continue
        if item["left"] < 300 or item["top"] < 120 or item["top"] > 900:
            continue
        if cleaned == "Claude":
            continue
        current = {
            "text": cleaned,
            "left": item["left"],
            "right": item["right"],
            "top": item["top"],
        }
        if _has_nearby_chat_action(button_items, current, chat_ui):
            continue
        visible.append((cleaned, item["left"], item["top"]))

    if not visible:
        return "(Chat sayfasinda okunabilir gorunur mesaj bulunamadi.)"

    visible.sort(key=lambda item: (item[2], item[1]))
    messages = _group_chat_messages(
        [{"text": text, "left": left, "top": top} for text, left, top in visible]
    )

    if not messages:
        return "(Chat sayfasinda okunabilir gorunur mesaj bulunamadi.)"

    recent = messages[-last_n:]
    if not any(len(text) >= 20 for text, _left, _top in recent):
        return "(Chat acildi, ancak mesaj gecmisi UI'dan guvenilir okunamadi.)"

    formatted = []
    split_left = int(chat_ui.get("role_split_left_threshold", 1050))
    for idx, (text, left, _top) in enumerate(recent, start=1):
        role = "SEN" if left > split_left else "CLAUDE"
        formatted.append(f"---- [{idx}] {role} ----\n{text}")
    return "Gorunur chat icerigi:\n------------------------------\n" + "\n\n".join(
        formatted
    )

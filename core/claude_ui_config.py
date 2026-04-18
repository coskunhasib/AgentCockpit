import copy
import json
import os

_INVALID = object()


CONFIG_SCHEMA = {
    "window_title": str,
    "mode_buttons": {
        "chat": str,
        "cowork": str,
        "code": str,
    },
    "model_labels": {
        "opus": str,
        "opus_1m": str,
        "sonnet": str,
        "haiku": str,
    },
    "tab_model_options": {
        "chat": [str],
        "cowork": [str],
        "code": [str],
    },
    "effort_labels": {
        "low": str,
        "medium": str,
        "high": str,
        "max": str,
    },
    "permission_labels": {
        "ask": str,
        "accept_edits": str,
        "plan": str,
        "bypass": str,
    },
    "permission_button_prefixes": [str],
    "permission_buttons": [str],
    "new_session_button_prefixes": [str],
    "navigation": {
        "menu_button": str,
        "collapse_sidebar_button": str,
        "expand_sidebar_button": str,
        "search_button": str,
        "back_button": str,
        "forward_button": str,
        "go_back_home_link": str,
    },
    "chat": {
        "page_not_found_text": str,
        "home_greeting_text": str,
        "more_options_prefix": str,
        "new_chat_button_prefixes": [str],
        "session_excluded_buttons": [str],
        "history_chrome_texts": [str],
        "history_open_prefixes": [str],
        "history_artifact_suffixes": [str],
        "history_action_buttons": [str],
        "history_greeting_prefixes": [str],
        "role_split_left_threshold": int,
    },
}

BUNDLED_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "claude_ui_config.json"
)


def _deep_merge(base, override):
    if override is _INVALID:
        return copy.deepcopy(base)
    if not isinstance(base, dict) or not isinstance(override, dict):
        return copy.deepcopy(override)

    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _load_json_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _schema_name(schema):
    if isinstance(schema, list):
        return f"list[{_schema_name(schema[0])}]"
    if isinstance(schema, dict):
        return "object"
    return getattr(schema, "__name__", str(schema))


def _validate_value(value, schema, path, warnings, strict):
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            message = f"{path} object olmali, gelen: {type(value).__name__}"
            if strict:
                raise ValueError(message)
            warnings.append(message)
            return _INVALID

        sanitized = {}
        for key, child_schema in schema.items():
            child_path = f"{path}.{key}" if path else key
            if key not in value:
                message = f"{child_path} eksik"
                if strict:
                    raise ValueError(message)
                warnings.append(message)
                continue
            child_value = _validate_value(
                value[key], child_schema, child_path, warnings, strict
            )
            if child_value is not _INVALID:
                sanitized[key] = child_value

        for unknown_key in value.keys() - schema.keys():
            warnings.append(f"{path}.{unknown_key} tanimsiz anahtar, yok sayildi")
        return sanitized

    if isinstance(schema, list):
        item_schema = schema[0]
        if not isinstance(value, list):
            message = f"{path} {_schema_name(schema)} olmali, gelen: {type(value).__name__}"
            if strict:
                raise ValueError(message)
            warnings.append(message)
            return _INVALID

        sanitized = []
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            try:
                item_value = _validate_value(
                    item, item_schema, item_path, warnings, strict
                )
            except ValueError:
                if strict:
                    raise
                warnings.append(f"{item_path} gecersiz, yok sayildi")
                continue
            if item_value is not _INVALID:
                sanitized.append(item_value)
        return sanitized

    if not isinstance(value, schema):
        message = f"{path} {_schema_name(schema)} olmali, gelen: {type(value).__name__}"
        if strict:
            raise ValueError(message)
        warnings.append(message)
        return _INVALID

    return value


def _get_override_path(explicit_path=None):
    if explicit_path:
        return explicit_path
    return os.environ.get("CLAUDE_UI_CONFIG_PATH", "").strip() or None


def load_claude_ui_config(override_path=None):
    bundled_raw = _load_json_file(BUNDLED_CONFIG_PATH)
    bundled_warnings = []
    bundled_config = _validate_value(
        bundled_raw, CONFIG_SCHEMA, "config", bundled_warnings, strict=True
    )

    resolved_override_path = _get_override_path(override_path)
    resolved_override_path = (
        os.path.abspath(resolved_override_path) if resolved_override_path else None
    )
    bundled_abs_path = os.path.abspath(BUNDLED_CONFIG_PATH)

    warnings = list(bundled_warnings)
    merged_config = copy.deepcopy(bundled_config)
    active_path = bundled_abs_path

    if resolved_override_path and resolved_override_path != bundled_abs_path:
        if os.path.exists(resolved_override_path):
            try:
                override_raw = _load_json_file(resolved_override_path)
            except Exception as exc:
                warnings.append(
                    f"override dosyasi okunamadi ({resolved_override_path}): {exc}"
                )
            else:
                override_config = _validate_value(
                    override_raw, CONFIG_SCHEMA, "override", warnings, strict=False
                )
                merged_config = _deep_merge(bundled_config, override_config)
                active_path = resolved_override_path
        else:
            warnings.append(f"override dosyasi bulunamadi: {resolved_override_path}")

    metadata = {
        "default_path": bundled_abs_path,
        "active_path": active_path,
        "override_path": resolved_override_path,
        "warnings": tuple(warnings),
    }
    return merged_config, metadata


def get_claude_ui_config_path():
    return CLAUDE_UI_CONFIG_METADATA["active_path"]


def get_claude_ui_config_metadata():
    return CLAUDE_UI_CONFIG_METADATA


CLAUDE_UI_CONFIG, CLAUDE_UI_CONFIG_METADATA = load_claude_ui_config()
CLAUDE_UI_CONFIG_WARNINGS = CLAUDE_UI_CONFIG_METADATA["warnings"]
CLAUDE_WINDOW_TITLE = CLAUDE_UI_CONFIG["window_title"]
CLAUDE_MODE_BUTTONS = CLAUDE_UI_CONFIG["mode_buttons"]
CLAUDE_MODEL_LABELS = CLAUDE_UI_CONFIG["model_labels"]
CLAUDE_TAB_MODEL_OPTIONS = CLAUDE_UI_CONFIG["tab_model_options"]
CLAUDE_EFFORT_LABELS = CLAUDE_UI_CONFIG["effort_labels"]
CLAUDE_PERMISSION_LABELS = CLAUDE_UI_CONFIG["permission_labels"]
CLAUDE_PERMISSION_BUTTON_PREFIXES = tuple(CLAUDE_UI_CONFIG["permission_button_prefixes"])
CLAUDE_PERMISSION_BUTTONS = set(CLAUDE_UI_CONFIG["permission_buttons"])
CLAUDE_NEW_SESSION_BUTTON_PREFIXES = tuple(CLAUDE_UI_CONFIG["new_session_button_prefixes"])
CLAUDE_NAVIGATION = CLAUDE_UI_CONFIG["navigation"]
CLAUDE_CHAT_UI = CLAUDE_UI_CONFIG["chat"]

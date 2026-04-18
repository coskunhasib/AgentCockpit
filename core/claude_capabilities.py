import copy
import sys


PLATFORM_CAPABILITY_MATRIX = {
    "win32": {
        "tab_selection": True,
        "model_selection": True,
        "code_effort": True,
        "permission_mode": True,
        "extended_thinking": True,
        "session_listing": True,
        "chat_session_listing": True,
        "chat_history_read": True,
        "runtime_permission_buttons": True,
        "desktop_sidebar_control": True,
        "desktop_mode_switch": True,
        "desktop_input_focus": True,
    },
    "darwin": {
        "tab_selection": True,
        "model_selection": True,
        "code_effort": True,
        "permission_mode": True,
        "extended_thinking": True,
        "session_listing": True,
        "chat_session_listing": True,
        "chat_history_read": True,
        "runtime_permission_buttons": True,
        "desktop_sidebar_control": True,
        "desktop_mode_switch": True,
        "desktop_input_focus": True,
    },
    "linux": {
        "tab_selection": False,
        "model_selection": False,
        "code_effort": False,
        "permission_mode": False,
        "extended_thinking": False,
        "session_listing": True,
        "chat_session_listing": False,
        "chat_history_read": False,
        "runtime_permission_buttons": False,
        "desktop_sidebar_control": False,
        "desktop_mode_switch": False,
        "desktop_input_focus": False,
    },
}

TRANSPORT_CAPABILITY_OVERRIDES = {
    "desktop": {},
    "cli": {
        "tab_selection": True,
        "model_selection": True,
        "code_effort": True,
        "permission_mode": True,
        "extended_thinking": False,
        "runtime_permission_buttons": False,
        "desktop_sidebar_control": False,
        "desktop_mode_switch": False,
        "desktop_input_focus": False,
    },
    "none": {
        "tab_selection": False,
        "model_selection": False,
        "code_effort": False,
        "permission_mode": False,
        "extended_thinking": False,
        "session_listing": False,
        "chat_session_listing": False,
        "chat_history_read": False,
        "runtime_permission_buttons": False,
        "desktop_sidebar_control": False,
        "desktop_mode_switch": False,
        "desktop_input_focus": False,
    },
}


def normalize_platform_name(platform_name=None):
    value = (platform_name or sys.platform or "linux").lower()
    if value.startswith("linux"):
        return "linux"
    if value.startswith("darwin"):
        return "darwin"
    return "win32"


def normalize_transport_mode(transport_mode=None):
    value = (transport_mode or "").strip().lower()
    if value in {"desktop", "cli", "none"}:
        return value
    return None


def get_platform_capabilities(platform_name=None):
    normalized = normalize_platform_name(platform_name)
    return copy.deepcopy(PLATFORM_CAPABILITY_MATRIX[normalized])


def get_effective_capabilities(platform_name=None, transport_mode=None):
    capabilities = get_platform_capabilities(platform_name)
    normalized_transport = normalize_transport_mode(transport_mode)
    if normalized_transport:
        capabilities.update(TRANSPORT_CAPABILITY_OVERRIDES[normalized_transport])
    return capabilities


def capability_enabled(name, platform_name=None, transport_mode=None):
    return bool(get_effective_capabilities(platform_name, transport_mode).get(name, False))


def tab_supports_session_listing(tab, platform_name=None, transport_mode=None):
    normalized_tab = (tab or "code").lower()
    if normalized_tab == "chat":
        return capability_enabled("chat_session_listing", platform_name, transport_mode)
    return capability_enabled("session_listing", platform_name, transport_mode)


def tab_supports_history_read(tab, platform_name=None, transport_mode=None):
    normalized_tab = (tab or "code").lower()
    if normalized_tab == "chat":
        return capability_enabled("chat_history_read", platform_name, transport_mode)
    return True


def get_capability_summary_lines(platform_name=None, transport_mode=None):
    capabilities = get_effective_capabilities(platform_name, transport_mode)
    return [
        f"tab_selection={capabilities['tab_selection']}",
        f"model_selection={capabilities['model_selection']}",
        f"code_effort={capabilities['code_effort']}",
        f"permission_mode={capabilities['permission_mode']}",
        f"extended_thinking={capabilities['extended_thinking']}",
        f"chat_session_listing={capabilities['chat_session_listing']}",
        f"chat_history_read={capabilities['chat_history_read']}",
        f"runtime_permission_buttons={capabilities['runtime_permission_buttons']}",
    ]

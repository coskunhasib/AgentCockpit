from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import os
import threading

from core.data_manager import DataManager

DEFAULT_STATE_KEY = "default"
DEFAULT_CWD = os.environ.get("CLAUDE_CWD", os.path.expanduser("~"))


@dataclass
class ClaudeRuntimeState:
    cwd: str = DEFAULT_CWD
    session_id: str | None = None
    session_title: str | None = None
    tab: str = "code"
    chat_model: str = "opus"
    cowork_model: str = "opus"
    code_model: str = "opus"
    effort: str = "max"
    permission_mode: str = "bypass"
    extended_thinking: bool = True
    last_prompt: str = ""
    last_prompt_time: float = 0.0
    session_cache: dict = field(default_factory=dict)
    permission_cache: dict = field(default_factory=dict)

    @classmethod
    def from_profile(cls, profile):
        return cls(
            cwd=DEFAULT_CWD,
            tab=profile.get("tab", "code"),
            chat_model=profile.get("chat_model", profile.get("model", "opus")),
            cowork_model=profile.get("cowork_model", profile.get("model", "opus")),
            code_model=profile.get("code_model", profile.get("model", "opus")),
            effort=profile.get("effort", "max"),
            permission_mode=profile.get("permission_mode", "bypass"),
            extended_thinking=bool(profile.get("extended_thinking", True)),
        )

    def to_profile(self):
        return {
            "tab": self.tab,
            "chat_model": self.chat_model,
            "cowork_model": self.cowork_model,
            "code_model": self.code_model,
            "effort": self.effort,
            "permission_mode": self.permission_mode,
            "extended_thinking": self.extended_thinking,
        }


_state_key_var = ContextVar("claude_state_key", default=DEFAULT_STATE_KEY)
_state_lock = threading.RLock()
_states = {}


def normalize_state_key(state_key=None):
    key = state_key if state_key is not None else _state_key_var.get()
    if key in (None, ""):
        return DEFAULT_STATE_KEY
    return str(key)


@contextmanager
def bind_state_key(state_key):
    token = _state_key_var.set(normalize_state_key(state_key))
    try:
        yield normalize_state_key(state_key)
    finally:
        _state_key_var.reset(token)


def get_state_key():
    return normalize_state_key()


def set_state_key(state_key):
    _state_key_var.set(normalize_state_key(state_key))


def get_state(state_key=None):
    key = normalize_state_key(state_key)
    with _state_lock:
        if key not in _states:
            profile = DataManager.get_claude_settings(profile_id=key)
            _states[key] = ClaudeRuntimeState.from_profile(profile)
        return _states[key]


def save_profile(state_key=None):
    key = normalize_state_key(state_key)
    state = get_state(key)
    DataManager.update_claude_settings(profile_id=key, **state.to_profile())


def set_session_cache(cache, state_key=None):
    get_state(state_key).session_cache = dict(cache or {})


def get_session_cache(state_key=None):
    return get_state(state_key).session_cache


def clear_session_cache(state_key=None):
    get_state(state_key).session_cache = {}


def set_permission_cache(cache, state_key=None):
    get_state(state_key).permission_cache = dict(cache or {})


def get_permission_cache(state_key=None):
    return get_state(state_key).permission_cache


def clear_permission_cache(state_key=None):
    get_state(state_key).permission_cache = {}


def reset_state_store():
    with _state_lock:
        _states.clear()
    set_state_key(DEFAULT_STATE_KEY)

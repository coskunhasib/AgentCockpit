from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import os
import threading

from core.data_manager import DataManager

DEFAULT_STATE_KEY = "default"
CODEX_GLOBAL_STATE = os.path.join(os.path.expanduser("~"), ".codex", ".codex-global-state.json")


def _detect_default_codex_cwd():
    try:
        with open(CODEX_GLOBAL_STATE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        active_roots = data.get("active-workspace-roots") or []
        for root in active_roots:
            if root:
                return root
    except Exception:
        pass
    return os.path.expanduser("~")


@dataclass
class CodexRuntimeState:
    cwd: str = field(default_factory=_detect_default_codex_cwd)
    session_id: str | None = None
    session_title: str | None = None
    last_prompt: str = ""
    last_prompt_time: float = 0.0
    session_cache: dict = field(default_factory=dict)

    @classmethod
    def from_profile(cls, profile):
        state = cls()
        stored_cwd = (profile or {}).get("cwd")
        if stored_cwd:
            state.cwd = stored_cwd
        return state

    def to_profile(self):
        return {
            "cwd": self.cwd,
        }


_state_key_var = ContextVar("codex_state_key", default=DEFAULT_STATE_KEY)
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
            profile = DataManager.get_codex_settings(profile_id=key)
            _states[key] = CodexRuntimeState.from_profile(profile)
        return _states[key]


def save_profile(state_key=None):
    key = normalize_state_key(state_key)
    state = get_state(key)
    DataManager.update_codex_settings(profile_id=key, **state.to_profile())


def set_session_cache(cache, state_key=None):
    get_state(state_key).session_cache = dict(cache or {})


def get_session_cache(state_key=None):
    return get_state(state_key).session_cache


def clear_session_cache(state_key=None):
    get_state(state_key).session_cache = {}


def reset_state_store():
    with _state_lock:
        _states.clear()
    set_state_key(DEFAULT_STATE_KEY)

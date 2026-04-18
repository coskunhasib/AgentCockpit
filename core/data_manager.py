# core/data_manager.py
import json
import os

DATA_FILE = "hotkeys.json"
DEFAULT_CLAUDE_SETTINGS = {
    "tab": "code",
    "chat_model": "opus",
    "cowork_model": "opus",
    "code_model": "opus",
    "effort": "max",
    "permission_mode": "bypass",
    "extended_thinking": True,
}
DEFAULT_CODEX_SETTINGS = {
    "cwd": "",
}
DEFAULT_MOUSE_SPEED = 100


class DataManager:
    @staticmethod
    def _default_data():
        return {
            "settings": {"mouse_speed": DEFAULT_MOUSE_SPEED},
            "claude_profiles": {"default": DEFAULT_CLAUDE_SETTINGS.copy()},
            "codex_profiles": {"default": DEFAULT_CODEX_SETTINGS.copy()},
            "hotkeys": {
                "Masaustu": ["winleft", "d"],
                "Gorev Yon.": ["ctrl", "shift", "esc"],
                "Kopyala": ["ctrl", "c"],
                "Yapistir": ["ctrl", "v"],
            },
        }

    @staticmethod
    def _normalize_claude_settings(settings):
        stored = settings or {}
        merged = DEFAULT_CLAUDE_SETTINGS.copy()
        legacy_model = stored.get("model")
        if legacy_model:
            stored.setdefault("code_model", legacy_model)
            if legacy_model != "opus_1m":
                stored.setdefault("chat_model", legacy_model)
                stored.setdefault("cowork_model", legacy_model)
        merged.update(stored)
        return merged

    @staticmethod
    def _normalize_codex_settings(settings):
        stored = settings or {}
        merged = DEFAULT_CODEX_SETTINGS.copy()
        merged.update(stored)
        return merged

    @staticmethod
    def _normalize_data(data):
        normalized = DataManager._default_data()
        if not isinstance(data, dict):
            return normalized

        settings = data.get("settings")
        if isinstance(settings, dict):
            normalized["settings"].update(settings)
        normalized["settings"]["mouse_speed"] = int(
            normalized["settings"].get("mouse_speed", DEFAULT_MOUSE_SPEED)
        )

        hotkeys = data.get("hotkeys")
        if isinstance(hotkeys, dict):
            normalized["hotkeys"].update(hotkeys)

        profiles = data.get("claude_profiles")
        if isinstance(profiles, dict):
            for profile_id, profile in profiles.items():
                normalized["claude_profiles"][str(profile_id)] = (
                    DataManager._normalize_claude_settings(profile)
                )

        codex_profiles = data.get("codex_profiles")
        if isinstance(codex_profiles, dict):
            for profile_id, profile in codex_profiles.items():
                normalized["codex_profiles"][str(profile_id)] = (
                    DataManager._normalize_codex_settings(profile)
                )

        legacy_profile = data.get("claude")
        if isinstance(legacy_profile, dict) and "default" not in normalized["claude_profiles"]:
            normalized["claude_profiles"]["default"] = DataManager._normalize_claude_settings(
                legacy_profile
            )
        elif isinstance(legacy_profile, dict):
            normalized["claude_profiles"]["default"] = DataManager._normalize_claude_settings(
                legacy_profile
            )

        return normalized

    @staticmethod
    def load_data():
        """Load all persisted bot data."""
        if not os.path.exists(DATA_FILE):
            default_data = DataManager._default_data()
            DataManager.save_data(default_data)
            return default_data

        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return DataManager._default_data()

        return DataManager._normalize_data(data)

    @staticmethod
    def save_data(data):
        data = DataManager._normalize_data(data)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    @staticmethod
    def set_mouse_speed(speed):
        data = DataManager.load_data()
        data["settings"]["mouse_speed"] = int(speed)
        DataManager.save_data(data)

    @staticmethod
    def get_mouse_speed():
        data = DataManager.load_data()
        return data.get("settings", {}).get("mouse_speed", DEFAULT_MOUSE_SPEED)

    @staticmethod
    def add_hotkey(name, keys):
        data = DataManager.load_data()
        if "hotkeys" not in data:
            data["hotkeys"] = {}
        data["hotkeys"][name] = keys
        DataManager.save_data(data)

    @staticmethod
    def remove_hotkey(name):
        data = DataManager.load_data()
        if name in data.get("hotkeys", {}):
            del data["hotkeys"][name]
            DataManager.save_data(data)
            return True
        return False

    @staticmethod
    def get_hotkeys():
        data = DataManager.load_data()
        return data.get("hotkeys", {})

    @staticmethod
    def get_claude_settings(profile_id="default"):
        data = DataManager.load_data()
        profiles = data.get("claude_profiles", {})
        stored = profiles.get(str(profile_id))
        if stored is None:
            stored = profiles.get("default", {})
        return DataManager._normalize_claude_settings(stored)

    @staticmethod
    def update_claude_settings(profile_id="default", **kwargs):
        data = DataManager.load_data()
        profiles = data.setdefault("claude_profiles", {})
        current = DataManager._normalize_claude_settings(
            profiles.get(str(profile_id), profiles.get("default", {}))
        )
        for key, value in kwargs.items():
            if value is not None:
                current[key] = value
        profiles[str(profile_id)] = DataManager._normalize_claude_settings(current)
        DataManager.save_data(data)

    @staticmethod
    def get_codex_settings(profile_id="default"):
        data = DataManager.load_data()
        profiles = data.get("codex_profiles", {})
        stored = profiles.get(str(profile_id))
        if stored is None:
            stored = profiles.get("default", {})
        return DataManager._normalize_codex_settings(stored)

    @staticmethod
    def update_codex_settings(profile_id="default", **kwargs):
        data = DataManager.load_data()
        profiles = data.setdefault("codex_profiles", {})
        current = DataManager._normalize_codex_settings(
            profiles.get(str(profile_id), profiles.get("default", {}))
        )
        for key, value in kwargs.items():
            if value is not None:
                current[key] = value
        profiles[str(profile_id)] = DataManager._normalize_codex_settings(current)
        DataManager.save_data(data)

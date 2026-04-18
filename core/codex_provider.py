from core import codex_bridge
from core.provider_contract import SessionRecord


class CodexProvider:
    name = "codex"

    def get_transport_mode(self) -> str:
        return codex_bridge.get_transport_mode()

    def get_profile_summary(self) -> str:
        return codex_bridge.get_profile_summary()

    def get_session_title(self) -> str | None:
        return codex_bridge.get_session_title()

    def get_tab(self) -> str:
        return "codex"

    def set_tab(self, tab: str) -> bool:
        return tab == "codex"

    def get_cwd(self) -> str:
        return codex_bridge.get_cwd()

    def set_cwd(self, cwd: str) -> bool:
        return codex_bridge.set_cwd(cwd)

    def clear_session(self) -> None:
        codex_bridge.clear_session()

    def set_session(self, session_id: str | None, title: str | None = None) -> bool:
        return codex_bridge.set_session(session_id, title=title)

    def set_model(self, model_key: str) -> bool:
        return False

    def set_effort(self, effort_key: str) -> bool:
        return False

    def set_permission_mode(self, mode_key: str) -> bool:
        return False

    def set_extended_thinking(self, enabled: bool) -> bool:
        return False

    def sync_settings(self, focus_input: bool = False) -> tuple[bool, str]:
        return (
            False,
            "Codex provider tab/model/effort ayari kullanmiyor; masaustu pencere ve rollout loglari ile calisiyor.",
        )

    def list_sessions(
        self, limit: int = 10, mode: str | None = None
    ) -> list[SessionRecord]:
        sessions = []
        for item in codex_bridge.list_sessions(limit=limit):
            sessions.append(
                SessionRecord(
                    id=item.get("id"),
                    title=item.get("title") or "",
                    cwd=item.get("cwd", "") or "",
                    source=item.get("source", "") or "",
                    last_activity=item.get("updated_at"),
                )
            )
        return sessions

    def read_session_history(
        self, session_id: str | None = None, last_n: int = 10
    ) -> str:
        return codex_bridge.read_session_history(session_id=session_id, last_n=last_n)


CODEX_PROVIDER = CodexProvider()

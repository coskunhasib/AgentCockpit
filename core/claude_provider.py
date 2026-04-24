from __future__ import annotations
from core import claude_bridge
from core.provider_contract import SessionRecord


class ClaudeProvider:
    name = "claude"

    def get_transport_mode(self) -> str:
        return claude_bridge.get_transport_mode()

    def get_profile_summary(self) -> str:
        return claude_bridge.get_profile_summary()

    def get_session_title(self) -> str | None:
        return claude_bridge.get_session_title()

    def get_tab(self) -> str:
        return claude_bridge.get_tab()

    def set_tab(self, tab: str) -> bool:
        return claude_bridge.set_tab(tab)

    def get_cwd(self) -> str:
        return claude_bridge.get_cwd()

    def set_cwd(self, cwd: str) -> bool:
        return claude_bridge.set_cwd(cwd)

    def clear_session(self) -> None:
        claude_bridge.clear_session()

    def set_session(self, session_id: str | None, title: str | None = None) -> bool:
        return claude_bridge.set_session(session_id, title=title)

    def set_model(self, model_key: str) -> bool:
        return claude_bridge.set_model(model_key)

    def set_effort(self, effort_key: str) -> bool:
        return claude_bridge.set_effort(effort_key)

    def set_permission_mode(self, mode_key: str) -> bool:
        return claude_bridge.set_permission_mode(mode_key)

    def set_extended_thinking(self, enabled: bool) -> bool:
        return claude_bridge.set_extended_thinking(enabled)

    def sync_settings(self, focus_input: bool = False) -> tuple[bool, str]:
        return claude_bridge.sync_claude_settings(focus_input)

    def list_sessions(self, limit: int = 10, mode: str | None = None) -> list[SessionRecord]:
        sessions = []
        for item in claude_bridge.list_sessions(limit=limit, mode=mode):
            sessions.append(
                SessionRecord(
                    id=item.get("id"),
                    title=item.get("title") or "",
                    cwd=item.get("cwd", "") or "",
                    source=item.get("source", "") or "",
                    last_activity=item.get("lastActivity"),
                )
            )
        return sessions

    def read_session_history(
        self, session_id: str | None = None, last_n: int = 10
    ) -> str:
        return claude_bridge.read_session_history(session_id=session_id, last_n=last_n)


CLAUDE_PROVIDER = ClaudeProvider()

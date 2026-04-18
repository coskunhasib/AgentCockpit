import unittest
from unittest.mock import patch

from core.codex_provider import CodexProvider


class CodexProviderTests(unittest.TestCase):
    def test_list_sessions_converts_bridge_payload_to_records(self):
        provider = CodexProvider()
        with patch(
            "core.codex_provider.codex_bridge.list_sessions",
            return_value=[
                {
                    "id": "codex-1",
                    "title": "Playground session",
                    "cwd": "C:/demo",
                    "source": "codex",
                    "updated_at": "2026-04-16T00:00:00Z",
                }
            ],
        ):
            sessions = provider.list_sessions(limit=1)

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].id, "codex-1")
        self.assertEqual(sessions[0].title, "Playground session")
        self.assertEqual(sessions[0].cwd, "C:/demo")
        self.assertEqual(sessions[0].source, "codex")

    def test_sync_settings_is_explicitly_unsupported(self):
        provider = CodexProvider()
        result = provider.sync_settings()
        self.assertEqual(
            result,
            (
                False,
                "Codex provider tab/model/effort ayari kullanmiyor; masaustu pencere ve rollout loglari ile calisiyor.",
            ),
        )


if __name__ == "__main__":
    unittest.main()

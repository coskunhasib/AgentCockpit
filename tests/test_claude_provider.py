import unittest
from unittest.mock import patch

from core.claude_provider import ClaudeProvider


class ClaudeProviderTests(unittest.TestCase):
    def test_list_sessions_converts_bridge_payload_to_records(self):
        provider = ClaudeProvider()
        with patch(
            "core.claude_provider.claude_bridge.list_sessions",
            return_value=[
                {
                    "id": "abc",
                    "title": "Demo Session",
                    "cwd": "C:/demo",
                    "source": "code",
                    "lastActivity": "2026-04-16T00:00:00Z",
                }
            ],
        ):
            sessions = provider.list_sessions(limit=1, mode="code")

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].id, "abc")
        self.assertEqual(sessions[0].title, "Demo Session")
        self.assertEqual(sessions[0].cwd, "C:/demo")
        self.assertEqual(sessions[0].source, "code")

    def test_sync_settings_delegates_to_bridge(self):
        provider = ClaudeProvider()
        with patch(
            "core.claude_provider.claude_bridge.sync_claude_settings",
            return_value=(True, "ok"),
        ) as mocked:
            result = provider.sync_settings(True)

        mocked.assert_called_once_with(True)
        self.assertEqual(result, (True, "ok"))


if __name__ == "__main__":
    unittest.main()

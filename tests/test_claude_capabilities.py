import unittest

from core.claude_capabilities import (
    capability_enabled,
    get_effective_capabilities,
    get_platform_capabilities,
    tab_supports_history_read,
    tab_supports_session_listing,
)


class ClaudeCapabilitiesTests(unittest.TestCase):
    def test_windows_capabilities_include_chat_support(self):
        capabilities = get_platform_capabilities("win32")
        self.assertTrue(capabilities["chat_session_listing"])
        self.assertTrue(capabilities["chat_history_read"])

    def test_linux_disables_desktop_only_features(self):
        self.assertFalse(capability_enabled("extended_thinking", "linux"))
        self.assertFalse(tab_supports_session_listing("chat", "linux"))
        self.assertFalse(tab_supports_history_read("chat", "linux"))
        self.assertTrue(tab_supports_session_listing("code", "linux"))

    def test_cli_transport_disables_desktop_only_controls(self):
        capabilities = get_effective_capabilities("win32", "cli")
        self.assertTrue(capabilities["model_selection"])
        self.assertTrue(capabilities["code_effort"])
        self.assertFalse(capabilities["extended_thinking"])
        self.assertFalse(capabilities["runtime_permission_buttons"])
        self.assertFalse(capabilities["desktop_sidebar_control"])

    def test_none_transport_disables_all_runtime_features(self):
        capabilities = get_effective_capabilities("win32", "none")
        self.assertFalse(capabilities["tab_selection"])
        self.assertFalse(capabilities["model_selection"])
        self.assertFalse(capabilities["session_listing"])
        self.assertFalse(capabilities["chat_history_read"])


if __name__ == "__main__":
    unittest.main()

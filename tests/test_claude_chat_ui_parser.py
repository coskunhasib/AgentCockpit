import unittest

from core.claude_chat_ui_parser import build_chat_sessions, format_visible_chat_history


CHAT_UI = {
    "page_not_found_text": "Page not found",
    "home_greeting_text": "How can I help you today?",
    "more_options_prefix": "More options for ",
    "new_chat_button_prefixes": ["New chat"],
    "session_excluded_buttons": ["Menu", "Chat", "Code"],
    "history_chrome_texts": ["Reply...", "How can I help you today?"],
    "history_open_prefixes": ["Open "],
    "history_artifact_suffixes": [". Open artifact."],
    "history_action_buttons": ["Copy", "Retry"],
    "history_greeting_prefixes": ["good morning", "good evening"],
    "role_split_left_threshold": 1000,
}


class ClaudeChatUiParserTests(unittest.TestCase):
    def test_build_chat_sessions_filters_sidebar_noise(self):
        sessions = build_chat_sessions(
            [
                {"text": "More options for Feature chat", "left": 20, "right": 120, "top": 300, "bottom": 320},
                {"text": "Feature chat", "left": 20, "right": 220, "top": 320, "bottom": 340},
                {"text": "Menu", "left": 20, "right": 100, "top": 100, "bottom": 120},
                {"text": "New chat", "left": 20, "right": 120, "top": 180, "bottom": 200},
            ],
            CHAT_UI,
            limit=10,
        )
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["title"], "Feature chat")

    def test_format_visible_chat_history_splits_roles(self):
        rendered = format_visible_chat_history(
            text_items=[
                {"text": "Claude cevabi satir 1", "left": 500, "right": 800, "top": 200, "bottom": 220},
                {"text": "Claude cevabi satir 2", "left": 500, "right": 800, "top": 230, "bottom": 250},
                {"text": "Kullanici mesaji", "left": 1100, "right": 1300, "top": 320, "bottom": 340},
            ],
            button_items=[],
            chat_ui=CHAT_UI,
            last_n=10,
            page_not_found=False,
            home_greeting=False,
        )
        self.assertIn("CLAUDE", rendered)
        self.assertIn("SEN", rendered)


if __name__ == "__main__":
    unittest.main()

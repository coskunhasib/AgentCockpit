import unittest
from unittest.mock import patch

from core import bot_engine


class _FakeTask:
    def __init__(self, done=False):
        self._done = done

    def done(self):
        return self._done


def _keyboard_labels(markup):
    rows = []
    container = getattr(markup, "keyboard", None)
    if container is None:
        container = getattr(markup, "inline_keyboard", [])
    for row in container:
        labels = []
        for button in row:
            labels.append(getattr(button, "text", button))
        rows.append(labels)
    return rows


class BotEngineCapabilityTests(unittest.TestCase):
    def tearDown(self):
        bot_engine._codex_delivery_tasks.clear()

    def test_mode_keyboard_includes_codex_entry(self):
        labels = _keyboard_labels(bot_engine.get_mode_keyboard())
        self.assertIn([bot_engine.button_label("Codex")], labels)

    def test_code_keyboard_shows_code_controls_on_desktop(self):
        with patch("core.bot_engine.get_tab", return_value="code"), patch(
            "core.bot_engine.get_transport_mode", return_value="desktop"
        ):
            labels = _keyboard_labels(bot_engine.get_claude_keyboard())

        self.assertEqual(labels[0], [bot_engine.button_label("Ekran Al"), bot_engine.button_label("Durum")])
        self.assertIn([bot_engine.button_label("Session Sec"), bot_engine.button_label("Yeni Session")], labels)
        self.assertIn([bot_engine.button_label("Sekme"), bot_engine.button_label("Model")], labels)
        self.assertIn([bot_engine.button_label("Effort"), bot_engine.button_label("Izin Modu")], labels)
        self.assertNotIn(["Thinking", "Durum"], labels)

    def test_conversation_keyboard_hides_extended_thinking_on_cli(self):
        with patch("core.bot_engine.get_tab", return_value="chat"), patch(
            "core.bot_engine.get_transport_mode", return_value="cli"
        ):
            labels = _keyboard_labels(bot_engine.get_claude_keyboard())

        self.assertEqual(labels[0], [bot_engine.button_label("Ekran Al"), bot_engine.button_label("Durum")])
        self.assertIn([bot_engine.button_label("Session Sec"), bot_engine.button_label("Yeni Session")], labels)
        self.assertIn([bot_engine.button_label("Sekme"), bot_engine.button_label("Model")], labels)
        self.assertNotIn(["Thinking", "Durum"], labels)

    def test_common_action_positions_align_across_modes(self):
        with patch("core.bot_engine.get_tab", return_value="code"), patch(
            "core.bot_engine.get_transport_mode", return_value="desktop"
        ):
            agentcockpit = _keyboard_labels(bot_engine.get_dynamic_keyboard())
            claude = _keyboard_labels(bot_engine.get_claude_keyboard())
            codex = _keyboard_labels(bot_engine.get_codex_keyboard())

        self.assertEqual(agentcockpit[0][0], bot_engine.button_label("Ekran Al"))
        self.assertEqual(claude[0][0], bot_engine.button_label("Ekran Al"))
        self.assertEqual(codex[0][0], bot_engine.button_label("Ekran Al"))
        self.assertEqual(claude[0][1], bot_engine.button_label("Durum"))
        self.assertEqual(codex[0][1], bot_engine.button_label("Durum"))
        self.assertEqual(agentcockpit[-1], [bot_engine.button_label("Ana Menu")])
        self.assertEqual(claude[-1], [bot_engine.button_label("Ana Menu")])
        self.assertEqual(codex[-1], [bot_engine.button_label("Ana Menu")])

    def test_icon_labels_are_canonicalized_for_handlers(self):
        self.assertEqual(
            bot_engine.canonical_button_label(bot_engine.button_label("Ekran Al")),
            "Ekran Al",
        )
        self.assertEqual(
            bot_engine.canonical_button_label(bot_engine.button_label("Ana Menu")),
            "Ana Menu",
        )
        self.assertEqual(
            bot_engine.canonical_button_label(bot_engine.button_label("Hotkey Ctrl-L")),
            "Hotkey Ctrl-L",
        )

    def test_resolve_codex_session_info_accepts_old_truncated_callback(self):
        cache = {
            "codses:019d8862-bde3-7863-9f18-0cd53b007c5b": {
                "id": "019d8862-bde3-7863-9f18-0cd53b007c5b",
                "title": "Uzun baslik",
                "display_title": "Kisa baslik",
                "cwd": "C:/demo",
                "source": "codex",
            }
        }
        with patch("core.bot_engine.codex_state.get_session_cache", return_value=cache):
            info = bot_engine._resolve_codex_session_info(
                "codses:019d8862-bde3-7863"
            )

        self.assertIsNotNone(info)
        self.assertEqual(info["id"], "019d8862-bde3-7863-9f18-0cd53b007c5b")

    def test_resolve_codex_session_info_falls_back_to_live_list(self):
        with patch("core.bot_engine.codex_state.get_session_cache", return_value={}), patch(
            "core.bot_engine.codex_bridge.list_sessions",
            return_value=[
                {
                    "id": "019d8867-c84a-73b2-9c25-e2fb816afd7a",
                    "title": "Uzun baslik",
                    "display_title": "Projeyi kapsamlı incele",
                    "cwd": "//demo",
                    "source": "codex",
                }
            ],
        ):
            info = bot_engine._resolve_codex_session_info(
                "codses:019d8867-c84a-73b2"
            )

        self.assertIsNotNone(info)
        self.assertEqual(info["display_title"], "Projeyi kapsamlı incele")

    def test_codex_session_keyboard_returns_full_text_summary(self):
        with patch(
            "core.bot_engine.codex_bridge.list_sessions",
            return_value=[
                {
                    "id": "session-1",
                    "title": "Bu cok uzun bir session basligi ve tam gorunmeli",
                    "display_title": "Bu cok uzun bir session basligi ve tam gorunmeli",
                    "cwd": "C:/Demo/Workspace",
                    "source": "codex",
                }
            ],
        ):
            markup, count, summary = bot_engine.get_codex_session_inline_keyboard()

        self.assertEqual(count, 1)
        self.assertIn("Bu cok uzun bir session basligi ve tam gorunmeli", summary)
        self.assertEqual(_keyboard_labels(markup)[0], ["1. Workspace"])

    def test_has_running_codex_task_only_for_incomplete_tasks(self):
        bot_engine._codex_delivery_tasks["123"] = _FakeTask(done=False)
        bot_engine._codex_delivery_tasks["456"] = _FakeTask(done=True)

        self.assertTrue(bot_engine._has_running_codex_task("123"))
        self.assertFalse(bot_engine._has_running_codex_task("456"))


if __name__ == "__main__":
    unittest.main()

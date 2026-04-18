import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import claude_state, data_manager


class ClaudeStateTests(unittest.TestCase):
    def tearDown(self):
        claude_state.reset_state_store()

    def test_runtime_state_is_isolated_per_key(self):
        claude_state.set_state_key("chat-1")
        state_one = claude_state.get_state()
        state_one.tab = "chat"

        claude_state.set_state_key("chat-2")
        state_two = claude_state.get_state()
        state_two.tab = "code"

        self.assertNotEqual(state_one, state_two)
        self.assertEqual(state_one.tab, "chat")
        self.assertEqual(state_two.tab, "code")

    def test_save_profile_persists_current_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "hotkeys.json"
            with patch.object(data_manager, "DATA_FILE", str(data_path)):
                claude_state.reset_state_store()
                claude_state.set_state_key("u-test")
                state = claude_state.get_state()
                state.tab = "cowork"
                state.code_model = "opus_1m"
                claude_state.save_profile()

                stored = data_manager.DataManager.get_claude_settings("u-test")

        self.assertEqual(stored["tab"], "cowork")
        self.assertEqual(stored["code_model"], "opus_1m")


if __name__ == "__main__":
    unittest.main()

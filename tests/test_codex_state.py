import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import codex_state, data_manager


class CodexStateTests(unittest.TestCase):
    def tearDown(self):
        codex_state.reset_state_store()

    def test_runtime_state_is_isolated_per_key(self):
        codex_state.set_state_key("chat-1")
        state_one = codex_state.get_state()
        state_one.cwd = "C:/one"

        codex_state.set_state_key("chat-2")
        state_two = codex_state.get_state()
        state_two.cwd = "C:/two"

        self.assertNotEqual(state_one, state_two)
        self.assertEqual(state_one.cwd, "C:/one")
        self.assertEqual(state_two.cwd, "C:/two")

    def test_save_profile_persists_current_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "hotkeys.json"
            with patch.object(data_manager, "DATA_FILE", str(data_path)):
                codex_state.reset_state_store()
                codex_state.set_state_key("u-test")
                state = codex_state.get_state()
                state.cwd = "C:/workspace"
                codex_state.save_profile()

                stored = data_manager.DataManager.get_codex_settings("u-test")

        self.assertEqual(stored["cwd"], "C:/workspace")


if __name__ == "__main__":
    unittest.main()

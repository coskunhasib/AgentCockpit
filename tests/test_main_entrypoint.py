import unittest
from pathlib import Path

import launcher
import main


class MainEntrypointTests(unittest.TestCase):
    def test_default_entrypoint_runs_unified_v2_stack(self):
        calls = []
        original_run_stack = launcher.run_stack
        original_legacy = main.run_legacy_application
        try:
            launcher.run_stack = lambda: calls.append("unified")
            main.run_legacy_application = lambda: calls.append("legacy")

            main.run_application([])

            self.assertEqual(calls, ["unified"])
        finally:
            launcher.run_stack = original_run_stack
            main.run_legacy_application = original_legacy

    def test_legacy_flag_keeps_old_core_bot_available(self):
        calls = []
        original_run_stack = launcher.run_stack
        original_legacy = main.run_legacy_application
        try:
            launcher.run_stack = lambda: calls.append("unified")
            main.run_legacy_application = lambda: calls.append("legacy")

            main.run_application(["--legacy"])

            self.assertEqual(calls, ["legacy"])
        finally:
            launcher.run_stack = original_run_stack
            main.run_legacy_application = original_legacy

    def test_main_restart_delegates_to_v2_bootstrap_with_main_script(self):
        calls = []
        original_restart = launcher.create_venv_and_restart
        try:
            launcher.create_venv_and_restart = lambda script_path=None: calls.append(script_path)

            main.create_venv_and_restart()

            self.assertEqual(calls, [str(Path(main.__file__).resolve())])
        finally:
            launcher.create_venv_and_restart = original_restart

    def test_v2_no_longer_contains_second_bot_entrypoints(self):
        root = Path(main.__file__).resolve().parent
        self.assertFalse((root / "v2" / "main.py").exists())
        self.assertFalse((root / "v2" / "start.py").exists())
        self.assertFalse((root / "v2" / "start.bat").exists())


if __name__ == "__main__":
    unittest.main()

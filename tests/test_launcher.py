import os
import unittest
from pathlib import Path
from unittest.mock import patch

import launcher


class LauncherTests(unittest.TestCase):
    def test_autostart_keeps_phone_bridge_after_launcher_exit(self):
        with patch.dict(os.environ, {"AGENTCOCKPIT_AUTOSTART": "true"}, clear=False), patch.object(
            launcher.sys, "argv", ["launcher.py"]
        ):
            self.assertTrue(launcher._keep_bridge_after_launcher_exit())

    def test_manual_run_cleans_phone_bridge_by_default(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(launcher.sys, "argv", ["launcher.py"]):
            self.assertFalse(launcher._keep_bridge_after_launcher_exit())

    def test_explicit_cleanup_override_wins_in_autostart(self):
        with patch.dict(
            os.environ,
            {"AGENTCOCKPIT_AUTOSTART": "true", "AGENTCOCKPIT_KEEP_BRIDGE_ON_EXIT": "false"},
            clear=False,
        ), patch.object(launcher.sys, "argv", ["launcher.py"]):
            self.assertFalse(launcher._keep_bridge_after_launcher_exit())

    def test_runner_stop_includes_bore_tunnel_process(self):
        runner = Path(__file__).resolve().parents[1] / "runner.sh"
        self.assertIn("/.agentcockpit/runtime/bin/bore", runner.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

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

    def _runner_stop_namespace(self):
        """Exec runner.sh's embedded stop script up to (but not including) the
        process-killing loop, so its matching logic can be exercised without
        ever signalling real processes."""
        runner = Path(__file__).resolve().parents[1] / "runner.sh"
        text = runner.read_text(encoding="utf-8")
        start = text.index("<<'PY'\n") + len("<<'PY'\n")
        end = text.index("\nPY", start)
        script = text[start:end].split("\nfor sig in (", 1)[0]
        namespace = {}
        with patch.dict(os.environ, {"PROJECT_ROOT_ENV": "/srv/AgentCockpit"}, clear=False):
            exec(compile(script, "runner.sh:PY", "exec"), namespace)  # noqa: S102
        return namespace

    def test_runner_stop_matches_bundled_tunnel_binaries(self):
        patterns = self._runner_stop_namespace()["patterns"]
        self.assertIn("/srv/AgentCockpit/.agentcockpit/runtime/bin/bore", patterns)
        self.assertIn("/srv/AgentCockpit/.agentcockpit/runtime/bin/cloudflared", patterns)

    def test_runner_stop_matches_relocated_and_path_installed_tunnels(self):
        is_our_tunnel = self._runner_stop_namespace()["is_our_tunnel"]
        # The bug this guards: a $PATH/Homebrew cloudflared or bore (no bundled
        # path, no env override) must still be matched by its argv signature.
        self.assertTrue(
            is_our_tunnel(
                "/opt/homebrew/bin/cloudflared tunnel --url http://127.0.0.1:8765 --no-autoupdate"
            )
        )
        self.assertTrue(
            is_our_tunnel(
                "/opt/homebrew/bin/bore local --local-host 127.0.0.1 --to 159.223.110.159 --port 41000 8765"
            )
        )
        # Unrelated tunnels must NOT be killed.
        self.assertFalse(is_our_tunnel("/usr/bin/cloudflared tunnel run my-named-tunnel"))
        self.assertFalse(is_our_tunnel("/usr/local/bin/bore server --secret abc"))


if __name__ == "__main__":
    unittest.main()

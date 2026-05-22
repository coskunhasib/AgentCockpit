import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autostart


class AutostartTests(unittest.TestCase):
    def test_register_mac_no_start_writes_launch_agent_without_bootstrap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bot_dir = root / "New project"
            python_exe = bot_dir / "venv" / "bin" / "python3"
            main_py = bot_dir / "main.py"
            launch_agents_dir = root / "LaunchAgents"
            python_exe.parent.mkdir(parents=True)
            python_exe.touch()
            main_py.parent.mkdir(parents=True, exist_ok=True)
            main_py.touch()

            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)

                class Result:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return Result()

            with patch("autostart.subprocess.run", side_effect=fake_run), patch(
                "autostart.os.getuid", return_value=501
            ), patch("autostart.shutil.which", return_value="/usr/bin/screen"):
                autostart.register_mac(
                    start_now=False,
                    bot_dir=bot_dir,
                    launch_agents_dir=launch_agents_dir,
                )

            plist_path = launch_agents_dir / f"{autostart.APP_LABEL}.plist"
            payload = plistlib.loads(plist_path.read_bytes())

            self.assertEqual(payload["Label"], autostart.APP_LABEL)
            self.assertEqual(
                payload["ProgramArguments"],
                [
                    "/usr/bin/screen",
                    "-DmS",
                    autostart.MAC_SCREEN_SESSION,
                    str(python_exe),
                    str(main_py),
                ],
            )
            self.assertEqual(payload["WorkingDirectory"], str(bot_dir))
            self.assertEqual(payload["EnvironmentVariables"]["PYTHONIOENCODING"], "utf-8")
            self.assertTrue((bot_dir / "logs").is_dir())
            self.assertFalse(any("bootstrap" in command for command in calls))
            self.assertIn(["launchctl", "enable", "gui/501/com.agentcockpit.bot"], calls)
            self.assertIn(
                ["/usr/bin/screen", "-S", autostart.MAC_SCREEN_SESSION, "-X", "quit"],
                calls,
            )

    def test_systemd_quote_preserves_paths_with_spaces(self):
        self.assertEqual(
            autostart._systemd_quote('/tmp/New project/main.py'),
            '"/tmp/New project/main.py"',
        )


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core import bot_engine


class BotEngineEventLoopTests(unittest.TestCase):
    def test_get_or_create_event_loop_creates_when_missing(self):
        created_loop = Mock()
        with patch(
            "core.bot_engine.asyncio.get_event_loop",
            side_effect=RuntimeError("no current event loop"),
        ), patch(
            "core.bot_engine.asyncio.new_event_loop", return_value=created_loop
        ) as new_event_loop, patch(
            "core.bot_engine.asyncio.set_event_loop"
        ) as set_event_loop:
            loop = bot_engine._get_or_create_event_loop()

        self.assertIs(loop, created_loop)
        new_event_loop.assert_called_once()
        set_event_loop.assert_called_once_with(created_loop)

    def test_get_or_create_event_loop_reuses_open_loop(self):
        existing_loop = Mock()
        existing_loop.is_closed.return_value = False

        with patch(
            "core.bot_engine.asyncio.get_event_loop", return_value=existing_loop
        ), patch("core.bot_engine.asyncio.new_event_loop") as new_event_loop, patch(
            "core.bot_engine.asyncio.set_event_loop"
        ) as set_event_loop:
            loop = bot_engine._get_or_create_event_loop()

        self.assertIs(loop, existing_loop)
        new_event_loop.assert_not_called()
        set_event_loop.assert_not_called()

    def test_get_or_create_event_loop_recreates_closed_loop(self):
        closed_loop = Mock()
        closed_loop.is_closed.return_value = True
        created_loop = Mock()

        with patch(
            "core.bot_engine.asyncio.get_event_loop", return_value=closed_loop
        ), patch(
            "core.bot_engine.asyncio.new_event_loop", return_value=created_loop
        ) as new_event_loop, patch(
            "core.bot_engine.asyncio.set_event_loop"
        ) as set_event_loop:
            loop = bot_engine._get_or_create_event_loop()

        self.assertIs(loop, created_loop)
        new_event_loop.assert_called_once()
        set_event_loop.assert_called_once_with(created_loop)

    def test_kill_old_instances_keeps_env_protected_parent_pid(self):
        ps_output = "\n".join(
            [
                "100 1 /usr/bin/python3 /Users/example/AgentCockpit/main.py",
                "200 100 /Users/example/AgentCockpit/venv/bin/python /Users/example/AgentCockpit/main.py",
                "300 1 /usr/bin/python3 /Users/example/AgentCockpit/main.py",
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            bot_engine, "LOCK_FILE", os.path.join(tmp_dir, "bot.lock")
        ), patch("core.bot_engine.os.getpid", return_value=200), patch(
            "core.bot_engine.os.getppid", return_value=100
        ), patch.dict(
            os.environ, {"AGENTCOCKPIT_PARENT_PIDS": "100"}, clear=False
        ), patch(
            "subprocess.check_output", return_value=ps_output
        ), patch(
            "core.platform_utils.kill_process"
        ) as kill_process, patch(
            "core.bot_engine.time.sleep"
        ), patch(
            "atexit.register"
        ), patch(
            "signal.signal"
        ):
            bot_engine._kill_old_instances()

        kill_process.assert_called_once_with(300)

    def test_agentcockpit_command_detection_ignores_shell_probe_text(self):
        cmd = (
            "/bin/zsh -c ps -axww -o pid,command | "
            "rg 'AgentCockpit|main.py|python3' && "
            "/Users/example/AgentCockpit/venv/bin/python3 -m json.tool"
        )

        self.assertFalse(bot_engine._is_agentcockpit_bot_command(cmd))

    def test_agentcockpit_command_detection_accepts_real_python_main(self):
        cmd = (
            "/Users/example/AgentCockpit/venv/bin/python3 "
            "/Users/example/AgentCockpit/main.py --autostart"
        )

        self.assertTrue(bot_engine._is_agentcockpit_bot_command(cmd))

    def test_agentcockpit_command_detection_handles_install_path_with_spaces(self):
        # Regression: shlex.split() broke an install path containing a space
        # (".../New project/..."), so a genuine running instance was treated as
        # unrelated and never recognized. Match it against the real project root.
        root = str(Path(bot_engine.__file__).resolve().parents[1])
        cmd = f"{root}/venv/bin/python {root}/main.py"
        self.assertTrue(bot_engine._is_agentcockpit_bot_command(cmd))

        framework = (
            "/Library/Frameworks/Python.framework/Versions/3.13/Resources/"
            "Python.app/Contents/MacOS/Python"
        )
        self.assertTrue(
            bot_engine._is_agentcockpit_bot_command(f"{framework} {root}/main.py --autostart")
        )

    def test_agentcockpit_command_detection_rejects_unrelated_python(self):
        # A python process that merely lives under a similar path but is not our
        # entry script must not be matched (would risk killing a random process).
        self.assertFalse(
            bot_engine._is_agentcockpit_bot_command("/usr/bin/python3 -m http.server 8000")
        )
        self.assertFalse(
            bot_engine._is_agentcockpit_bot_command("/usr/bin/python3 /tmp/other/main.py")
        )

    def test_bot_instance_cleanup_skips_when_launcher_already_did_it(self):
        with patch.dict(os.environ, {"AGENTCOCKPIT_BOT_CLEANUP_DONE": "1"}, clear=False), patch(
            "core.bot_engine._kill_old_instances"
        ) as kill_old_instances, patch("core.bot_engine.record_runtime_event") as record_event:
            did_cleanup = bot_engine._ensure_bot_instance_cleanup()

        self.assertFalse(did_cleanup)
        kill_old_instances.assert_not_called()
        record_event.assert_called_once_with(
            "bot_engine_cleanup_skipped",
            reason="already_done_by_launcher",
        )

    def test_bot_instance_cleanup_runs_when_launcher_did_not_do_it(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "core.bot_engine._kill_old_instances"
        ) as kill_old_instances:
            did_cleanup = bot_engine._ensure_bot_instance_cleanup()

        self.assertTrue(did_cleanup)
        kill_old_instances.assert_called_once()


if __name__ == "__main__":
    unittest.main()

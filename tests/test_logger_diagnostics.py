import io
import logging
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import core.logger as diagnostics


class LoggerDiagnosticsTests(unittest.TestCase):
    def test_redact_text_removes_known_secret_shapes(self):
        fake_github_token = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
        text = (
            "TELEGRAM_TOKEN=123456:AAAAAAAAAAAAAAAAAAAAAAAAA "
            "https://example.test/app?token=secret-value "
            "X-AgentCockpit-Admin: admin-secret "
            f"{fake_github_token} "
            "/tmp/private-file"
        )

        redacted = diagnostics.redact_text(text)

        self.assertNotIn("123456:AAAAAAAA", redacted)
        self.assertNotIn("secret-value", redacted)
        self.assertNotIn("admin-secret", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", redacted)
        self.assertNotIn("/tmp/private-file", redacted)
        self.assertIn("<redacted>", redacted)

    def test_redact_text_masks_token_inside_telegram_api_url(self):
        text = (
            "HTTP Request: POST "
            'https://api.telegram.org/bot123456789:AAfake-token-abcdef/getMe "HTTP/1.1 200 OK"'
        )

        redacted = diagnostics.redact_text(text)

        self.assertNotIn("123456789:AAfake-token", redacted)
        self.assertIn("/bot<redacted>/getMe", redacted)

    def test_harden_stdlib_logging_redacts_and_silences_httpx(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        root.addHandler(handler)
        httpx_logger = logging.getLogger("httpx")
        try:
            diagnostics.harden_stdlib_logging()

            self.assertEqual(httpx_logger.getEffectiveLevel(), logging.WARNING)

            httpx_logger.info(
                'HTTP Request: POST %s "%s"',
                "https://api.telegram.org/bot123456789:AAfake-token-abcdef/getMe",
                "HTTP/1.1 200 OK",
            )
            httpx_logger.warning(
                'HTTP Request: POST %s "%s"',
                "https://api.telegram.org/bot123456789:AAfake-token-abcdef/getMe",
                "HTTP/1.1 429 Too Many Requests",
            )
        finally:
            root.removeHandler(handler)

        output = stream.getvalue()
        self.assertNotIn("200 OK", output)
        self.assertIn("429", output)
        self.assertNotIn("123456789:AAfake-token", output)
        self.assertIn("/bot<redacted>/getMe", output)

    def test_collect_diagnostics_snapshot_contains_core_process_fields(self):
        snapshot = diagnostics.collect_diagnostics_snapshot("unit-test")

        self.assertEqual(snapshot["schema"], 1)
        self.assertEqual(snapshot["process"], "unit-test")
        self.assertEqual(snapshot["pid"], os.getpid())
        self.assertIn("threads", snapshot)
        self.assertIn("resource", snapshot)
        self.assertIn("current_rss", snapshot["resource"])
        self.assertIn("disk", snapshot)

    def test_resource_snapshot_keeps_current_rss_when_resource_module_is_unavailable(self):
        with patch.object(diagnostics, "resource", None), patch.object(
            diagnostics, "current_rss_bytes", return_value=123456
        ):
            snapshot = diagnostics._resource_snapshot()

        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["current_rss"], 123456)
        self.assertEqual(snapshot["current_rss_units"], "bytes")

    def test_windows_rss_path_uses_working_set_reader(self):
        with patch.object(diagnostics.os, "name", "nt"), patch.object(
            diagnostics, "_read_windows_rss_bytes", return_value=654321
        ) as windows_reader:
            value = diagnostics._read_current_rss_bytes()

        self.assertEqual(value, 654321)
        windows_reader.assert_called_once_with()

    def test_runtime_maintenance_thread_is_independent_from_heartbeat(self):
        original = diagnostics._MAINTENANCE_THREAD_STARTED
        fake_thread = unittest.mock.Mock()
        try:
            diagnostics._MAINTENANCE_THREAD_STARTED = False
            with patch.object(diagnostics.threading, "Thread", return_value=fake_thread) as thread:
                diagnostics.start_runtime_maintenance(interval=60)

            thread.assert_called_once()
            self.assertEqual(
                thread.call_args.kwargs["name"],
                "agentcockpit-runtime-maintenance",
            )
            self.assertTrue(thread.call_args.kwargs["daemon"])
            fake_thread.start.assert_called_once_with()
        finally:
            diagnostics._MAINTENANCE_THREAD_STARTED = original

    def test_runtime_maintenance_lock_is_process_wide(self):
        original_log_dir = diagnostics.LOG_DIR
        try:
            with tempfile.TemporaryDirectory() as tmp:
                diagnostics.LOG_DIR = tmp
                child_code = (
                    "import sys; "
                    "import core.logger as diagnostics; "
                    "diagnostics.LOG_DIR = sys.argv[1]; "
                    "lock = diagnostics._interprocess_maintenance_lock(); "
                    "acquired = lock.__enter__(); "
                    "print(int(acquired)); "
                    "lock.__exit__(None, None, None)"
                )
                with diagnostics._interprocess_maintenance_lock() as acquired:
                    self.assertTrue(acquired)
                    child = subprocess.run(
                        [sys.executable, "-c", child_code, tmp],
                        cwd=diagnostics.PROJECT_ROOT,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=True,
                    )

                self.assertEqual(child.stdout.strip(), "0")
        finally:
            diagnostics.LOG_DIR = original_log_dir

    def test_runtime_maintenance_prunes_old_artifacts_and_caps_stdio_log(self):
        original = {
            "LOG_DIR": diagnostics.LOG_DIR,
            "CRASH_DIR": diagnostics.CRASH_DIR,
            "DIAGNOSTIC_DIR": diagnostics.DIAGNOSTIC_DIR,
            "APP_LOG_FILE": diagnostics.APP_LOG_FILE,
            "EVENT_LOG_FILE": diagnostics.EVENT_LOG_FILE,
            "LAST_MAINTENANCE_AT": diagnostics._LAST_MAINTENANCE_AT,
        }
        now = time.time()

        try:
            with tempfile.TemporaryDirectory() as tmp:
                log_dir = Path(tmp) / "logs"
                crash_dir = log_dir / "crashes"
                diag_dir = log_dir / "diagnostics"
                crash_dir.mkdir(parents=True)
                diag_dir.mkdir()
                app_log = log_dir / "app_current.log"
                event_log = diag_dir / "events_current.jsonl"
                app_log.write_text("current\n", encoding="utf-8")
                event_log.write_text("current\n", encoding="utf-8")
                old_state = diag_dir / "state_main_99999999.json"
                old_state.write_text("{}\n", encoding="utf-8")
                os.utime(old_state, (now - 10 * 86400, now - 10 * 86400))
                live_state = diag_dir / f"state_other_{os.getpid()}.json"
                live_state.write_text("{}\n", encoding="utf-8")
                os.utime(live_state, (now - 10 * 86400, now - 10 * 86400))
                stdio_log = log_dir / "launchd_err.log"
                stdio_log.write_bytes(b"x" * (2 * 1024 * 1024))

                diagnostics.LOG_DIR = str(log_dir)
                diagnostics.CRASH_DIR = str(crash_dir)
                diagnostics.DIAGNOSTIC_DIR = str(diag_dir)
                diagnostics.APP_LOG_FILE = str(app_log)
                diagnostics.EVENT_LOG_FILE = str(event_log)
                with patch.dict(
                    os.environ,
                    {
                        "AGENTCOCKPIT_LOG_RETENTION_DAYS": "7",
                        "AGENTCOCKPIT_STDIO_LOG_MAX_MB": "1",
                    },
                ):
                    result = diagnostics.maintain_runtime_artifacts(force=True, now=now)

                self.assertFalse(old_state.exists())
                self.assertTrue(live_state.exists())
                self.assertTrue(app_log.exists())
                self.assertTrue(event_log.exists())
                self.assertLess(stdio_log.stat().st_size, 1024 * 1024)
                self.assertEqual(result["removed"], 1)
                self.assertEqual(result["trimmed"], 1)
                self.assertTrue((log_dir / ".runtime_maintenance.lock").exists())
        finally:
            diagnostics.LOG_DIR = original["LOG_DIR"]
            diagnostics.CRASH_DIR = original["CRASH_DIR"]
            diagnostics.DIAGNOSTIC_DIR = original["DIAGNOSTIC_DIR"]
            diagnostics.APP_LOG_FILE = original["APP_LOG_FILE"]
            diagnostics.EVENT_LOG_FILE = original["EVENT_LOG_FILE"]
            diagnostics._LAST_MAINTENANCE_AT = original["LAST_MAINTENANCE_AT"]

    def test_log_crash_writes_enriched_redacted_report(self):
        original = {
            "LOG_DIR": diagnostics.LOG_DIR,
            "CRASH_DIR": diagnostics.CRASH_DIR,
            "DIAGNOSTIC_DIR": diagnostics.DIAGNOSTIC_DIR,
            "APP_LOG_FILE": diagnostics.APP_LOG_FILE,
            "EVENT_LOG_FILE": diagnostics.EVENT_LOG_FILE,
        }

        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                log_dir = root / "logs"
                crash_dir = log_dir / "crashes"
                diag_dir = log_dir / "diagnostics"
                log_dir.mkdir()
                crash_dir.mkdir()
                diag_dir.mkdir()
                app_log = log_dir / "app_test.log"
                event_log = diag_dir / "events_test.jsonl"
                app_log.write_text("GET /app?token=raw-token\n", encoding="utf-8")

                diagnostics.LOG_DIR = str(log_dir)
                diagnostics.CRASH_DIR = str(crash_dir)
                diagnostics.DIAGNOSTIC_DIR = str(diag_dir)
                diagnostics.APP_LOG_FILE = str(app_log)
                diagnostics.EVENT_LOG_FILE = str(event_log)

                crash_file = diagnostics.log_crash(
                    "unit",
                    "admin_token=raw-admin",
                    "Traceback includes TELEGRAM_TOKEN=123456:AAAAAAAAAAAAAAAAAAAAAAAAA",
                )
                content = Path(crash_file).read_text(encoding="utf-8")
        finally:
            diagnostics.LOG_DIR = original["LOG_DIR"]
            diagnostics.CRASH_DIR = original["CRASH_DIR"]
            diagnostics.DIAGNOSTIC_DIR = original["DIAGNOSTIC_DIR"]
            diagnostics.APP_LOG_FILE = original["APP_LOG_FILE"]
            diagnostics.EVENT_LOG_FILE = original["EVENT_LOG_FILE"]

        self.assertIn("Runtime snapshot", content)
        self.assertIn("Thread dump", content)
        self.assertIn("Recent app log tail", content)
        self.assertNotIn("raw-admin", content)
        self.assertNotIn("raw-token", content)
        self.assertNotIn("123456:AAAAAAAA", content)


if __name__ == "__main__":
    unittest.main()

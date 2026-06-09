import os
import tempfile
import unittest
from pathlib import Path

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

    def test_collect_diagnostics_snapshot_contains_core_process_fields(self):
        snapshot = diagnostics.collect_diagnostics_snapshot("unit-test")

        self.assertEqual(snapshot["schema"], 1)
        self.assertEqual(snapshot["process"], "unit-test")
        self.assertEqual(snapshot["pid"], os.getpid())
        self.assertIn("threads", snapshot)
        self.assertIn("resource", snapshot)
        self.assertIn("disk", snapshot)

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

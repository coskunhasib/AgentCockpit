import unittest
from unittest.mock import patch

import macos_autostart_guard as guard


class MacOSAutostartGuardTests(unittest.TestCase):
    def test_non_macos_is_ready_immediately(self):
        with patch.object(guard.sys, "platform", "linux"):
            self.assertEqual(guard.readiness_reasons(), [])

    def test_macos_collects_failed_readiness_reasons(self):
        with patch.object(guard.sys, "platform", "darwin"), patch.object(
            guard, "_console_ready", return_value=(False, "console yok")
        ):
            self.assertEqual(guard.readiness_reasons(), ["console yok"])

    def test_numeric_console_owner_matches_current_uid(self):
        with patch.object(guard.os, "getuid", return_value=501), patch.object(
            guard, "_console_identity", return_value=("(501)", 501)
        ):
            self.assertEqual(guard._console_ready(), (True, ""))

    def test_wait_until_ready_stops_on_timeout(self):
        times = iter([0.0, 0.0, 1.0])
        sleeps = []
        with patch.dict(
            guard.os.environ,
            {
                "AGENTCOCKPIT_MAC_READY_INTERVAL_SEC": "1",
                "AGENTCOCKPIT_MAC_READY_TIMEOUT_SEC": "1",
            },
            clear=False,
        ), patch.object(guard, "readiness_reasons", return_value=["hazir degil"]):
            self.assertFalse(
                guard.wait_until_ready(
                    sleep=sleeps.append,
                    now=lambda: next(times),
                )
            )
        self.assertEqual(sleeps, [1.0])


if __name__ == "__main__":
    unittest.main()

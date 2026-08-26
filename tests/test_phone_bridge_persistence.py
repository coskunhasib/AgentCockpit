import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import phone_bridge_server as bridge
from phone_bridge_server import SessionLinkStore, TrustedDeviceStore


class _Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class PhoneBridgePersistenceTests(unittest.TestCase):
    def test_trusted_device_survives_store_recreation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_path = Path(tmp_dir) / "trusted_devices.json"
            first_store = TrustedDeviceStore(storage_path)
            device = first_store.create(label="Telefon", user_agent="Mobile Safari")

            second_store = TrustedDeviceStore(storage_path)
            restored = second_store.consume(device["token"])

            self.assertIsNotNone(restored)
            self.assertTrue(restored["trusted_device"])
            self.assertEqual(restored["device_label"], "Telefon")
            self.assertTrue(restored["expires_unlimited"])

    def test_trusted_devices_are_bounded_by_recent_use(self):
        clock = _Clock()
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            bridge.time, "time", clock
        ):
            store = TrustedDeviceStore(
                Path(tmp_dir) / "trusted_devices.json",
                max_entries=8,
                stale_days=90,
            )
            tokens = []
            for index in range(10):
                clock.now += 1
                tokens.append(store.create(label=f"Telefon {index}")["token"])

            self.assertEqual(store.count(), 8)
            self.assertIsNone(store.consume(tokens[0]))
            self.assertIsNone(store.consume(tokens[1]))
            self.assertIsNotNone(store.consume(tokens[-1]))

    def test_stale_trusted_devices_are_removed_on_load(self):
        clock = _Clock()
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            bridge.time, "time", clock
        ):
            path = Path(tmp_dir) / "trusted_devices.json"
            first = TrustedDeviceStore(path, stale_days=1)
            token = first.create(label="Eski Telefon")["token"]
            clock.now += 2 * 86400

            second = TrustedDeviceStore(path, stale_days=1)

            self.assertEqual(second.count(), 0)
            self.assertIsNone(second.consume(token))

    def test_trusted_device_last_seen_writes_are_throttled(self):
        clock = _Clock()
        with tempfile.TemporaryDirectory() as tmp_dir, patch.object(
            bridge.time, "time", clock
        ):
            store = TrustedDeviceStore(
                Path(tmp_dir) / "trusted_devices.json",
                persist_interval=30,
            )
            token = store.create(label="Telefon")["token"]
            with patch.object(store, "_save_locked", wraps=store._save_locked) as save:
                clock.now += 5
                self.assertIsNotNone(store.consume(token))
                save.assert_not_called()

                clock.now += 31
                self.assertIsNotNone(store.consume(token))
                save.assert_called_once()

    def test_session_links_are_bounded_and_countable(self):
        clock = _Clock()
        with patch.object(bridge.time, "time", clock):
            store = SessionLinkStore(max_entries=8)
            tokens = []
            for _ in range(10):
                clock.now += 1
                tokens.append(store.create(None)["token"])

            self.assertEqual(store.count(), 8)
            self.assertIsNone(store.consume(tokens[0]))
            self.assertIsNotNone(store.consume(tokens[-1]))

    def test_protected_pairing_session_survives_lru_pressure(self):
        clock = _Clock()
        with patch.object(bridge.time, "time", clock):
            store = SessionLinkStore(max_entries=8)
            pairing_token = store.create(
                None,
                label="startup-phone",
                protected=True,
            )["token"]
            for _ in range(12):
                clock.now += 1
                store.create(None)

            self.assertEqual(store.count(), 8)
            self.assertIsNotNone(store.consume(pairing_token))

    def test_new_protected_session_replaces_previous_protection(self):
        clock = _Clock()
        with patch.object(bridge.time, "time", clock):
            store = SessionLinkStore(max_entries=8)
            old_token = store.create(None, protected=True)["token"]
            clock.now += 1
            new_token = store.create(None, protected=True)["token"]
            for _ in range(8):
                clock.now += 1
                store.create(None)

            self.assertIsNone(store.consume(old_token))
            self.assertIsNotNone(store.consume(new_token))


if __name__ == "__main__":
    unittest.main()

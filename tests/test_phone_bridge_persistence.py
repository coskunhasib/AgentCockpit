import tempfile
import unittest
from pathlib import Path

from phone_bridge_server import TrustedDeviceStore


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


if __name__ == "__main__":
    unittest.main()

import asyncio
import tempfile
import unittest
from pathlib import Path

import core.bot_engine as legacy
import telegram_ux as ux


class PhoneNotificationTests(unittest.TestCase):
    def _link_payload(self):
        return {
            "expires_in_text": "Sinirsiz",
            "label": "telegram-repair",
            "lan_url": "http://192.168.1.10:8765/app?token=test",
            "lan_urls": ["http://192.168.1.10:8765/app?token=test"],
            "local_url": "http://127.0.0.1:8765/app?token=test",
            "public_url": "https://new.trycloudflare.com",
            "wan_url": "https://new.trycloudflare.com/app?token=test",
        }

    def test_phone_chat_and_public_url_are_persisted_for_repair_notifications(self):
        original_path = ux.PHONE_NOTIFICATION_STATE_FILE
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                ux.PHONE_NOTIFICATION_STATE_FILE = Path(tmp_dir) / "phone_state.json"

                ux._remember_phone_chat(12345)
                ux._remember_notified_public_url("https://old.trycloudflare.com")

                state = ux._load_phone_notification_state()
                self.assertEqual(state["chat_ids"], ["12345"])
                self.assertEqual(state["last_public_url"], "https://old.trycloudflare.com")
        finally:
            ux.PHONE_NOTIFICATION_STATE_FILE = original_path

    def test_notification_targets_include_saved_chats_and_allowed_users(self):
        original_path = ux.PHONE_NOTIFICATION_STATE_FILE
        original_allowed_ids = set(legacy.ALLOWED_IDS)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                ux.PHONE_NOTIFICATION_STATE_FILE = Path(tmp_dir) / "phone_state.json"
                legacy.ALLOWED_IDS.clear()
                legacy.ALLOWED_IDS.update({"222", "333"})

                ux._remember_phone_chat(111)

                self.assertEqual(
                    ux._notification_target_chat_ids(),
                    ["111", "222", "333"],
                )
        finally:
            ux.PHONE_NOTIFICATION_STATE_FILE = original_path
            legacy.ALLOWED_IDS.clear()
            legacy.ALLOWED_IDS.update(original_allowed_ids)

    def test_repair_link_marks_public_url_after_successful_send(self):
        class Bot:
            def __init__(self):
                self.messages = []

            async def send_message(self, **kwargs):
                self.messages.append(kwargs)

        original_path = ux.PHONE_NOTIFICATION_STATE_FILE
        original_create_phone_link = ux.create_phone_link
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                ux.PHONE_NOTIFICATION_STATE_FILE = Path(tmp_dir) / "phone_state.json"
                ux.create_phone_link = lambda *args, **kwargs: self._link_payload()

                bot = Bot()
                public_url = asyncio.run(
                    ux._send_phone_repair_link(
                        bot,
                        "111",
                        old_url="https://old.trycloudflare.com",
                    )
                )

                state = ux._load_phone_notification_state()
                self.assertEqual(public_url, "https://new.trycloudflare.com")
                self.assertEqual(state["last_public_url"], "https://new.trycloudflare.com")
                self.assertEqual(len(bot.messages), 1)
        finally:
            ux.PHONE_NOTIFICATION_STATE_FILE = original_path
            ux.create_phone_link = original_create_phone_link

    def test_repair_link_does_not_mark_public_url_when_send_fails(self):
        class Bot:
            async def send_message(self, **kwargs):
                raise RuntimeError("telegram down")

        original_path = ux.PHONE_NOTIFICATION_STATE_FILE
        original_create_phone_link = ux.create_phone_link
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                ux.PHONE_NOTIFICATION_STATE_FILE = Path(tmp_dir) / "phone_state.json"
                ux.create_phone_link = lambda *args, **kwargs: self._link_payload()

                with self.assertRaises(RuntimeError):
                    asyncio.run(
                        ux._send_phone_repair_link(
                            Bot(),
                            "111",
                            old_url="https://old.trycloudflare.com",
                        )
                    )

                self.assertNotIn(
                    "last_public_url",
                    ux._load_phone_notification_state(),
                )
        finally:
            ux.PHONE_NOTIFICATION_STATE_FILE = original_path
            ux.create_phone_link = original_create_phone_link


if __name__ == "__main__":
    unittest.main()

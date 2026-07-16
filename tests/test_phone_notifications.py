import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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

                with patch.dict(os.environ, {"ALLOWED_USER_ID": ""}, clear=False):
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


class PhoneCallbackAuthTests(unittest.TestCase):
    """The phone: callback branch mints remote-control links and toggles the
    public WAN tunnel; it must enforce ALLOWED_IDS before doing anything."""

    class _Query:
        def __init__(self, data, user_id, chat_id=999):
            self.data = data
            self.from_user = SimpleNamespace(id=user_id)
            self.message = SimpleNamespace(chat_id=chat_id)
            self.answered = False
            self.edits = []

        async def answer(self, *args, **kwargs):
            self.answered = True

        async def edit_message_text(self, text, **kwargs):
            self.edits.append(text)

    def _run(self, data, user_id):
        """Invoke the override handle_callback with privileged ops tracked."""
        query = self._Query(data, user_id)
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(bot=SimpleNamespace())
        calls = []

        def _track_create(*args, **kwargs):
            calls.append("create_phone_link")
            return self_link_payload()

        async def _track_wan_start(*args, **kwargs):
            calls.append("start_wan_session")
            return True

        async def _track_wan_stop(*args, **kwargs):
            calls.append("stop_wan_session")
            return True

        def self_link_payload():
            return {
                "expires_in_text": "Sinirsiz",
                "lan_urls": [],
                "local_url": "http://127.0.0.1:8765/app?token=t",
                "public_url": "https://x.trycloudflare.com",
                "wan_url": "https://x.trycloudflare.com/app?token=t",
            }

        with patch.object(ux, "create_phone_link", _track_create), patch.object(
            ux, "start_wan_session", _track_wan_start
        ), patch.object(ux, "stop_wan_session", _track_wan_stop), patch.object(
            ux, "_phone_bridge_status_text", lambda **kwargs: "status"
        ), patch.object(
            ux, "_phone_status_markup", lambda **kwargs: None
        ), patch.object(
            ux, "_phone_link_text", lambda payload: "link"
        ), patch.object(
            ux, "_phone_link_markup", lambda payload, **kwargs: None
        ):
            asyncio.run(ux.handle_callback(update, context))
        return query, calls

    def test_unauthorized_phone_callbacks_are_blocked_and_not_enrolled(self):
        original_path = ux.PHONE_NOTIFICATION_STATE_FILE
        original_allowed = set(legacy.ALLOWED_IDS)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                ux.PHONE_NOTIFICATION_STATE_FILE = Path(tmp_dir) / "phone_state.json"
                legacy.ALLOWED_IDS.clear()
                legacy.ALLOWED_IDS.update({"777"})

                for data in ("phone:status", "phone:new:0", "phone:wan:start", "phone:wan:stop"):
                    with self.subTest(data=data):
                        query, calls = self._run(data, user_id=555)
                        # The query is acknowledged but no privileged op runs...
                        self.assertTrue(query.answered)
                        self.assertEqual(calls, [])
                        self.assertEqual(query.edits, [])
                        # ...and the attacker's chat is never persisted as a target.
                        state = ux._load_phone_notification_state()
                        self.assertEqual(state.get("chat_ids", []), [])
        finally:
            ux.PHONE_NOTIFICATION_STATE_FILE = original_path
            legacy.ALLOWED_IDS.clear()
            legacy.ALLOWED_IDS.update(original_allowed)

    def test_authorized_phone_callback_proceeds_and_enrolls_chat(self):
        original_path = ux.PHONE_NOTIFICATION_STATE_FILE
        original_allowed = set(legacy.ALLOWED_IDS)
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                ux.PHONE_NOTIFICATION_STATE_FILE = Path(tmp_dir) / "phone_state.json"
                legacy.ALLOWED_IDS.clear()
                legacy.ALLOWED_IDS.update({"777"})

                query, calls = self._run("phone:wan:start", user_id=777)
                self.assertTrue(query.answered)
                self.assertIn("start_wan_session", calls)
                self.assertEqual(len(query.edits), 1)
                self.assertEqual(
                    ux._load_phone_notification_state().get("chat_ids", []), ["999"]
                )
        finally:
            ux.PHONE_NOTIFICATION_STATE_FILE = original_path
            legacy.ALLOWED_IDS.clear()
            legacy.ALLOWED_IDS.update(original_allowed)




class BridgeRestartDecisionTests(unittest.TestCase):
    def test_no_restart_below_failure_threshold(self):
        self.assertFalse(ux._bridge_restart_decision(0, None, 1000.0))
        self.assertFalse(ux._bridge_restart_decision(2, None, 1000.0))

    def test_restart_at_threshold_when_no_prior_restart(self):
        self.assertTrue(ux._bridge_restart_decision(3, None, 1000.0))

    def test_cooldown_blocks_rapid_respawns(self):
        self.assertFalse(ux._bridge_restart_decision(3, 950.0, 1000.0))
        self.assertTrue(ux._bridge_restart_decision(3, 950.0, 1071.0))


if __name__ == "__main__":
    unittest.main()

import unittest
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


if __name__ == "__main__":
    unittest.main()

import inspect
import unittest
from unittest.mock import patch

import phone_bridge_server as pbs
from phone_bridge_server import ActionDedup, PhoneBridgeHandler


class _Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class ActionDedupTests(unittest.TestCase):
    def test_abort_releases_inflight_for_retry(self):
        dedup = ActionDedup()
        cached, owner = dedup.acquire("rid-1")
        self.assertIsNone(cached)
        self.assertTrue(owner)
        self.assertIn("rid-1", dedup._inflight)

        dedup.abort("rid-1")
        self.assertNotIn("rid-1", dedup._inflight)

        # A genuine retry can take ownership again instead of stalling.
        cached2, owner2 = dedup.acquire("rid-1")
        self.assertIsNone(cached2)
        self.assertTrue(owner2)

    def test_complete_caches_response_and_releases_inflight(self):
        dedup = ActionDedup()
        dedup.acquire("rid-2")
        dedup.complete("rid-2", {"status": "ok"})
        self.assertNotIn("rid-2", dedup._inflight)

        cached, owner = dedup.acquire("rid-2")
        self.assertEqual(cached, {"status": "ok"})
        self.assertFalse(owner)

    def test_stale_inflight_self_heals_without_blocking(self):
        # Regression: if an owner ever fails to call complete()/abort() (e.g. an
        # error escaped the action handler), the reservation must not live
        # forever and stall every later retry of the same request_id for the
        # full wait_timeout. _evict_locked drops in-flight ids older than
        # inflight_ttl.
        clock = _Clock(1000.0)
        with patch.object(pbs.time, "time", clock):
            dedup = ActionDedup(wait_timeout=15.0, inflight_ttl=60.0)
            cached, owner = dedup.acquire("rid-leak")
            self.assertTrue(owner)
            self.assertIn("rid-leak", dedup._inflight)

            # Owner leaks the reservation; time passes well beyond inflight_ttl.
            clock.now += 61.0
            cached2, owner2 = dedup.acquire("rid-leak")

        # The stale entry is evicted, so the next caller owns it again with no
        # cached response and without waiting.
        self.assertIsNone(cached2)
        self.assertTrue(owner2)

    def test_empty_request_id_is_never_cached_or_reserved(self):
        dedup = ActionDedup()
        cached, owner = dedup.acquire("")
        self.assertIsNone(cached)
        self.assertFalse(owner)
        self.assertEqual(dedup._inflight, {})


class ActionDedupHandlerWiringTests(unittest.TestCase):
    def test_delay_parse_is_inside_the_abort_protected_try(self):
        # Regression: the delay parse used to run AFTER acquire() reserved the
        # request_id but BEFORE the try whose except calls abort(), so a
        # malformed delay leaked the in-flight id permanently. It must sit inside
        # that try.
        source = inspect.getsource(PhoneBridgeHandler.do_POST)
        acquire_at = source.index("action_dedup.acquire(request_id)")
        try_at = source.index("try:", acquire_at)
        delay_at = source.index('float(payload.get("delay"', acquire_at)
        abort_at = source.index("action_dedup.abort(request_id)", acquire_at)
        self.assertLess(try_at, delay_at)
        self.assertLess(delay_at, abort_at)


if __name__ == "__main__":
    unittest.main()

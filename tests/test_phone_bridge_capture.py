import unittest
from unittest.mock import patch

from PIL import Image

import phone_bridge_server as bridge


class _FakePyAutoGui:
    def __init__(self, image):
        self._image = image

    def screenshot(self):
        return self._image.copy()


class _BrokenPyAutoGui:
    def screenshot(self):
        raise OSError("could not create image from display")


class _CursorOnlyPyAutoGui:
    def position(self):
        return (10, 10)

    class Size:
        width = 1728
        height = 1117

    def size(self):
        return self.Size()


class _ZeroSizePyAutoGui:
    class Size:
        width = 0
        height = 0

    def size(self):
        return self.Size()


class PhoneBridgeCaptureTests(unittest.TestCase):
    def setUp(self):
        bridge._PYAUTOGUI = _CursorOnlyPyAutoGui()
        with bridge._CAPTURE_STATE_LOCK:
            bridge._CAPTURE_STATE.update(
                {
                    "last_error": "",
                    "last_error_at": 0.0,
                    "last_success_at": 0.0,
                    "last_width": 0,
                    "last_height": 0,
                    "failure_count": 0,
                    "backoff_until": 0.0,
                }
            )
        bridge._QUARTZ_STATE.update({"checked": True, "ok": False})

    def test_is_nearly_black_frame_detects_black(self):
        image = Image.new("RGB", (16, 16), (0, 0, 0))
        self.assertTrue(bridge._is_nearly_black_frame(image))

    def test_is_nearly_black_frame_detects_non_black(self):
        image = Image.new("RGB", (16, 16), (0, 0, 0))
        image.putpixel((5, 5), (20, 20, 20))
        self.assertFalse(bridge._is_nearly_black_frame(image))

    def test_capture_payload_raises_clear_error_when_frame_stays_black(self):
        black = Image.new("RGB", (32, 32), (0, 0, 0))
        fake = _FakePyAutoGui(black)

        with patch.object(bridge, "_require_pyautogui", return_value=fake), patch.object(
            bridge, "_capture_with_screencapture", return_value=None
        ), patch.object(bridge, "_mouse_overlay_point", return_value=(10, 10)):
            with self.assertRaises(RuntimeError) as ctx:
                bridge._capture_payload(quality=60, max_width=1280)
            self.assertIn("Screen Recording", str(ctx.exception))

    def test_capture_payload_uses_macos_fallback_when_primary_is_black(self):
        black = Image.new("RGB", (32, 32), (0, 0, 0))
        fallback = Image.new("RGB", (32, 32), (200, 40, 30))
        fake = _FakePyAutoGui(black)

        with patch.object(bridge, "_require_pyautogui", return_value=fake), patch.object(
            bridge, "_capture_with_screencapture", return_value=fallback
        ), patch.object(bridge, "_mouse_overlay_point", return_value=(10, 10)):
            payload = bridge._capture_payload(quality=60, max_width=1280)

        self.assertIn("image", payload)
        self.assertGreater(len(payload["image"]), 20)
        self.assertEqual(payload["screen_width"], 32)
        self.assertEqual(payload["screen_height"], 32)

    def test_capture_payload_uses_fallback_when_primary_capture_raises(self):
        fallback = Image.new("RGB", (40, 30), (120, 80, 60))

        with patch.object(bridge, "_require_pyautogui", return_value=_BrokenPyAutoGui()), patch.object(
            bridge, "_capture_with_screencapture", return_value=fallback
        ), patch.object(bridge, "_mouse_overlay_point", return_value=(10, 10)):
            payload = bridge._capture_payload(quality=60, max_width=1280)

        self.assertEqual(payload["screen_width"], 40)
        self.assertEqual(payload["screen_height"], 30)
        self.assertIn("image", payload)

    def test_capture_payload_raises_clear_error_when_primary_capture_and_fallback_fail(self):
        with patch.object(bridge, "_require_pyautogui", return_value=_BrokenPyAutoGui()), patch.object(
            bridge, "_capture_with_screencapture", return_value=None
        ):
            with self.assertRaises(RuntimeError) as ctx:
                bridge._capture_payload(quality=60, max_width=1280)

        self.assertIn("Screen Recording", str(ctx.exception))

    def test_capture_health_reports_zero_screen_as_unavailable(self):
        health = bridge._capture_health({"available": True, "width": 0, "height": 0})

        self.assertFalse(health["capture_available"])
        self.assertEqual(health["capture_error"], "screen metrics unavailable")

    def test_screen_metrics_treat_zero_size_as_unavailable(self):
        with patch.object(bridge, "_get_pyautogui", return_value=_ZeroSizePyAutoGui()):
            metrics = bridge._get_screen_metrics()

        self.assertEqual(metrics["width"], 0)
        self.assertEqual(metrics["height"], 0)
        self.assertFalse(metrics["available"])

    def test_capture_health_reports_last_capture_error(self):
        bridge._record_capture_error(RuntimeError("could not create image from display"))

        health = bridge._capture_health({"available": True, "width": 1728, "height": 1117})

        self.assertFalse(health["capture_available"])
        self.assertIn("could not create image", health["capture_error"])

    def test_raw_capture_serialized_releases_lock_after_failure(self):
        with patch.object(bridge, "_raw_capture", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                bridge._raw_capture_serialized()

        self.assertTrue(bridge._CAPTURE_LOCK.acquire(blocking=False))
        bridge._CAPTURE_LOCK.release()

    def test_raw_capture_serialized_defers_when_screen_metrics_unavailable(self):
        with patch.object(
            bridge,
            "_get_screen_metrics",
            return_value={"width": 0, "height": 0, "available": False},
        ), patch.object(bridge, "_raw_capture", side_effect=AssertionError("raw capture should not run")):
            with self.assertRaises(bridge.CaptureUnavailable) as ctx:
                bridge._raw_capture_serialized()

        self.assertIn("screen metrics unavailable", str(ctx.exception))
        self.assertGreaterEqual(ctx.exception.retry_after, 1)

    def test_capture_error_sets_retry_backoff_for_unavailable_screen(self):
        bridge._record_capture_error(
            bridge.CaptureUnavailable("screen metrics unavailable", retry_after=5)
        )

        self.assertGreaterEqual(bridge._capture_retry_after_seconds(), 1)

    def test_capture_success_clears_retry_backoff(self):
        bridge._record_capture_error(
            bridge.CaptureUnavailable("screen metrics unavailable", retry_after=5)
        )
        bridge._record_capture_success(1280, 720)

        self.assertEqual(bridge._capture_retry_after_seconds(), 0)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from PIL import Image

import phone_bridge_server as bridge


class _FakePyAutoGui:
    def __init__(self, image):
        self._image = image

    def screenshot(self):
        return self._image.copy()


class PhoneBridgeCaptureTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

import inspect
import unittest

from core import claude_platform_windows


class ClaudePlatformWindowsTests(unittest.TestCase):
    def test_response_filter_uses_real_unicode_chrome_tokens(self):
        source = inspect.getsource(claude_platform_windows.wait_and_read_response)

        self.assertIn("· Max", source)
        self.assertIn("↓?", source)
        self.assertNotIn("Â·", source)
        self.assertNotIn("â†", source)


if __name__ == "__main__":
    unittest.main()

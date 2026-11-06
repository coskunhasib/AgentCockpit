import unittest
from pathlib import Path


class PhoneClientKeyboardTests(unittest.TestCase):
    def test_keyboard_panel_exposes_recovery_shortcuts(self):
        html = Path("phone_client/index.html").read_text(encoding="utf-8")

        self.assertIn('data-key="ctrl+shift+esc"', html)
        self.assertIn('data-key="taskmgr-close"', html)
        self.assertIn('data-key="alt+f4"', html)
        self.assertIn('data-key="winleft+d"', html)
        self.assertIn('data-key="mac_control+left"', html)
        self.assertIn('data-key="mac_control+right"', html)
        self.assertIn('id="btn-input-target"', html)
        self.assertIn("input_target: inputTarget", html)
        self.assertIn("inputTarget: 'ac_phone_input_target_v2'", html)
        self.assertIn("includes(savedInputTarget) ? savedInputTarget : 'auto'", html)

    def test_keyboard_defaults_to_visible_text_with_password_toggle(self):
        html = Path("phone_client/index.html").read_text(encoding="utf-8")

        self.assertIn('id="type-input" type="text"', html)
        self.assertIn('id="btn-sensitive"', html)
        self.assertIn("sensitive: sensitiveTyping", html)
        self.assertIn("rememberTextTarget(coords)", html)
        self.assertIn("const focus = recentTextTarget()", html)
        self.assertIn("sensitive: sensitiveTyping, focus, delay", html)
        self.assertIn("typeInput.type = sensitiveTyping ? 'password' : 'text'", html)

    def test_hid_text_is_chunked_without_refocusing_or_automatic_retries(self):
        html = Path("phone_client/index.html").read_text(encoding="utf-8")
        self.assertIn("Array.from(payload.text || '')", html)
        self.assertIn('offset += 64', html)
        self.assertIn('focus: offset === 0 ? payload.focus : null', html)
        self.assertIn('request_id: `${payload.request_id}:hid:${offset}`', html)
        self.assertIn('{ timeoutMs: 75000, retries: 0 }', html)
        self.assertIn('input_target: target', html)
        self.assertIn('target = result.input_target', html)


if __name__ == "__main__":
    unittest.main()

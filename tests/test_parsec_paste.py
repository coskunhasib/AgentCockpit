import unittest
from unittest.mock import Mock, patch

from core.parsec_paste import _new_entry, _normalized, paste_via_menu


class ParsecPasteTests(unittest.TestCase):
    def test_existing_text_and_ambiguous_entries_are_not_clicked(self):
        self.assertIsNone(_new_entry([(100, 100)], [(102, 100)], (90, 90)))
        self.assertIsNone(_new_entry([], [(100, 100), (150, 100)], (90, 90)))
        self.assertEqual(_new_entry([], [(100, 100)], (90, 90)), (100, 100))
        self.assertEqual(_normalized('Yapıştır'), 'yapistir')

    def test_missing_menu_reports_failure_and_restores_sensitive_clipboard(self):
        gui, clipboard = Mock(), Mock()
        gui.position.return_value = (100, 100)
        gui.size.return_value = (1000, 800)
        clipboard.paste.side_effect = ['previous', 'secret']
        with patch('core.system_tools.SystemOps.is_parsec_frontmost', return_value=True), patch(
            'core.parsec_paste._pointer_on_parsec', return_value=True
        ), patch(
            'core.parsec_paste._capture_entries', return_value=[]
        ), patch('core.parsec_paste.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'bulunamadi'):
                paste_via_menu('secret', gui, clipboard, restore_clipboard=True)
        self.assertEqual(gui.click.call_count, 2)  # Open and dismiss; never select.
        clipboard.copy.assert_called_with('previous')

    def test_clipboard_changed_by_user_is_preserved(self):
        gui, clipboard = Mock(), Mock()
        gui.position.return_value = (100, 100)
        gui.size.return_value = (1000, 800)
        clipboard.paste.side_effect = ['previous', 'new user clipboard']
        with patch('core.system_tools.SystemOps.is_parsec_frontmost', return_value=True), patch(
            'core.parsec_paste._pointer_on_parsec', return_value=True
        ), patch(
            'core.parsec_paste._capture_entries', side_effect=[[], [(150, 150)], []]
        ), patch('core.parsec_paste.time.sleep'):
            self.assertTrue(paste_via_menu('secret', gui, clipboard, restore_clipboard=True))
        clipboard.copy.assert_called_once_with('secret')

    def test_non_parsec_focus_does_not_touch_clipboard_or_mouse(self):
        gui, clipboard = Mock(), Mock()
        with patch('core.system_tools.SystemOps.is_parsec_frontmost', return_value=False):
            with self.assertRaises(RuntimeError):
                paste_via_menu('text', gui, clipboard)
        gui.click.assert_not_called()
        clipboard.copy.assert_not_called()

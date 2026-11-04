import json
import unittest
from unittest.mock import MagicMock, patch

from core import parsec_hid


class ParsecHIDTests(unittest.TestCase):
    def test_text_uses_stdin_mcp_not_command_arguments(self):
        session = MagicMock()
        with patch.object(parsec_hid, '_frontmost', return_value=True), patch.object(
            parsec_hid, '_layout_name', return_value='us'
        ), patch.object(parsec_hid, '_cursor', return_value={'x': 1, 'y': 2}), patch.object(
            parsec_hid, '_Session'
        ) as factory:
            factory.return_value.__enter__.return_value = session
            self.assertTrue(parsec_hid.type_text('secret'))
        tool = session.send.call_args_list[-1].args[0]
        self.assertEqual(tool['method'], 'tools/call')
        self.assertEqual(tool['params']['name'], 'play')
        self.assertNotIn('secret', json.dumps(tool))
        lines = [json.loads(line) for line in tool['params']['arguments']['script'].splitlines()]
        self.assertEqual(lines[1]['keys'], [22])
        self.assertEqual(lines[-1]['keys'], [])

    def test_no_process_started_when_parsec_is_not_frontmost(self):
        with patch.object(parsec_hid, '_frontmost', return_value=False), patch.object(
            parsec_hid, '_Session'
        ) as factory:
            with self.assertRaises(parsec_hid.HIDError):
                parsec_hid._call('play', {}, 1)
        factory.assert_not_called()

    def test_key_aliases(self):
        with patch.object(parsec_hid, '_play', return_value=True) as call:
            parsec_hid.press_keys(['command', 'shift', 'esc'])
        call.assert_called_once_with([['leftCommand', 'leftShift', 41]], hold_ms=150)

    def test_modifier_is_sent_before_key_and_released_after_key(self):
        with patch.object(parsec_hid, '_cursor', return_value={'x': 1, 'y': 2}), patch.object(
            parsec_hid, '_call', return_value=True
        ) as call:
            parsec_hid._play([['leftShift', 4]])
        lines = [json.loads(line) for line in call.call_args.args[1]['script'].splitlines()]
        self.assertEqual(lines[1:], [
            {'t_ms': 0, 'keys': ['leftShift']},
            {'t_ms': 60, 'keys': ['leftShift', 4]},
            {'t_ms': 180, 'keys': ['leftShift']},
            {'t_ms': 220, 'keys': []},
        ])

    def test_turkish_letters_never_use_mac_option_alternatives(self):
        letters = parsec_hid._text_keys('i\u00e7\u011f\u00f6\u015f\u00fc\u0131', 'tr-q')
        self.assertEqual(letters, [[52], [55], [47], [54], [51], [48], [12]])
        self.assertFalse(any('leftOption' in keys or 'rightOption' in keys for keys in letters))

    def test_uppercase_turkish_uses_only_shift(self):
        letters = parsec_hid._text_keys('\u0130\u00c7\u011e\u00d6\u015e\u00dcI', 'tr-q')
        self.assertEqual(letters, [['leftShift', key] for key in [52, 55, 47, 54, 51, 48, 12]])

    def test_unsupported_text_is_refused_before_any_input(self):
        with patch.object(parsec_hid, '_layout_name', return_value='us'), patch.object(
            parsec_hid, '_play'
        ) as play:
            with self.assertRaises(parsec_hid.HIDError):
                parsec_hid.type_text('test\U0001f600')
        play.assert_not_called()

    def test_altgr_not_left_alt_for_windows_symbols(self):
        self.assertEqual(parsec_hid._text_keys('@{}', 'tr-q'),
                         [['rightOption', 20], ['rightOption', 36], ['rightOption', 39]])

    def test_focus_loss_interrupts_wait(self):
        session = parsec_hid._Session()
        session.buffer = b''
        with patch.object(parsec_hid, '_frontmost', return_value=False):
            with self.assertRaises(parsec_hid.HIDError):
                session.answer(2, 1)

    def test_tool_error_does_not_disclose_text(self):
        session = parsec_hid._Session()
        session.buffer = json.dumps({
            'id': 2, 'result': {'isError': True, 'content': [{'text': 'private'}]}
        }).encode() + b'\n'
        with patch.object(parsec_hid, '_frontmost', return_value=True):
            with self.assertRaises(parsec_hid.HIDError) as error:
                session.answer(2, 1)
        self.assertNotIn('private', str(error.exception))

    def test_child_environment_disables_telemetry(self):
        process = MagicMock()
        with patch.object(parsec_hid, '_binary', return_value='/example/vhid'), patch.object(
            parsec_hid.subprocess, 'Popen', return_value=process
        ) as popen, patch.object(parsec_hid.selectors, 'DefaultSelector'), patch.dict(
            parsec_hid.os.environ, {'OTEL_EXPORTER_OTLP_ENDPOINT': 'https://example.com'}
        ):
            with parsec_hid._Session():
                pass
        self.assertEqual(popen.call_args.args[0], ['/example/vhid', 'mcp'])
        self.assertFalse(any(key.startswith('OTEL_') for key in popen.call_args.kwargs['env']))
        process.terminate.assert_called_once()


if __name__ == '__main__':
    unittest.main()

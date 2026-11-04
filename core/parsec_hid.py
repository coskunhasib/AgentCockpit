"""Send Parsec keys through vhid's signed DriverKit client, never the clipboard."""

import ctypes
import json
import os
import selectors
import shutil
import subprocess
import threading
import time
import unicodedata

_LOCK = threading.Lock()
_LAYOUT_LOCK = threading.Lock()


class HIDError(RuntimeError):
    pass


def _binary():
    path = shutil.which('vhid')
    if not path and os.access('/usr/local/bin/vhid', os.X_OK):
        path = '/usr/local/bin/vhid'
    if not path:
        raise HIDError('vhid kurulu degil; sanal HID surucusunu kurun.')
    return path


def _frontmost():
    from core.system_tools import SystemOps
    return SystemOps.is_parsec_frontmost()


class _Session:
    def __enter__(self):
        # Text travels only over stdin. Do not inherit optional telemetry exporters.
        env = {key: value for key, value in os.environ.items() if not key.startswith('OTEL_')}
        self.process = subprocess.Popen(
            [_binary(), 'mcp'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env,
        )
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b''
        return self

    def send(self, message):
        self.process.stdin.write((json.dumps(message) + '\n').encode('utf-8'))
        self.process.stdin.flush()

    def answer(self, request_id, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _frontmost():
                raise HIDError('Parsec odagi kayboldu; aktarim durduruldu, tekrar gonderilmedi.')
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                reply = json.loads(line)
                if reply.get('id') == request_id:
                    if 'error' in reply or reply.get('result', {}).get('isError'):
                        # Upstream failures can contain input characters. Never log them.
                        raise HIDError('HID islemi reddedildi; surucu, odak ve klavye duzenini kontrol edin.')
                    if not isinstance(reply.get('result'), dict):
                        raise HIDError('Gecersiz HID yaniti.')
                    return reply['result']
            if self.selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                data = os.read(self.process.stdout.fileno(), 65536)
                if not data:
                    raise HIDError('HID istemcisi yanit vermeden kapandi.')
                self.buffer += data
                if len(self.buffer) > 1048576:
                    raise HIDError('HID yaniti boyut sinirini asti.')
        raise HIDError('HID zaman asimi; metnin bir kismi yazilmis olabilir, otomatik tekrarlanmadi.')

    def __exit__(self, *args):
        # SIGTERM asks vhid to cancel its operation and release held keys.
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        self.selector.close()
        self.process.stdin.close()
        self.process.stdout.close()


def _call(name, arguments, timeout):
    if not _LOCK.acquire(timeout=1):
        raise HIDError('Baska bir HID islemi devam ediyor.')
    try:
        if not _frontmost():
            raise HIDError('Parsec onde degil; hicbir tus gonderilmedi.')
        with _Session() as session:
            session.send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2024-11-05', 'capabilities': {},
                'clientInfo': {'name': 'AgentCockpit', 'version': '1.0'},
            }})
            session.answer(1, 10)
            session.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            if name in ('type', 'press'):
                arguments = {**arguments, 'into': 'Parsec'}
            session.send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                          'params': {'name': name, 'arguments': arguments}})
            session.answer(2, timeout)
        return True
    finally:
        _LOCK.release()


def _layout_name():
    requested = os.environ.get('AGENTCOCKPIT_PARSEC_LAYOUT', '').strip().lower()
    if requested:
        if requested not in ('tr-q', 'us'):
            raise HIDError('AGENTCOCKPIT_PARSEC_LAYOUT tr-q veya us olmali.')
        return requested
    with _LAYOUT_LOCK:
        return _system_layout_name()


def _system_layout_name():
    carbon = ctypes.CDLL('/System/Library/Frameworks/Carbon.framework/Carbon')
    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    carbon.TISCopyCurrentKeyboardLayoutInputSource.restype = ctypes.c_void_p
    carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
    cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_uint32]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    source = carbon.TISCopyCurrentKeyboardLayoutInputSource()
    if not source:
        raise HIDError('Klavye duzeni okunamadi; AGENTCOCKPIT_PARSEC_LAYOUT ayarlayin.')
    try:
        identifier = carbon.TISGetInputSourceProperty(
            source, ctypes.c_void_p.in_dll(carbon, 'kTISPropertyInputSourceID'))
        buffer = ctypes.create_string_buffer(512)
        if not identifier or not cf.CFStringGetCString(identifier, buffer, len(buffer), 0x08000100):
            raise HIDError('Klavye duzeni okunamadi.')
        name = buffer.value.decode('utf-8')
    finally:
        cf.CFRelease(source)
    if name.endswith('.Turkish-QWERTY-PC'):
        return 'tr-q'
    if name in ('com.apple.keylayout.US', 'com.apple.keylayout.ABC'):
        return 'us'
    raise HIDError('Hedef Windows duzenini AGENTCOCKPIT_PARSEC_LAYOUT ile secin: tr-q veya us.')


def _text_keys(text, layout):
    # Windows physical positions, not macOS Option-character alternatives.
    # Turkish Q: https://learn.microsoft.com/en-us/globalization/keyboards/kbdtuq
    pairs = {chr(97 + i): (4 + i, chr(65 + i)) for i in range(26)}
    pairs.update({char: (30 + i, shifted) for i, (char, shifted) in enumerate(zip(
        '1234567890', "!'^+%&/()=" if layout == 'tr-q' else '!@#$%^&*()'))})
    punctuation = (
        {42: ('\b', None), 44: (' ', None), 45: ('*', '?'), 46: ('-', '_'),
         47: ('\u011f', '\u011e'), 48: ('\u00fc', '\u00dc'), 49: (',', ';'),
         51: ('\u015f', '\u015e'), 52: ('i', '\u0130'), 53: ('"', '\u00e9'),
         54: ('\u00f6', '\u00d6'), 55: ('\u00e7', '\u00c7'), 56: ('.', ':'), 100: ('<', '>')}
        if layout == 'tr-q' else
        {44: (' ', None), 45: ('-', '_'), 46: ('=', '+'), 47: ('[', '{'),
         48: (']', '}'), 49: ('\\', '|'), 51: (';', ':'), 52: ("'", '"'),
         53: ('`', '~'), 54: (',', '<'), 55: ('.', '>'), 56: ('/', '?')}
    )
    if layout == 'tr-q':
        pairs.pop('i')
        pairs['\u0131'] = (12, 'I')
    mapping = {}
    for char, (usage, upper) in pairs.items():
        mapping[char] = [usage]
        mapping[upper] = ['leftShift', usage]
    for usage, (plain, shifted) in punctuation.items():
        mapping[plain] = [usage]
        if shifted:
            mapping[shifted] = ['leftShift', usage]
    if layout == 'tr-q':
        for char, usage in {'@': 20, '\u20ac': 8, '\u20ba': 23, '#': 32, '$': 33,
                            '{': 36, '[': 37, ']': 38, '}': 39, '\\': 45, '|': 46}.items():
            mapping[char] = ['rightOption', usage]
        mapping['/'] = ['leftShift', 36]
        # Circumflex is a dead key in Windows Turkish Q.
        mapping['^'] = ['leftShift', 32]
    mapping.update({'\n': [40], '\t': [43]})
    text = unicodedata.normalize('NFC', str(text)).replace('\r\n', '\n').replace('\r', '\n')
    if any(char not in mapping or char == '\b' for char in text):
        raise HIDError('Metinde hedef klavye duzeniyle yazilamayan karakter var; hicbir tus gonderilmedi.')
    strokes = []
    for char in text:
        strokes.append(mapping[char])
        if layout == 'tr-q' and char == '^':
            strokes.append([44])
    return strokes


def _cursor():
    import Quartz
    point = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return {'x': float(point.x), 'y': float(point.y)}


def _play(strokes, *, hold_ms=120):
    lines = [{'to': _cursor()}]
    elapsed = 0
    for keys in strokes:
        modifiers = [key for key in keys if isinstance(key, str)]
        # Parsec must see the modifier before the character's HID report.
        # One combined report can arrive as a plain letter on the Windows host.
        if modifiers:
            lines.append({'t_ms': elapsed, 'keys': modifiers})
            elapsed += 60
        lines.append({'t_ms': elapsed, 'keys': keys})
        elapsed += hold_ms
        lines.append({'t_ms': elapsed, 'keys': modifiers})
        if modifiers:
            elapsed += 40
            lines.append({'t_ms': elapsed, 'keys': []})
        elapsed += 80
    script = '\n'.join(json.dumps(line) for line in lines)
    return _call('play', {'script': script}, max(30, elapsed / 1000 + 15))


def type_text(text):
    if not text:
        return True
    return _play(_text_keys(text, _layout_name()))


def press_keys(keys):
    aliases = {
        'ctrl': 'leftControl', 'control': 'leftControl', 'ctrlleft': 'leftControl',
        'ctrlright': 'rightControl', 'command': 'leftCommand', 'winleft': 'leftCommand',
        'winright': 'rightCommand', 'option': 'leftOption', 'alt': 'leftOption',
        'altleft': 'leftOption', 'altright': 'rightOption', 'shift': 'leftShift',
        'shiftleft': 'leftShift', 'shiftright': 'rightShift', 'esc': 'escape',
        'enter': 'return', 'backspace': 'delete', 'delete': 'forwardDelete',
        'pageup': 'pageUp', 'pagedown': 'pageDown',
    }
    named = {
        'return': 40, 'escape': 41, 'delete': 42, 'tab': 43, 'space': 44,
        'capslock': 57, 'printscreen': 70, 'scrolllock': 71, 'pause': 72,
        'insert': 73, 'home': 74, 'pageUp': 75, 'forwardDelete': 76,
        'end': 77, 'pageDown': 78, 'right': 79, 'left': 80, 'down': 81, 'up': 82,
    }
    named.update({f'f{i + 1}': 58 + i for i in range(12)})
    named.update({char: 4 + i for i, char in enumerate('abcdefghijklmnopqrstuvwxyz')})
    named.update({char: 30 + i for i, char in enumerate('1234567890')})
    modifiers = {'leftControl', 'rightControl', 'leftShift', 'rightShift',
                 'leftOption', 'rightOption', 'leftCommand', 'rightCommand'}
    chord = []
    for key in keys:
        key = aliases.get(key, key)
        if key in modifiers:
            chord.append(key)
        elif key in named:
            chord.append(named[key])
        else:
            raise HIDError('Desteklenmeyen HID tusu; hicbir tus gonderilmedi.')
    if not chord:
        return True
    return _play([chord], hold_ms=150)

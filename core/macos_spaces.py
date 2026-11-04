"""Verified local Space transitions; SkyLight symbols are private and may change."""

import ctypes
import plistlib
import threading
import time

_LOCK = threading.Lock()


class SpaceController:
    def __init__(self):
        self.sky = ctypes.CDLL(
            '/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight'
        )
        self.cf = ctypes.CDLL(
            '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation'
        )
        signatures = (
            (self.sky, 'SLSMainConnectionID', [], ctypes.c_int),
            (self.sky, 'SLSGetActiveSpace', [ctypes.c_int], ctypes.c_uint64),
            (self.sky, 'SLSCopyManagedDisplaySpaces', [ctypes.c_int], ctypes.c_void_p),
            (self.sky, 'SLSManagedDisplaySetCurrentSpace',
             [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint64], None),
            (self.sky, 'SLSShowSpaces', [ctypes.c_int, ctypes.c_void_p], None),
            (self.sky, 'SLSHideSpaces', [ctypes.c_int, ctypes.c_void_p], None),
            (self.cf, 'CFRelease', [ctypes.c_void_p], None),
            (self.cf, 'CFPropertyListCreateData',
             [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_ulong,
              ctypes.c_void_p], ctypes.c_void_p),
            (self.cf, 'CFDataGetLength', [ctypes.c_void_p], ctypes.c_long),
            (self.cf, 'CFDataGetBytePtr', [ctypes.c_void_p], ctypes.c_void_p),
            (self.cf, 'CFStringCreateWithCString',
             [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32], ctypes.c_void_p),
            (self.cf, 'CFNumberCreate',
             [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p], ctypes.c_void_p),
            (self.cf, 'CFArrayCreate',
             [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p],
             ctypes.c_void_p),
        )
        for library, name, args, result in signatures:
            function = getattr(library, name)
            function.argtypes = args
            function.restype = result
        self.connection = self.sky.SLSMainConnectionID()

    def displays(self):
        value = self.sky.SLSCopyManagedDisplaySpaces(self.connection)
        if not value:
            raise RuntimeError('WindowServer Space listesi okunamadi.')
        data = None
        try:
            data = self.cf.CFPropertyListCreateData(None, value, 200, 0, None)
            if not data:
                raise RuntimeError('WindowServer Space listesi donusturulemedi.')
            return plistlib.loads(ctypes.string_at(
                self.cf.CFDataGetBytePtr(data), self.cf.CFDataGetLength(data)
            ))
        finally:
            if data:
                self.cf.CFRelease(data)
            self.cf.CFRelease(value)

    def _visibility(self, space_id, show):
        number = ctypes.c_int64(space_id)
        value = self.cf.CFNumberCreate(None, 4, ctypes.byref(number))
        if not value:
            raise RuntimeError('Space numarasi olusturulamadi.')
        array = None
        try:
            values = (ctypes.c_void_p * 1)(value)
            array = self.cf.CFArrayCreate(None, values, 1, None)
            if not array:
                raise RuntimeError('Space listesi olusturulamadi.')
            function = self.sky.SLSShowSpaces if show else self.sky.SLSHideSpaces
            function(self.connection, array)
        finally:
            if array:
                self.cf.CFRelease(array)
            self.cf.CFRelease(value)

    def _select(self, display, previous, target):
        name = self.cf.CFStringCreateWithCString(None, display.encode(), 0x08000100)
        if not name:
            raise RuntimeError('Ekran kimligi olusturulamadi.')
        try:
            self._visibility(target, True)
            self._visibility(previous, False)
            self.sky.SLSManagedDisplaySetCurrentSpace(self.connection, name, target)
        finally:
            self.cf.CFRelease(name)

    def switch(self, direction):
        with _LOCK:
            displays = self.displays()
            active = self.sky.SLSGetActiveSpace(self.connection)
            display = next((d for d in displays if
                            d.get('Current Space', {}).get('ManagedSpaceID') == active), None)
            if display is None:
                raise RuntimeError('Aktif ekran Space bilgisi bulunamadi.')
            previous = display['Current Space']['ManagedSpaceID']
            spaces = [s['ManagedSpaceID'] for s in display['Spaces']]
            index = spaces.index(previous) + (-1 if direction < 0 else 1)
            if not 0 <= index < len(spaces):
                return previous, previous
            target = spaces[index]
            name = display['Display Identifier']
            try:
                self._select(name, previous, target)
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    current = next((d for d in self.displays()
                                    if d['Display Identifier'] == name), {})
                    if (current.get('Current Space', {}).get('ManagedSpaceID') == target
                            and self.sky.SLSGetActiveSpace(self.connection) == target):
                        return previous, target
                    time.sleep(0.05)
                raise RuntimeError('macOS hedef Space gecisini dogrulamadi.')
            except Exception:
                self._select(name, target, previous)
                raise

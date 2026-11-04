import unittest
from unittest.mock import MagicMock, patch

from core import system_tools
from core.system_tools import SystemOps


class SystemToolsHotkeyTests(unittest.TestCase):
    def test_parsec_focus_is_read_live_not_from_nsworkspace_cache(self):
        appkit = MagicMock()
        appkit.NSRunningApplication.runningApplicationWithProcessIdentifier_.return_value.bundleIdentifier.return_value = 'tv.parsec.www'
        with patch.object(system_tools.sys, 'platform', 'darwin'), patch.object(
            system_tools, '_get_appkit', return_value=appkit
        ), patch('core.macos_focus.focused_pid', side_effect=[123, 0]):
            self.assertTrue(SystemOps.is_parsec_frontmost())
            self.assertFalse(SystemOps.is_parsec_frontmost())
        appkit.NSWorkspace.sharedWorkspace.assert_not_called()

    def test_mac_space_shortcut_uses_verified_local_controller(self):
        with patch.object(system_tools.sys, 'platform', 'darwin'), patch(
            'core.macos_spaces.SpaceController'
        ) as controller:
            controller.return_value.switch.return_value = (32, 1)
            self.assertTrue(SystemOps.execute_hotkey(['mac_control', 'left']))
        controller.return_value.switch.assert_called_once_with(-1.0)

    def test_unverified_mac_space_transition_reports_failure(self):
        with patch('core.macos_spaces.SpaceController') as controller:
            controller.return_value.switch.side_effect = RuntimeError('unverified')
            self.assertFalse(SystemOps._switch_macos_space(1))

    def test_mac_maps_windows_style_shortcuts_to_macos_intent(self):
        with patch.object(system_tools.sys, "platform", "darwin"):
            self.assertEqual(SystemOps.normalize_hotkey(["ctrl", "c"]), ["command", "c"])
            self.assertEqual(SystemOps.normalize_hotkey(["alt", "tab"]), ["command", "tab"])
            self.assertEqual(SystemOps.normalize_hotkey(["alt", "shift", "tab"]), ["command", "shift", "tab"])
            self.assertEqual(SystemOps.normalize_hotkey(["winleft", "d"]), ["command", "f3"])
            self.assertEqual(SystemOps.normalize_hotkey(["mac_control", "left"]), ["ctrl", "left"])
            self.assertEqual(SystemOps.normalize_hotkey(["mac_control", "right"]), ["ctrl", "right"])
            self.assertEqual(SystemOps.normalize_hotkey(["ctrlleft", "left"]), ["ctrl", "left"])
            self.assertEqual(SystemOps.normalize_hotkey(["ctrlright", "right"]), ["ctrl", "right"])
            self.assertEqual(
                SystemOps.normalize_hotkey(["ctrl", "shift", "esc"]),
                ["command", "option", "esc"],
            )

    def test_desktop_keeps_windows_style_shortcuts_usable(self):
        with patch.object(system_tools.sys, "platform", "win32"):
            self.assertEqual(SystemOps.normalize_hotkey(["win", "d"]), ["winleft", "d"])
            self.assertEqual(SystemOps.normalize_hotkey(["command", "v"]), ["ctrl", "v"])
            self.assertEqual(SystemOps.normalize_hotkey(["option", "tab"]), ["alt", "tab"])
            self.assertEqual(SystemOps.normalize_hotkey(["mac_control", "left"]), ["ctrl", "left"])

    def test_parsec_frontmost_preserves_windows_hotkey_intent(self):
        class FakePyAutoGui:
            def __init__(self):
                self.hotkeys = []

            def hotkey(self, *keys, **kwargs):
                self.hotkeys.append((keys, kwargs))

        fake_pyautogui = FakePyAutoGui()
        with patch.object(system_tools.sys, "platform", "darwin"), patch.object(
            SystemOps, "is_parsec_frontmost", return_value=True
        ), patch.object(
            system_tools, "_parsec_key_swap_enabled", return_value=True
        ), patch.object(
            system_tools, "_get_pyautogui", return_value=fake_pyautogui
        ), patch('core.parsec_hid.press_keys', return_value=True) as hid:
            self.assertTrue(SystemOps.execute_hotkey(["ctrl", "shift", "esc"]))
            self.assertTrue(SystemOps.execute_hotkey(["alt", "tab"]))
            self.assertTrue(SystemOps.execute_hotkey(["winleft", "d"]))

        self.assertEqual([call.args[0] for call in hid.call_args_list],
                         [["command", "shift", "esc"], ["option", "tab"], ["ctrl", "d"]])
        self.assertEqual(fake_pyautogui.hotkeys, [])

    def test_parsec_native_mapping_honors_disabled_command_ctrl_swap(self):
        with patch.object(system_tools.sys, "platform", "darwin"), patch.object(
            system_tools, "_parsec_key_swap_enabled", return_value=False
        ):
            self.assertEqual(
                SystemOps.normalize_hotkey(
                    ["ctrl", "alt", "winleft"], parsec_passthrough=True
                ),
                ["ctrl", "option", "command"],
            )

    def test_hid_mapping_cannot_turn_remote_shortcut_into_macos_logout(self):
        with patch.object(system_tools.sys, 'platform', 'darwin'), patch.object(
            system_tools, '_parsec_key_swap_enabled', return_value=True
        ), patch('core.parsec_hid.press_keys') as hid:
            self.assertFalse(SystemOps.execute_hotkey(['ctrl', 'shift', 'q'], parsec_passthrough=True))
        hid.assert_not_called()

    def test_system_lock_hotkeys_are_blocked_before_pyautogui(self):
        class FakePyAutoGui:
            def hotkey(self, *keys, **kwargs):
                raise AssertionError("blocked hotkey should not reach pyautogui")

        with patch.object(system_tools.sys, "platform", "darwin"), patch.object(
            system_tools,
            "_get_pyautogui",
            return_value=FakePyAutoGui(),
        ):
            self.assertFalse(SystemOps.execute_hotkey(["win", "l"]))
            self.assertFalse(SystemOps.execute_hotkey(["winleft", "l"]))
            self.assertFalse(SystemOps.execute_hotkey(["mac_control", "command", "q"]))
            self.assertFalse(SystemOps.execute_hotkey(["shift", "command", "q"]))

    def test_windows_lock_hotkey_is_blocked_before_pyautogui(self):
        class FakePyAutoGui:
            def hotkey(self, *keys, **kwargs):
                raise AssertionError("blocked hotkey should not reach pyautogui")

        with patch.object(system_tools.sys, "platform", "win32"), patch.object(
            system_tools,
            "_get_pyautogui",
            return_value=FakePyAutoGui(),
        ):
            self.assertFalse(SystemOps.execute_hotkey(["win", "l"]))

    def test_mac_dangerous_single_keys_are_blocked_before_pyautogui(self):
        class FakePyAutoGui:
            def press(self, key):
                raise AssertionError("blocked key should not reach pyautogui")

        with patch.object(system_tools.sys, "platform", "darwin"), patch.object(
            system_tools,
            "_get_pyautogui",
            return_value=FakePyAutoGui(),
        ):
            self.assertFalse(SystemOps.press_key("sleep"))
            self.assertFalse(SystemOps.press_key("power"))
            self.assertFalse(SystemOps.press_key("lock"))

    def test_task_manager_close_command_uses_windows_taskkill(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        with patch.object(system_tools.sys, "platform", "win32"), patch(
            "core.system_tools.subprocess.run", return_value=completed
        ) as run_mock:
            self.assertTrue(SystemOps.close_task_manager())
            self.assertTrue(SystemOps.press_key("taskmgr-close"))
            self.assertTrue(SystemOps.execute_hotkey(["taskmgr-close"]))

        run_mock.assert_called_with(
            ["taskkill", "/IM", "Taskmgr.exe", "/F"],
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_paste_text_uses_system_events_hotkey_on_macos(self):
        class FakePyAutoGui:
            def __init__(self):
                self.hotkeys = []

            def hotkey(self, *keys, **kwargs):
                self.hotkeys.append((keys, kwargs))

        class FakePyperclip:
            def __init__(self):
                self.copied = []

            def copy(self, text):
                self.copied.append(text)

        fake_pyautogui = FakePyAutoGui()
        fake_pyperclip = FakePyperclip()
        with patch.object(system_tools.sys, "platform", "darwin"), patch.object(
            SystemOps,
            "desktop_input_permissions",
            return_value={"post_event_access": True},
        ), patch.object(
            system_tools,
            "_get_pyautogui",
            return_value=fake_pyautogui,
        ), patch.object(system_tools, "_get_pyperclip", return_value=fake_pyperclip), patch.object(
            system_tools,
            "_paste_with_system_events",
            return_value=True,
        ) as system_events, patch.object(
            system_tools.time,
            "sleep",
            return_value=None,
        ):
            self.assertTrue(SystemOps.paste_text("Kaldığın yerden devam et"))

        self.assertEqual(fake_pyperclip.copied, ["Kaldığın yerden devam et"])
        system_events.assert_called_once_with()
        self.assertEqual(fake_pyautogui.hotkeys, [])

    def test_sensitive_paste_text_restores_previous_clipboard(self):
        class FakePyAutoGui:
            def __init__(self):
                self.hotkeys = []

            def hotkey(self, *keys, **kwargs):
                self.hotkeys.append((keys, kwargs))

        class FakePyperclip:
            def __init__(self):
                self.value = "onceki"
                self.copied = []

            def paste(self):
                return self.value

            def copy(self, text):
                self.value = text
                self.copied.append(text)

        fake_pyautogui = FakePyAutoGui()
        fake_pyperclip = FakePyperclip()
        with patch.object(system_tools.sys, "platform", "darwin"), patch.object(
            SystemOps,
            "desktop_input_permissions",
            return_value={"post_event_access": True},
        ), patch.object(
            system_tools,
            "_get_pyautogui",
            return_value=fake_pyautogui,
        ), patch.object(system_tools, "_get_pyperclip", return_value=fake_pyperclip), patch.object(
            system_tools,
            "_paste_with_system_events",
            return_value=True,
        ) as system_events, patch.object(
            system_tools.time,
            "sleep",
            return_value=None,
        ):
            self.assertTrue(SystemOps.paste_text("sifre", restore_clipboard=True))

        self.assertEqual(fake_pyperclip.copied, ["sifre", "onceki"])
        system_events.assert_called_once_with()
        self.assertEqual(fake_pyautogui.hotkeys, [])

    def test_paste_text_falls_back_to_pyautogui_when_system_events_fails(self):
        class FakePyAutoGui:
            def __init__(self):
                self.hotkeys = []

            def hotkey(self, *keys, **kwargs):
                self.hotkeys.append((keys, kwargs))

        class FakePyperclip:
            def __init__(self):
                self.copied = []

            def copy(self, text):
                self.copied.append(text)

        fake_pyautogui = FakePyAutoGui()
        fake_pyperclip = FakePyperclip()
        with patch.object(system_tools.sys, "platform", "darwin"), patch.object(
            SystemOps,
            "desktop_input_permissions",
            return_value={"post_event_access": True},
        ), patch.object(
            system_tools,
            "_get_pyautogui",
            return_value=fake_pyautogui,
        ), patch.object(system_tools, "_get_pyperclip", return_value=fake_pyperclip), patch.object(
            system_tools,
            "_paste_with_system_events",
            return_value=False,
        ), patch.object(
            system_tools.time,
            "sleep",
            return_value=None,
        ):
            self.assertTrue(SystemOps.paste_text("metin"))

        self.assertEqual(fake_pyperclip.copied, ["metin"])
        self.assertEqual(fake_pyautogui.hotkeys, [(("command", "v"), {"interval": 0.08})])

    def test_parsec_text_uses_hid_for_ascii_and_unicode(self):
        with patch.object(system_tools.sys, 'platform', 'darwin'), patch.object(
            system_tools, '_get_pyautogui', return_value=object()
        ), patch.object(system_tools, '_get_pyperclip', return_value=object()), patch(
            'core.parsec_hid.type_text', return_value=True
        ) as hid:
            for text in ['test123', 'Türkçe']:
                self.assertTrue(SystemOps.type_text_for_parsec(text, restore_clipboard=True))
                hid.assert_called_with(text)

    def test_parsec_hid_failure_never_retries_clipboard(self):
        with patch.object(system_tools.sys, 'platform', 'darwin'), patch(
            'core.parsec_hid.type_text', side_effect=RuntimeError('interrupted')
        ), patch.object(SystemOps, 'paste_text') as paste:
            self.assertFalse(SystemOps.type_text_for_parsec('test'))
        paste.assert_not_called()

    def test_parsec_single_key_uses_hid(self):
        with patch.object(system_tools.sys, 'platform', 'darwin'), patch(
            'core.parsec_hid.press_keys', return_value=True
        ) as hid:
            self.assertTrue(SystemOps.press_key('enter', parsec_passthrough=True))
        hid.assert_called_once_with(['enter'])

    def test_system_events_paste_runs_osascript_with_timeout(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        with patch.object(system_tools.sys, "platform", "darwin"), patch.object(
            system_tools.subprocess,
            "run",
            return_value=completed,
        ) as run_mock:
            self.assertTrue(system_tools._paste_with_system_events(timeout=3))

        run_mock.assert_called_once()
        args, kwargs = run_mock.call_args
        self.assertEqual(args[0][0], "osascript")
        self.assertIn("System Events", args[0][2])
        self.assertEqual(kwargs["timeout"], 3)
        self.assertTrue(kwargs["capture_output"])

    def test_system_events_paste_fails_on_timeout(self):
        with patch.object(system_tools.sys, "platform", "darwin"), patch.object(
            system_tools.subprocess,
            "run",
            side_effect=system_tools.subprocess.TimeoutExpired("osascript", 2),
        ):
            self.assertFalse(system_tools._paste_with_system_events(timeout=2))

    def test_paste_text_fails_before_hotkey_without_post_event_access(self):
        class FakePyAutoGui:
            def hotkey(self, *keys):
                raise AssertionError("hotkey should not be called")

        with patch.object(system_tools.sys, "platform", "darwin"), patch.object(
            SystemOps,
            "desktop_input_permissions",
            return_value={"post_event_access": False},
        ), patch.object(system_tools, "_get_pyautogui", return_value=FakePyAutoGui()):
            self.assertFalse(SystemOps.paste_text("metin"))

    def test_desktop_input_permissions_reads_quartz_preflight_status(self):
        class FakeQuartz:
            def CGPreflightPostEventAccess(self):
                return True

            def CGPreflightListenEventAccess(self):
                return False

            def CGPreflightScreenCaptureAccess(self):
                return True

        fake_quartz = FakeQuartz()
        try:
            with patch.object(system_tools.importlib, "import_module", return_value=fake_quartz):
                system_tools._QUARTZ = None
                self.assertEqual(
                    SystemOps.desktop_input_permissions(),
                    {
                        "quartz_available": True,
                        "post_event_access": True,
                        "listen_event_access": False,
                        "screen_capture_access": True,
                    },
                )
        finally:
            system_tools._QUARTZ = None

    def test_mac_unicode_typing_posts_quartz_events(self):
        class FakeQuartz:
            kCGHIDEventTap = "tap"

            def __init__(self):
                self.posts = []

            def CGEventCreateKeyboardEvent(self, source, keycode, down):
                return {"source": source, "keycode": keycode, "down": down}

            def CGEventKeyboardSetUnicodeString(self, event, length, text):
                event["length"] = length
                event["text"] = text

            def CGEventPost(self, tap, event):
                self.posts.append((tap, event))

        fake_quartz = FakeQuartz()
        try:
            with patch.object(system_tools.sys, "platform", "darwin"), patch.object(
                system_tools.importlib,
                "import_module",
                return_value=fake_quartz,
            ), patch.object(system_tools, "_get_pyautogui", return_value=None), patch.object(
                system_tools.time,
                "sleep",
                return_value=None,
            ):
                system_tools._QUARTZ = None
                self.assertTrue(SystemOps.type_text_unicode("şİ", interval=0.01))
        finally:
            system_tools._QUARTZ = None

        self.assertEqual(
            [(event["down"], event.get("text")) for _, event in fake_quartz.posts],
            [(True, "ş"), (False, None), (True, "İ"), (False, None)],
        )

    def test_mac_unicode_typing_uses_pyautogui_for_ascii_chunks(self):
        class FakePyAutoGui:
            def __init__(self):
                self.writes = []
                self.presses = []

            def write(self, text, interval=0.0):
                self.writes.append((text, interval))

            def press(self, key):
                self.presses.append(key)

        class FakeQuartz:
            kCGHIDEventTap = "tap"

            def __init__(self):
                self.posts = []

            def CGEventCreateKeyboardEvent(self, source, keycode, down):
                return {"source": source, "keycode": keycode, "down": down}

            def CGEventKeyboardSetUnicodeString(self, event, length, text):
                event["length"] = length
                event["text"] = text

            def CGEventPost(self, tap, event):
                self.posts.append((tap, event))

        fake_pyautogui = FakePyAutoGui()
        fake_quartz = FakeQuartz()
        try:
            with patch.object(system_tools.sys, "platform", "darwin"), patch.object(
                system_tools.importlib,
                "import_module",
                return_value=fake_quartz,
            ), patch.object(system_tools, "_get_pyautogui", return_value=fake_pyautogui), patch.object(
                system_tools.time,
                "sleep",
                return_value=None,
            ):
                system_tools._QUARTZ = None
                self.assertTrue(SystemOps.type_text_unicode("Kalğı", interval=0.03))
        finally:
            system_tools._QUARTZ = None

        self.assertEqual(fake_pyautogui.writes, [("Kal", 0.03)])
        self.assertEqual(
            [(event["down"], event.get("text")) for _, event in fake_quartz.posts],
            [(True, "ğ"), (False, None), (True, "ı"), (False, None)],
        )


if __name__ == "__main__":
    unittest.main()

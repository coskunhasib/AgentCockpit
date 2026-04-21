import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import codex_bridge


def _write_rollout(path, session_id, cwd, messages):
    rows = [
        {
            "timestamp": "2026-04-16T09:00:00.000Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": cwd,
            },
        }
    ]
    current_minute = 1
    for role, text in messages:
        rows.append(
            {
                "timestamp": f"2026-04-16T09:{current_minute:02d}:00.000Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": role,
                    "content": [
                        {
                            "type": "output_text" if role == "assistant" else "input_text",
                            "text": text,
                        }
                    ],
                },
            }
        )
        current_minute += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


class CodexBridgeTests(unittest.TestCase):
    def test_extract_session_record_uses_first_real_user_message_as_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rollout = Path(temp_dir) / "rollout-2026-04-16T09-00-00-session-1.jsonl"
            _write_rollout(
                rollout,
                "session-1",
                r"C:\Users\Hasib Coşkun\Documents\Playground",
                [
                    ("user", "<environment_context>\n  <cwd>demo</cwd>\n</environment_context>"),
                    ("user", "ilk gerçek istek burada başlıyor"),
                    ("assistant", "cevap"),
                ],
            )

            record = codex_bridge._extract_session_record(rollout)

        self.assertEqual(record["id"], "session-1")
        self.assertEqual(record["cwd"], r"C:\Users\Hasib Coşkun\Documents\Playground")
        self.assertEqual(record["title"], "ilk gerçek istek burada başlıyor")
        self.assertEqual(record["display_title"], "ilk gerçek istek burada başlıyor")

    def test_extract_session_record_prefers_session_index_thread_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rollout = Path(temp_dir) / "rollout-2026-04-16T09-00-00-session-1.jsonl"
            _write_rollout(
                rollout,
                "session-1",
                r"C:\Users\Hasib Coşkun\Documents\Playground",
                [
                    ("user", "uzun ilk mesaj"),
                    ("assistant", "cevap"),
                ],
            )

            record = codex_bridge._extract_session_record(
                rollout,
                session_index={"session-1": {"thread_name": "Kisa Baslik"}},
            )

        self.assertEqual(record["display_title"], "Kisa Baslik")

    def test_list_rollout_sessions_prefers_matching_cwd(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_rollout(
                root / "2026" / "04" / "16" / "rollout-a-session-a.jsonl",
                "session-a",
                r"C:\Users\Hasib Coşkun\Documents\Playground",
                [("user", "playground oturumu")],
            )
            _write_rollout(
                root / "2026" / "04" / "16" / "rollout-b-session-b.jsonl",
                "session-b",
                r"\\wsl.localhost\Ubuntu-22.04\Nexus_Project",
                [("user", "nexus oturumu")],
            )

            with patch.object(codex_bridge, "CODEX_SESSIONS_DIR", root), patch.object(
                codex_bridge, "CODEX_SESSION_INDEX", root / "session_index.jsonl"
            ):
                sessions = codex_bridge._list_rollout_sessions(
                    r"C:\Users\Hasib Coşkun\Documents\Playground"
                )

        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0]["id"], "session-a")
        self.assertEqual(sessions[1]["id"], "session-b")

    def test_read_rollout_messages_filters_environment_payloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rollout = Path(temp_dir) / "rollout-2026-04-16T09-00-00-session-2.jsonl"
            _write_rollout(
                rollout,
                "session-2",
                r"C:\Users\Hasib Coşkun\Documents\Playground",
                [
                    ("user", "<environment_context>\n  <cwd>demo</cwd>\n</environment_context>"),
                    ("user", "kodex merhaba"),
                    ("assistant", "ilk cevap"),
                ],
            )

            messages = codex_bridge._read_rollout_messages(rollout)

        self.assertEqual(
            messages,
            [
                {"role": "SEN", "text": "kodex merhaba", "timestamp": "2026-04-16T09:02:00.000Z", "phase": ""},
                {"role": "CODEX", "text": "ilk cevap", "timestamp": "2026-04-16T09:03:00.000Z", "phase": ""},
            ],
        )

    def test_transport_mode_supports_macos_window_detection(self):
        with patch.object(codex_bridge.sys, "platform", "darwin"), patch.object(
            codex_bridge, "find_codex_window", return_value="Codex"
        ):
            self.assertEqual(codex_bridge.get_transport_mode(), "desktop")

    def test_focus_codex_window_uses_macos_applescript(self):
        with patch.object(codex_bridge.sys, "platform", "darwin"), patch.object(
            codex_bridge, "_run_macos_applescript", return_value="true"
        ) as run_script, patch.object(codex_bridge.time, "sleep"):
            self.assertTrue(codex_bridge.focus_codex_window("Codex"))

        run_script.assert_called_once()
        self.assertIn('tell application "Codex" to activate', run_script.call_args[0][0])

    def test_session_text_matching_accepts_running_and_truncated_titles(self):
        self.assertTrue(
            codex_bridge._session_text_matches(
                "Running proje dizininde rapor dosyasi", "proje dizininde rapor dosyasi"
            )
        )
        self.assertTrue(
            codex_bridge._session_text_matches(
                "uzun codex basligi", "uzun codex basligi devam eden title"
            )
        )
        self.assertFalse(codex_bridge._session_text_matches("farkli", "hedef"))

    def test_macos_session_click_uses_visible_sidebar_item(self):
        visible_item = {
            "role": "button",
            "text": "Running hedef session",
            "left": 24,
            "right": 220,
            "top": 320,
            "bottom": 350,
        }
        with patch.object(
            codex_bridge, "_collect_codex_macos_items", return_value=[visible_item]
        ), patch.object(
            codex_bridge, "_click_codex_macos_item", return_value=True
        ) as click_item:
            self.assertTrue(codex_bridge._click_codex_macos_session("hedef session"))

        click_item.assert_called_once_with(visible_item)


if __name__ == "__main__":
    unittest.main()

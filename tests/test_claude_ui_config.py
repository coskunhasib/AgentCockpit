import json
import tempfile
import unittest
from pathlib import Path

from core import claude_ui_config


class ClaudeUiConfigTests(unittest.TestCase):
    def test_bundled_config_loads(self):
        config, metadata = claude_ui_config.load_claude_ui_config()
        self.assertIn("window_title", config)
        self.assertIn("chat", config)
        self.assertEqual(Path(metadata["default_path"]).name, "claude_ui_config.json")

    def test_override_is_merged_and_invalid_values_warn(self):
        default_config, _ = claude_ui_config.load_claude_ui_config()
        with tempfile.TemporaryDirectory() as temp_dir:
            override_path = Path(temp_dir) / "override.json"
            override_path.write_text(
                json.dumps(
                    {
                        "navigation": {"menu_button": "Alt Menu"},
                        "chat": {"role_split_left_threshold": "bad"},
                        "extra_key": True,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            config, metadata = claude_ui_config.load_claude_ui_config(
                override_path=str(override_path)
            )

        self.assertEqual(config["navigation"]["menu_button"], "Alt Menu")
        self.assertEqual(
            config["chat"]["role_split_left_threshold"],
            default_config["chat"]["role_split_left_threshold"],
        )
        self.assertIn("override.extra_key tanimsiz anahtar, yok sayildi", metadata["warnings"])
        self.assertEqual(metadata["active_path"], str(override_path))

    def test_missing_override_keeps_default_active_path(self):
        config, metadata = claude_ui_config.load_claude_ui_config(
            override_path=str(Path(tempfile.gettempdir()) / "missing_config.json")
        )
        self.assertIn("window_title", config)
        self.assertEqual(metadata["active_path"], metadata["default_path"])
        self.assertTrue(metadata["warnings"])


if __name__ == "__main__":
    unittest.main()

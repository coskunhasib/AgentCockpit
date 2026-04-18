import json
import os
import platform
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import bot_engine, claude_bridge, platform_utils  # noqa: E402
from core.claude_capabilities import get_effective_capabilities  # noqa: E402
from core.claude_ui_config import get_claude_ui_config_metadata  # noqa: E402


def _safe_call(name, fn):
    try:
        return {"ok": True, "value": fn()}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def build_report():
    session_meta_dir = claude_bridge.SESSIONS_META_DIR
    project_logs_dir = claude_bridge.PROJECTS_DIR
    transport = claude_bridge.get_transport_mode()
    session_preview = []

    sessions_result = _safe_call("list_sessions", lambda: claude_bridge.list_sessions(3))
    if sessions_result["ok"]:
        for item in sessions_result["value"]:
            session_preview.append(
                {
                    "id": item.get("id", "")[:12],
                    "title": item.get("title", "")[:60],
                    "cwd": item.get("cwd", ""),
                }
            )

    config_metadata = get_claude_ui_config_metadata()
    return {
        "platform": platform_utils.PLATFORM,
        "python": sys.executable,
        "python_version": platform.python_version(),
        "project_root": str(PROJECT_ROOT),
        "claude_exe": platform_utils.get_claude_exe(),
        "claude_exe_exists": os.path.exists(platform_utils.get_claude_exe()),
        "desktop_window_detected": bool(platform_utils.find_claude_window()),
        "transport_mode": transport,
        "session_meta_dir": session_meta_dir,
        "session_meta_dir_exists": os.path.isdir(session_meta_dir),
        "project_logs_dir": project_logs_dir,
        "project_logs_dir_exists": os.path.isdir(project_logs_dir),
        "session_count_check": sessions_result,
        "session_preview": session_preview,
        "profile_summary": claude_bridge.get_profile_summary(),
        "capabilities": get_effective_capabilities(platform_utils.PLATFORM, transport),
        "config_path": config_metadata["active_path"],
        "config_default_path": config_metadata["default_path"],
        "config_override_path": config_metadata["override_path"],
        "config_warnings": list(config_metadata["warnings"]),
        "env_force_transport": os.environ.get("CLAUDE_TRANSPORT", ""),
        "bot_engine_imported": bool(bot_engine),
    }


def main():
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))

    transport = report["transport_mode"]
    if transport == "none":
        print(
            "\n[WARN] Claude Desktop veya Claude CLI bulunamadi. "
            "Prompt gonderimi calismayacaktir."
        )
    elif transport == "cli":
        print(
            "\n[INFO] Claude CLI fallback aktif. "
            "Linux icin beklenen yol genelde budur."
        )
    else:
        print(
            "\n[INFO] Claude Desktop UI transport aktif. "
            "Canli sekme/model/effort/permission testleri yapilabilir."
        )


if __name__ == "__main__":
    main()

import json
import os
import platform
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import codex_bridge  # noqa: E402


def build_report():
    sessions = codex_bridge.list_sessions(3)
    return {
        "platform": sys.platform,
        "python": sys.executable,
        "python_version": platform.python_version(),
        "project_root": str(PROJECT_ROOT),
        "codex_home": str(codex_bridge.CODEX_HOME),
        "codex_home_exists": os.path.isdir(codex_bridge.CODEX_HOME),
        "transport_mode": codex_bridge.get_transport_mode(),
        "window_detected": bool(codex_bridge.find_codex_window()),
        "session_count": len(sessions),
        "session_preview": [
            {
                "id": item.get("id", "")[:12],
                "title": item.get("title", "")[:60],
                "cwd": item.get("cwd", ""),
            }
            for item in sessions
        ],
        "profile_summary": codex_bridge.get_profile_summary(),
    }


def main():
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if report["transport_mode"] == "desktop":
        print("\n[INFO] Codex Desktop UI gorundu. Session acma, history okuma ve prompt gonderim yolu kullanilabilir.")
    else:
        print("\n[WARN] Codex Desktop UI gorunmedi. Bu entegrasyon su an masaustu penceresine bagimli.")


if __name__ == "__main__":
    main()

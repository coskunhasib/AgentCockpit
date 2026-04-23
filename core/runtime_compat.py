import importlib
import os
import platform
import shutil
import sys

from phone_public_tunnel import cloudflared_download_url


def _platform_key(platform_name=None):
    value = (platform_name or sys.platform or "linux").strip().lower()
    if value.startswith("win"):
        return "win32"
    if value.startswith("darwin") or value.startswith("mac"):
        return "darwin"
    return "linux"


def desktop_automation_help_text(platform_name=None):
    key = _platform_key(platform_name)
    if key == "darwin":
        return (
            "Masaustu otomasyonu icin Screen Recording ve Accessibility izinlerini verin."
        )
    if key == "win32":
        return (
            "Masaustu otomasyonu icin aktif bir desktop oturumu acik olmali ve guvenlik politikasi "
            "pyautogui olaylarini engellememeli."
        )
    return (
        "Masaustu otomasyonu icin grafik oturumu (DISPLAY veya WAYLAND_DISPLAY) ve pyautogui destegi gerekli."
    )


def _linux_gui_session(env):
    return bool((env.get("DISPLAY") or "").strip() or (env.get("WAYLAND_DISPLAY") or "").strip())


def _browser_available(platform_key, env, browser_tools):
    if platform_key == "win32":
        return True
    if platform_key == "darwin":
        return "open" in browser_tools
    if (env.get("BROWSER") or "").strip():
        return True
    return any(tool in browser_tools for tool in ("xdg-open", "gio", "gnome-open", "kde-open"))


def detect_runtime_compatibility(
    *,
    platform_name=None,
    machine_name=None,
    env=None,
    browser_tools=None,
    import_module=None,
):
    env_map = os.environ if env is None else env
    importer = importlib.import_module if import_module is None else import_module
    platform_key = _platform_key(platform_name)
    machine = (machine_name or platform.machine() or "").strip()
    machine_key = machine.lower()

    browser_candidates = browser_tools
    if browser_candidates is None:
        browser_candidates = {
            name
            for name in ("open", "xdg-open", "gio", "gnome-open", "kde-open")
            if shutil.which(name)
        }
    else:
        browser_candidates = set(browser_candidates)

    gui_session = True
    gui_reason = ""
    if platform_key == "linux":
        gui_session = _linux_gui_session(env_map)
        if not gui_session:
            gui_reason = "Grafik oturumu bulunamadi (DISPLAY/WAYLAND_DISPLAY yok)."

    browser_available = _browser_available(platform_key, env_map, browser_candidates)
    browser_reason = ""
    if not browser_available:
        browser_reason = "Tarayici acma araci bulunamadi; linkler sadece konsola yazdirilacak."

    desktop_automation_available = gui_session
    desktop_automation_reason = gui_reason
    if desktop_automation_available:
        try:
            importer("pyautogui")
        except Exception as exc:
            desktop_automation_available = False
            desktop_automation_reason = f"pyautogui hazir degil: {exc}"

    tunnel_download = cloudflared_download_url(
        "Windows" if platform_key == "win32" else "Darwin" if platform_key == "darwin" else "Linux",
        machine,
    )
    public_tunnel_supported = bool(tunnel_download)
    public_tunnel_reason = ""
    if not public_tunnel_supported:
        public_tunnel_reason = (
            f"Quick tunnel otomatik indirme bu platformda desteklenmiyor: {platform_key} {machine_key or 'unknown'}"
        )

    warnings = []
    if not desktop_automation_available:
        reason = desktop_automation_reason or desktop_automation_help_text(platform_key)
        warnings.append(f"Masaustu otomasyonu kisitli modda calisacak. {reason}")
    if not browser_available:
        warnings.append(browser_reason)
    if not public_tunnel_supported:
        warnings.append(public_tunnel_reason)

    return {
        "platform": platform_key,
        "machine": machine,
        "gui_session": gui_session,
        "gui_reason": gui_reason,
        "browser_available": browser_available,
        "browser_reason": browser_reason,
        "desktop_automation_available": desktop_automation_available,
        "desktop_automation_reason": desktop_automation_reason,
        "public_tunnel_supported": public_tunnel_supported,
        "public_tunnel_reason": public_tunnel_reason,
        "public_tunnel_download_url": tunnel_download or "",
        "warnings": warnings,
        "applied_defaults": [],
    }


def apply_runtime_defaults(report, *, env=None):
    env_map = os.environ if env is None else env
    applied = list(report.get("applied_defaults", []))

    if not report.get("public_tunnel_supported") and not (env_map.get("PHONE_PUBLIC_TUNNEL") or "").strip():
        env_map["PHONE_PUBLIC_TUNNEL"] = "off"
        applied.append("PHONE_PUBLIC_TUNNEL=off")

    report["applied_defaults"] = applied
    return report


def format_runtime_compatibility(report):
    lines = [
        f"[COMPAT] Platform: {report['platform']} ({report['machine'] or 'unknown'})",
        f"[COMPAT] Browser auto-open: {'hazir' if report['browser_available'] else 'kapali'}",
        (
            "[COMPAT] Desktop automation: hazir"
            if report["desktop_automation_available"]
            else f"[COMPAT] Desktop automation: kisitli ({report['desktop_automation_reason'] or desktop_automation_help_text(report['platform'])})"
        ),
        (
            "[COMPAT] Public tunnel: destekli"
            if report["public_tunnel_supported"]
            else f"[COMPAT] Public tunnel: kisitli ({report['public_tunnel_reason']})"
        ),
    ]
    for item in report.get("applied_defaults", []):
        lines.append(f"[COMPAT] Varsayilan uygulandi: {item}")
    return lines

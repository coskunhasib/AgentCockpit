import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from core.app_config import get_str

PLACEHOLDER_TOKENS = {
    "",
    "BURAYA_BOTFATHER_TOKEN_YAZ",
    "YOUR_TELEGRAM_BOT_TOKEN",
    "TELEGRAM_TOKEN",
}
SETUP_HOST = get_str("TELEGRAM_SETUP_HOST")


def _read_env_values(env_path):
    values = {}
    try:
        lines = Path(env_path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _is_placeholder_token(token):
    value = (token or "").strip()
    return value in PLACEHOLDER_TOKENS or value.startswith("BURAYA_")


def needs_telegram_setup(env_path):
    env_token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    if env_token and not _is_placeholder_token(env_token):
        return False

    file_token = _read_env_values(env_path).get("TELEGRAM_TOKEN", "")
    return _is_placeholder_token(file_token)


def _upsert_env_values(env_path, updates):
    path = Path(env_path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []

    pending = dict(updates)
    output = []
    seen = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            output.append(line)
            continue

        key = stripped.split("=", 1)[0].strip()
        if key in pending:
            if key not in seen:
                output.append(f"{key}={pending[key]}")
                seen.add(key)
            continue
        output.append(line)

    for key, value in pending.items():
        if key not in seen:
            output.append(f"{key}={value}")

    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def validate_telegram_token(token, *, timeout=10, urlopen=urllib.request.urlopen):
    value = (token or "").strip()
    if ":" not in value or len(value) < 20:
        return False, "Token formati BotFather token'ina benzemiyor.", {}

    url = f"https://api.telegram.org/bot{value}/getMe"
    request = urllib.request.Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.NOT_FOUND}:
            return False, "Telegram bu token'i kabul etmedi.", {}
        return False, f"Telegram dogrulama hatasi: HTTP {exc.code}", {}
    except Exception as exc:
        return False, f"Telegram'a erisilemedi: {exc}", {}

    result = payload.get("result") if isinstance(payload, dict) else None
    if not payload.get("ok") or not isinstance(result, dict):
        return False, "Telegram token dogrulamasi basarisiz oldu.", {}
    return True, "", result


def _setup_page(error=""):
    error_html = (
        f'<div class="error">{html.escape(error)}</div>'
        if error
        else ""
    )
    return f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AgentCockpit Ilk Kurulum</title>
  <style>
    :root {{
      --bg: #f5efe4;
      --ink: #241b13;
      --muted: #756452;
      --card: #fffaf2;
      --line: #eadcc9;
      --accent: #1c6f65;
      --accent-dark: #104a44;
      --danger: #9d2f24;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 20% 15%, #f7d8a8 0, transparent 30%),
        radial-gradient(circle at 80% 20%, #b5e2d8 0, transparent 26%),
        linear-gradient(145deg, #f5efe4, #eee1cf);
      padding: 24px;
    }}
    main {{
      width: min(680px, 100%);
      padding: 34px;
      border: 1px solid var(--line);
      border-radius: 28px;
      background: color-mix(in srgb, var(--card) 92%, white);
      box-shadow: 0 28px 80px rgb(72 50 28 / 18%);
    }}
    .eyebrow {{
      margin: 0 0 10px;
      color: var(--accent-dark);
      font: 700 13px/1.2 Verdana, sans-serif;
      letter-spacing: .14em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(34px, 6vw, 58px);
      line-height: .95;
      letter-spacing: -.04em;
    }}
    p {{
      color: var(--muted);
      font-size: 18px;
      line-height: 1.55;
    }}
    label {{
      display: block;
      margin: 28px 0 10px;
      font: 700 14px/1.2 Verdana, sans-serif;
      color: var(--ink);
    }}
    input {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      font: 16px/1.2 Consolas, monospace;
      background: #fffdf8;
      color: var(--ink);
      outline: none;
    }}
    input:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 4px rgb(28 111 101 / 14%);
    }}
    button {{
      margin-top: 18px;
      width: 100%;
      border: 0;
      border-radius: 16px;
      padding: 16px 18px;
      background: var(--accent);
      color: white;
      font: 800 16px/1 Verdana, sans-serif;
      cursor: pointer;
    }}
    button:hover {{ background: var(--accent-dark); }}
    .hint {{
      margin-top: 16px;
      padding: 14px 16px;
      border-radius: 16px;
      background: #f0e3d0;
      color: var(--muted);
      font-size: 15px;
    }}
    .error {{
      margin-top: 22px;
      padding: 14px 16px;
      border-radius: 16px;
      background: #ffe8e4;
      color: var(--danger);
      font: 700 14px/1.4 Verdana, sans-serif;
    }}
    code {{ font-family: Consolas, monospace; }}
  </style>
</head>
<body>
  <main>
    <p class="eyebrow">AgentCockpit</p>
    <h1>Telegram botunu baglayalim</h1>
    <p>
      BotFather'dan aldigin Telegram bot token'ini buraya yapistir.
      Bu sayfa sadece bu bilgisayarda acilir ve token telefona/uzak PWA'ya gonderilmez.
    </p>
    {error_html}
    <form method="post" action="/save">
      <label for="telegram_token">Telegram Bot Token</label>
      <input id="telegram_token" name="telegram_token" type="password"
             autocomplete="off" spellcheck="false"
             placeholder="1234567890:AA..." required autofocus>
      <button type="submit">Dogrula ve Kaydet</button>
    </form>
    <p class="hint">
      Token yoksa Telegram'da <code>@BotFather</code> ile <code>/newbot</code>
      komutunu kullan. Kayit sonrasi bot kullanici adi otomatik bulunur.
    </p>
  </main>
</body>
</html>"""


def _success_page(username):
    username_line = f"@{html.escape(username)}" if username else "Bot"
    return f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AgentCockpit Hazir</title>
  <style>
    body {{
      min-height: 100vh;
      margin: 0;
      display: grid;
      place-items: center;
      font-family: Georgia, "Times New Roman", serif;
      color: #1e261f;
      background: linear-gradient(135deg, #d8f1df, #f7eedf);
      padding: 24px;
    }}
    main {{
      width: min(620px, 100%);
      padding: 34px;
      border-radius: 28px;
      background: #fffdf7;
      box-shadow: 0 24px 70px rgb(24 78 50 / 18%);
    }}
    h1 {{ margin: 0; font-size: clamp(34px, 7vw, 58px); line-height: .95; }}
    p {{ color: #536454; font-size: 18px; line-height: 1.55; }}
    strong {{ color: #14614f; }}
  </style>
</head>
<body>
  <main>
    <h1>Kurulum tamam.</h1>
    <p><strong>{username_line}</strong> dogrulandi ve ayarlar kaydedildi.</p>
    <p>Bu sekmeyi kapatabilirsin. AgentCockpit simdi normal sekilde aciliyor.</p>
  </main>
</body>
</html>"""


class _TelegramSetupServer(HTTPServer):
    def __init__(self, server_address, handler_class, env_path):
        super().__init__(server_address, handler_class)
        self.env_path = Path(env_path)
        self.done = False
        self.ok = False


class _TelegramSetupHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send_html(self, body, status=HTTPStatus.OK):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path not in {"/", "/setup"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_html(_setup_page())

    def do_POST(self):
        if self.path != "/save":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(min(length, 8192)).decode("utf-8", errors="replace")
        values = urllib.parse.parse_qs(raw)
        token = (values.get("telegram_token") or [""])[0].strip()

        ok, error, bot_info = validate_telegram_token(token)
        if not ok:
            self._send_html(_setup_page(error), status=HTTPStatus.BAD_REQUEST)
            return

        username = (bot_info.get("username") or "").strip()
        updates = {
            "TELEGRAM_TOKEN": token,
            "ALLOWED_USER_ID": _read_env_values(self.server.env_path).get("ALLOWED_USER_ID", ""),
        }
        if username:
            updates["TELEGRAM_BOT_USERNAME"] = username

        _upsert_env_values(self.server.env_path, updates)
        os.environ["TELEGRAM_TOKEN"] = token
        if username:
            os.environ["TELEGRAM_BOT_USERNAME"] = username

        self.server.ok = True
        self.server.done = True
        self._send_html(_success_page(username))


def ensure_telegram_setup(project_root, *, open_browser=True):
    env_path = Path(project_root) / ".env"
    if not needs_telegram_setup(env_path):
        return True

    try:
        server = _TelegramSetupServer((SETUP_HOST, 0), _TelegramSetupHandler, env_path)
    except OSError as exc:
        print("[SETUP] Telegram token bulunamadi.")
        print(
            "[SETUP] Yerel kurulum sayfasi acilamadi. "
            f".env dosyasina TELEGRAM_TOKEN ekleyip tekrar calistirin. ({exc})"
        )
        return False

    setup_url = f"http://{SETUP_HOST}:{server.server_port}/setup"

    print("[SETUP] Telegram token bulunamadi. Ilk kurulum sayfasi aciliyor.")
    print(f"[SETUP] Sayfa acilmazsa bu adresi kullan: {setup_url}")
    if open_browser:
        try:
            webbrowser.open(setup_url, new=2)
        except Exception as exc:
            print(f"[SETUP] Tarayici acilamadi: {exc}")

    try:
        while not server.done:
            server.handle_request()
    finally:
        server.server_close()

    if server.ok:
        print("[SETUP] Telegram token kaydedildi.")
    return server.ok

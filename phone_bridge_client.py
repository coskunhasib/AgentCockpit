import json
import socket
import urllib.error
import urllib.request

from core.app_config import get_int, get_str
from phone_runtime_config import get_shared_admin_token

DEFAULT_PORT = get_int("PHONE_PORT")
DEFAULT_BASE_URL = get_str(
    "PHONE_BRIDGE_URL",
    f"http://{get_str('AGENTCOCKPIT_LOCAL_HOST')}:{DEFAULT_PORT}",
)


class PhoneBridgeClientError(RuntimeError):
    pass


def _normalize_base_url(base_url=None):
    value = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not value.startswith("http://") and not value.startswith("https://"):
        value = "http://" + value
    return value


def get_bridge_base_url(base_url=None):
    return _normalize_base_url(base_url)


def _request_json(path, *, method="GET", body=None, headers=None, base_url=None, timeout=None):
    url = _normalize_base_url(base_url) + path
    payload = None
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    if body is not None:
        payload = json.dumps(body).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers=request_headers,
        method=method,
    )
    timeout = get_int("PHONE_BRIDGE_TIMEOUT_SEC") if timeout is None else timeout
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (TimeoutError, socket.timeout) as exc:
        raise PhoneBridgeClientError("Bridge istegi zaman asimina ugradi.") from exc
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8"))
            message = data.get("message") or data.get("status") or str(exc)
        except Exception:
            message = str(exc)
        raise PhoneBridgeClientError(message) from exc
    except urllib.error.URLError as exc:
        raise PhoneBridgeClientError(str(exc.reason)) from exc
    except Exception as exc:
        raise PhoneBridgeClientError(f"Bridge istegi basarisiz: {exc}") from exc


def get_bridge_health(*, base_url=None):
    return _request_json("/health", base_url=base_url)


def create_phone_link(minutes=0, *, label="telegram", admin_token=None, base_url=None):
    token = (admin_token or get_shared_admin_token()).strip()
    if not token:
        raise PhoneBridgeClientError(
            "PHONE_ADMIN_TOKEN tanimli degil. Phone bridge ile backend'in ayni admin token'i bilmesi gerekiyor."
        )

    if minutes in (None, "", 0, "0", False):
        safe_minutes = 0
    else:
        safe_minutes = max(5, min(24 * 60, int(minutes)))
    safe_label = (label or "telegram").strip()[:80] or "telegram"
    data = _request_json(
        "/api/session-links",
        method="POST",
        body={"minutes": safe_minutes, "label": safe_label},
        headers={"X-AgentCockpit-Admin": token},
        base_url=base_url,
    )
    if data.get("status") != "ok" or "session" not in data:
        raise PhoneBridgeClientError("Phone link olusturulamadi.")
    return data["session"]

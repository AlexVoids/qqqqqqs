"""SMS TEST v3.1 — phone/URL checks and request transport for owned APIs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs

import phonenumbers
from phonenumbers import geocoder
import requests

MAX_REQUESTS = 5
DELAY_SECONDS = 3
MAX_PROFILES = 20
MAX_HISTORY = 50


@dataclass(frozen=True)
class PhoneResult:
    number: str
    country: str
    country_code: str


def validate_phone(value: str) -> PhoneResult:
    """Accept E.164 with or without leading + (country code is required)."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Введите номер с кодом страны, например 79991234567")
    if value.startswith("+"):
        normalized = value
    elif value.startswith("00"):
        normalized = "+" + value[2:]
    else:
        normalized = "+" + value
    try:
        number = phonenumbers.parse(normalized, None)
    except phonenumbers.NumberParseException as exc:
        raise ValueError("Нужен номер с кодом страны: 79991234567 или +79991234567") from exc
    if not phonenumbers.is_valid_number(number):
        raise ValueError("Номер не проходит проверку формата для своей страны")
    e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    return PhoneResult(
        number=e164,
        country=geocoder.description_for_number(number, "ru") or "Регион не определён",
        country_code=f"+{number.country_code}",
    )


def validate_url(value: str) -> str:
    value = (value or "").strip()
    if not value or len(value) > 4096 or any(ch.isspace() for ch in value):
        raise ValueError("Вставьте полный URL без пробелов (до 4096 символов)")
    parts = urlsplit(value)
    if parts.scheme.lower() != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("Разрешены только полноценные HTTPS-ссылки без логина/пароля в URL")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("Некорректный порт в URL") from exc
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Некорректный порт в URL")
    return value


def auth_like(value: str) -> bool:
    """Potential sign-in/verification links need human-in-the-loop browser auth."""
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    path = parts.path.lower().strip("/")
    segments = [seg for seg in path.split("/") if seg]
    query_keys = {key.lower() for key in parse_qs(parts.query)}
    if host.startswith("oauth.") or "oauth" in host.split("."):
        return True
    if any(seg in {"oauth", "oauth2", "authorize", "authorization", "login", "signin", "verify"} for seg in segments):
        return True
    if any(seg == "auth" for seg in segments):
        return True
    if {"bot_id", "request_access"} & query_keys:
        return True
    return False


def url_overview(value: str) -> dict[str, str | int]:
    parts = urlsplit(validate_url(value))
    return {
        "host": parts.hostname or "",
        "path": parts.path or "/",
        "params": len(parse_qs(parts.query)),
        "kind": "browser" if auth_like(value) else "api",
    }


def safe_url_label(value: str) -> str:
    """Do not expose query tokens in logging/history."""
    parts = urlsplit(value)
    return f"{parts.hostname or '?'}{parts.path or '/'}"


def _bearer_header(token: str) -> dict[str, str]:
    headers = {"User-Agent": "SMSTest/3.1", "Accept": "application/json"}
    token = (token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def send_one(
    url: str,
    phone: str,
    token: str = "",
    session=None,
    *,
    without_plus: bool = False,
) -> dict:
    """POST phone to an authorized SMS API; never automate sign-in/OTP URLs."""
    validate_url(url)
    if auth_like(url):
        raise ValueError("Ссылки авторизации открываются в браузере; POST сюда отключён")
    checked = validate_phone(phone)
    client = session if session is not None else requests
    response = client.post(
        url,
        headers=_bearer_header(token),
        data={"phone": checked.number.lstrip("+") if without_plus else checked.number},
        timeout=10,
        allow_redirects=False,
    )
    status = int(response.status_code)
    message_id = ""
    if 200 <= status < 300:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message_id = str(payload.get("message_id") or payload.get("id") or "")
        except ValueError:
            pass
    return {"status": status, "accepted": 200 <= status < 300, "message_id": message_id}


def poll_delivery(status_url: str, message_id: str, token: str = "", session=None) -> str:
    """A single status check; caller controls polling frequency and ceiling."""
    if not message_id:
        return "unknown"
    validate_url(status_url)
    if auth_like(status_url):
        raise ValueError("URL статуса не должен быть ссылкой входа")
    client = session if session is not None else requests
    response = client.get(
        status_url,
        headers=_bearer_header(token),
        params={"message_id": message_id},
        timeout=10,
        allow_redirects=False,
    )
    if not 200 <= response.status_code < 300:
        return f"HTTP {response.status_code}"
    try:
        data = response.json()
    except ValueError:
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    return str(data.get("status") or "unknown").lower()


def history_item(profile: dict, status: str, delivery: str) -> dict[str, str]:
    return {
        "at": datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M:%S"),
        "profile": str(profile.get("name", "API"))[:60],
        "endpoint": safe_url_label(profile["url"]),
        "status": status,
        "delivery": delivery,
    }

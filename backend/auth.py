"""Тонкий клиент центрального auth-шлюза (tg-authgw): логин делегирован шлюзу
(один общий Telegram-бот, группы под продукты), проверка сессии — ЛОКАЛЬНО
(HMAC-SHA256 секретом продукта). No-op без AUTHGW_URL + SESSION_SECRET → локальная
разработка и тесты идут без гейта.

Раньше здесь жил собственный поллер группы StoryBoard; теперь его роль у шлюза
(единственный getUpdates-консьюмер общего бота — иначе 409 Conflict). Совместимость
сохранена: enabled/verify_session/issue_session/is_admin/COOKIE прежние, поэтому уже
выданные сессии продолжают работать (verify проверяет только подпись+срок, а секрет
у ir свой → сессия другого продукта под ним не пройдёт).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

AUTHGW_URL = os.environ.get("AUTHGW_URL", "").rstrip("/")
PRODUCT = os.environ.get("AUTHGW_PRODUCT", "ir-storyboard")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")

COOKIE = "ir_session"
SESSION_TTL = 60 * 60 * 24 * 21      # 21 день (совпадает с TTL шлюза)


def enabled() -> bool:
    """Гейт активен: настроен центральный шлюз (URL) и секрет продукта."""
    return bool(AUTHGW_URL and SESSION_SECRET)


def _admin_tids() -> set:
    """Супер-админы (переназначают владельца любой компании) — Telegram id из env
    IR_ADMIN_TIDS (через запятую). Пусто = админов нет."""
    out = set()
    for part in os.environ.get("IR_ADMIN_TIDS", "").replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return out


def is_admin(tid) -> bool:
    try:
        return int(tid) in _admin_tids()
    except (TypeError, ValueError):
        return False


# ── session cookie: compact HMAC-signed token (формат идентичен tg_authgw.session) ──

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def issue_session(tid: int, name: str) -> str:
    """Локальная выдача сессии (для dev/совместимости). В проде сессию выдаёт шлюз."""
    body = _b64(json.dumps(
        {"p": PRODUCT, "tid": tid, "name": name, "iat": int(time.time())},
        separators=(",", ":")).encode())
    sig = _b64(hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_session(token: str) -> Optional[dict]:
    """Локальная проверка сессии: подпись (секретом ir) + срок. → {tid, name} или None.
    Поле product в теле НЕ проверяем: секрет у каждого продукта свой, поэтому сессия
    другого продукта под секретом ir подпись не пройдёт. Это сохраняет уже выданные
    (до миграции) сессии, у которых поля product в теле нет."""
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "==").decode())
    except Exception:  # noqa: BLE001
        return None
    if int(time.time()) - int(data.get("iat", 0)) > SESSION_TTL:
        return None
    return {"tid": data.get("tid"), "name": data.get("name")}


# ── проксирование логина в центральный шлюз ──────────────────────────────────────

def authgw_start() -> dict:
    """Начать вход: шлюз выдаёт {token, deep_link} на общего бота (продукт=ir-storyboard)."""
    r = requests.post(f"{AUTHGW_URL}/start", json={"product": PRODUCT}, timeout=15)
    r.raise_for_status()
    return r.json()


def authgw_status(token: str) -> dict:
    """Опрос статуса входа у шлюза. На approved вернёт подписанную session в теле."""
    r = requests.get(f"{AUTHGW_URL}/status", params={"token": token}, timeout=15)
    r.raise_for_status()
    return r.json()


def start_poller() -> None:
    """Совместимость: поллер теперь у шлюза, здесь — no-op."""
    return

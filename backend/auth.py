"""Telegram group-membership auth (magic-code over long-polling — no domain needed).

Flow: app generates a login token -> user opens the auth bot via a deep link and
taps Start -> the poller validates the token, checks the user's membership of the
work supergroup via getChatMember, and marks the token approved -> the app polls
/auth/status, gets a signed session cookie, and is in.

Auth is a no-op unless TELEGRAM_AUTH_BOT_TOKEN + TELEGRAM_GROUP_ID + SESSION_SECRET
are all set, so local dev and tests run unauthenticated.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_AUTH_BOT_TOKEN", "")
GROUP_ID = os.environ.get("TELEGRAM_GROUP_ID", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")

COOKIE = "ir_session"
SESSION_TTL = 60 * 60 * 24 * 21      # 21 days
TOKEN_TTL = 300                       # 5 min login window
_API = "https://api.telegram.org/bot{}/{}"


def enabled() -> bool:
    return bool(BOT_TOKEN and GROUP_ID and SESSION_SECRET)


# ── session cookie: compact HMAC-signed token (stdlib, no extra deps) ──────────

def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def issue_session(tid: int, name: str) -> str:
    body = _b64(json.dumps({"tid": tid, "name": name, "iat": int(time.time())},
                           separators=(",", ":")).encode())
    sig = _b64(hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_session(token: str) -> Optional[dict]:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(SESSION_SECRET.encode(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "==").decode())
    except Exception:
        return None
    if int(time.time()) - int(data.get("iat", 0)) > SESSION_TTL:
        return None
    return {"tid": data.get("tid"), "name": data.get("name")}


# ── in-memory login-token store (short-lived, no DB needed) ────────────────────

_lock = threading.Lock()
_tokens: dict[str, dict] = {}


def _gc_locked() -> None:
    now = time.time()
    for k in [k for k, v in _tokens.items() if now - v["ts"] > TOKEN_TTL]:
        _tokens.pop(k, None)


def create_login_token() -> str:
    t = secrets.token_urlsafe(16)
    with _lock:
        _gc_locked()
        _tokens[t] = {"status": "pending", "ts": time.time()}
    return t


def get_login_token(t: str) -> Optional[dict]:
    with _lock:
        _gc_locked()
        v = _tokens.get(t)
        return dict(v) if v else None


def consume_login_token(t: str) -> Optional[dict]:
    with _lock:
        return _tokens.pop(t, None)


def _update_token(t: str, **kw) -> None:
    with _lock:
        if t in _tokens:
            _tokens[t].update(kw)


# ── telegram bot api ──────────────────────────────────────────────────────────

def _tg(method: str, **params):
    return requests.get(_API.format(BOT_TOKEN, method), params=params, timeout=20).json()


_bot_username: Optional[str] = None


def bot_username() -> str:
    global _bot_username
    if _bot_username is None:
        try:
            d = _tg("getMe")
            _bot_username = d["result"]["username"] if d.get("ok") else ""
        except Exception:
            _bot_username = ""
    return _bot_username or ""


def is_group_member(user_id: int) -> bool:
    try:
        d = _tg("getChatMember", chat_id=GROUP_ID, user_id=user_id)
    except Exception as e:
        logger.warning("getChatMember failed: %s", e)
        return False
    if not d.get("ok"):
        return False
    return d["result"]["status"] in ("member", "administrator", "creator")


def _reply(chat_id, text: str) -> None:
    try:
        _tg("sendMessage", chat_id=chat_id, text=text)
    except Exception:
        pass


# ── long-poll loop: handle /start <token> ─────────────────────────────────────

def _poll_loop() -> None:
    offset = 0
    while True:
        try:
            d = requests.get(_API.format(BOT_TOKEN, "getUpdates"),
                             params={"offset": offset, "timeout": 25}, timeout=35).json()
            if not d.get("ok"):
                time.sleep(3)
                continue
            for u in d["result"]:
                offset = u["update_id"] + 1
                msg = u.get("message")
                if not msg:
                    continue
                text = (msg.get("text") or "").strip()
                if not text.startswith("/start"):
                    continue
                parts = text.split(maxsplit=1)
                token = parts[1].strip() if len(parts) > 1 else ""
                frm = msg.get("from", {})
                uid = frm.get("id")
                name = ("@" + frm["username"]) if frm.get("username") else \
                    (" ".join(filter(None, [frm.get("first_name"), frm.get("last_name")])) or str(uid))
                chat_id = msg["chat"]["id"]

                if not token or not get_login_token(token):
                    _reply(chat_id, "Ссылка для входа устарела — начни вход заново в приложении.")
                    continue
                if is_group_member(uid):
                    _update_token(token, status="approved", tid=uid, name=name)
                    _reply(chat_id, "✅ Доступ подтверждён. Вернись в приложение — вход выполнен.")
                else:
                    _update_token(token, status="denied")
                    _reply(chat_id, "⛔ Доступа нет. Попроси добавить тебя в рабочую группу StoryBoard.")
        except Exception as e:
            logger.warning("auth poll error: %s", e)
            time.sleep(3)


_poller_started = False


def start_poller() -> None:
    global _poller_started
    if not enabled() or _poller_started:
        return
    _poller_started = True
    threading.Thread(target=_poll_loop, name="tg-auth-poller", daemon=True).start()
    logger.info("telegram auth poller started (group=%s)", GROUP_ID)

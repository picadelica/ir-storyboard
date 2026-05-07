"""Wayback Machine integration.

lookup_snapshot — synchronous, cached, non-blocking (fast path).
save_snapshot   — called in a background thread (slow path, fire-and-forget).
"""
from __future__ import annotations

import threading
import time
import urllib.request
import urllib.parse
import json
from typing import Optional


_cache: dict[str, Optional[str]] = {}
_cache_lock = threading.Lock()

_SAVE_INTERVAL = 1.0   # ≥1 sec between saves (rate limit)
_save_lock = threading.Lock()
_last_save_at: float = 0.0


def lookup_snapshot(url: str, timestamp: str | None = None) -> Optional[str]:
    """Return closest Wayback snapshot URL, or None. Cached per URL."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    with _cache_lock:
        if url in _cache:
            return _cache[url]
    try:
        api_url = "https://archive.org/wayback/available?url=" + urllib.parse.quote(url, safe=":/")
        if timestamp:
            api_url += "&timestamp=" + timestamp
        req = urllib.request.Request(api_url, headers={"User-Agent": "ir-storyboard/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        snapshot = (data.get("archived_snapshots") or {}).get("closest") or {}
        result = snapshot.get("url") if snapshot.get("available") else None
    except Exception:
        result = None
    with _cache_lock:
        _cache[url] = result
    return result


def save_snapshot(url: str, timeout: float = 30.0) -> Optional[str]:
    """POST to Wayback save endpoint. Rate-limited to 1/sec. Returns archive URL or None."""
    global _last_save_at
    if not url or not url.startswith(("http://", "https://")):
        return None
    with _save_lock:
        now = time.monotonic()
        wait = _SAVE_INTERVAL - (now - _last_save_at)
        if wait > 0:
            time.sleep(wait)
        try:
            save_url = "https://web.archive.org/save/" + url
            req = urllib.request.Request(
                save_url, method="POST",
                headers={"User-Agent": "ir-storyboard/1.0", "Content-Length": "0"},
                data=b"",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                location = resp.headers.get("Content-Location") or resp.url
                archive = ("https://web.archive.org" + location
                           if location and location.startswith("/web/")
                           else location)
        except Exception:
            archive = None
        _last_save_at = time.monotonic()
    if archive:
        with _cache_lock:
            _cache[url] = archive
    return archive


def enqueue_save(url: str, source_id: int, conn_factory) -> None:
    """Fire-and-forget: save snapshot in background, then update sources.archive_url."""
    def _run():
        archive = save_snapshot(url)
        if archive:
            try:
                conn = conn_factory()
                conn.execute("UPDATE sources SET archive_url=? WHERE id=?", (archive, source_id))
                conn.commit()
                conn.close()
            except Exception:
                pass
    threading.Thread(target=_run, daemon=True).start()

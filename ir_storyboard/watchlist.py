"""Мониторинг: watchlist источников клиента и кандидаты на разбор.

Три вида источников (`watchlist_items.kind`):
  youtube_channel — канал/плейлист, обход через yt-dlp `--flat-playlist` (без скачивания);
  rss             — любой фид (в т.ч. RSS подкаста и YouTube-фид канала);
  search_query    — периодический веб-поиск по имени спикера (Tavily через llm.web_search).

Найденное складывается в `monitor_candidates` и НИКОГДА не разбирается автоматически:
разбор — существующий YouTube/Audio-ингест, запускает аналитик. Идемпотентность —
по `norm_url` (UNIQUE вместе с client_id), поэтому повторная проверка не плодит строк.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from .ingest.loaders.youtube_url import normalize_url as _yt_normalize

KINDS = ("youtube_channel", "rss", "search_query")

# Трекинговые параметры, которые не должны разводить один и тот же эпизод по двум строкам.
_DROP_PARAMS_PREFIX = ("utm_", "yclid", "gclid", "fbclid", "_openstat")


# ── URL ──────────────────────────────────────────────────────────────────────

def norm_candidate_url(url: str) -> str:
    """Нормализованный URL кандидата — ключ идемпотентности.

    YouTube (любой вариант: youtu.be, /shorts/, с t=/list=) сводится к каноническому
    watch?v=ID той же функцией, что и ингест, — поэтому кандидат и разобранный источник
    сходятся по строке. Остальное — схема+хост в нижнем регистре, без фрагмента,
    без трекинговых параметров, без хвостового слеша.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        return _yt_normalize(raw)
    except Exception:
        pass  # не YouTube — общая нормализация ниже
    p = urlparse(raw if "//" in raw else "https://" + raw)
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    query = urlencode([
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
        if not k.lower().startswith(_DROP_PARAMS_PREFIX)
    ])
    path = p.path.rstrip("/") or "/"
    return urlunparse(((p.scheme or "https").lower(), host, path, "", query, ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_item(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["config"] = json.loads(d.get("config") or "{}")
    except json.JSONDecodeError:
        d["config"] = {}
    return d


# ── CRUD watchlist ───────────────────────────────────────────────────────────

def add_item(conn: sqlite3.Connection, client_id: str, kind: str, config: dict,
             *, label: str = "", speaker_entity_id: Optional[int] = None,
             schedule: str = "daily", created_by: str = "") -> int:
    """Завести источник. Для youtube_channel ссылка на ВИДЕО тоже принимается —
    канал определяется по метаданным этого видео (аналитик редко держит под рукой
    ссылку именно на канал)."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    cfg = dict(config or {})
    if kind == "youtube_channel":
        cfg["url"] = resolve_channel_url(str(cfg.get("url", "")).strip())
        if not cfg["url"]:
            raise ValueError("нужна ссылка на канал или на любое видео с него")
    elif kind == "rss":
        if not str(cfg.get("feed_url", "")).strip():
            raise ValueError("нужна ссылка на фид")
    elif kind == "search_query":
        if not str(cfg.get("query", "")).strip():
            raise ValueError("нужен поисковый запрос")
        window = str(cfg.get("window") or "auto").strip().lower()
        if window not in WINDOWS and window != "auto":
            raise ValueError("окно поиска: auto | all | year | quarter | month")
        cfg["window"] = window

    cur = conn.execute(
        """INSERT INTO watchlist_items
             (client_id, kind, config, label, speaker_entity_id, schedule, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (client_id, kind, json.dumps(cfg, ensure_ascii=False), label or _default_label(kind, cfg),
         speaker_entity_id, schedule or "daily", created_by, _now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def _default_label(kind: str, cfg: dict) -> str:
    if kind == "search_query":
        return f"поиск: {cfg.get('query', '')}"
    return str(cfg.get("url") or cfg.get("feed_url") or "")


def list_items(conn: sqlite3.Connection, client_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT w.*, e.name AS speaker_name,
                  (SELECT COUNT(*) FROM monitor_candidates c
                    WHERE c.watchlist_item_id = w.id AND c.state = 'new') AS new_count
             FROM watchlist_items w
             LEFT JOIN entities e ON e.id = w.speaker_entity_id
            WHERE w.client_id = ?
            ORDER BY w.created_at DESC""",
        (client_id,),
    ).fetchall()
    return [_row_to_item(r) for r in rows]


def get_item(conn: sqlite3.Connection, item_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM watchlist_items WHERE id = ?", (item_id,)).fetchone()
    return _row_to_item(row) if row else None


def set_item_status(conn: sqlite3.Connection, item_id: int, status: str) -> None:
    if status not in ("active", "paused"):
        raise ValueError("status must be active|paused")
    conn.execute("UPDATE watchlist_items SET status = ? WHERE id = ?", (status, item_id))
    conn.commit()


def delete_item(conn: sqlite3.Connection, item_id: int) -> None:
    """Удалить источник. Кандидаты остаются: аналитик мог их уже разобрать, а история
    разбора — ценность (тот же принцип, что с work-items при удалении фактов)."""
    conn.execute("DELETE FROM watchlist_items WHERE id = ?", (item_id,))
    conn.commit()


# ── Обход источников ─────────────────────────────────────────────────────────

def resolve_channel_url(url: str) -> str:
    """Ссылка на канал из ссылки на канал ИЛИ на любое его видео."""
    u = (url or "").strip()
    if not u:
        return ""
    if not re.search(r"(watch\?v=|youtu\.be/|/shorts/|/live/)", u):
        return u.rstrip("/")
    try:
        from .ingest.loaders.youtube_url import fetch_metadata, normalize_url
        meta = fetch_metadata(normalize_url(u))
        return (getattr(meta, "channel_url", "") or "").rstrip("/") or u.rstrip("/")
    except Exception:
        return u.rstrip("/")


def fetch_channel_entries(channel_url: str, limit: int = 15) -> list[dict]:
    """Последние загрузки канала через yt-dlp flat-playlist (метаданные, без скачивания)."""
    url = channel_url.rstrip("/")
    if re.search(r"youtube\.com/(@|channel/|c/|user/)", url) and not url.endswith(
            ("/videos", "/streams", "/podcasts")):
        url += "/videos"
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        return []
    opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
            "skip_download": True, "playlistend": limit}
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # сеть/приватный канал/удалён — наверх как ошибка источника
        raise RuntimeError(f"yt-dlp: {exc}") from exc
    out: list[dict] = []
    for e in (info or {}).get("entries", []) or []:
        if not isinstance(e, dict):
            continue
        vid = e.get("id") or ""
        link = e.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
        if not link:
            continue
        if link.startswith("http") is False:
            link = f"https://www.youtube.com/watch?v={link}"
        thumbs = e.get("thumbnails") or []
        out.append({
            "url": link,
            "title": e.get("title") or "",
            "duration_sec": int(e.get("duration") or 0) or None,
            "published_at": _ts_to_date(e.get("release_timestamp") or e.get("timestamp")),
            "thumb_url": (thumbs[-1].get("url") if thumbs else "") or "",
            "description": (e.get("description") or "")[:600],
            "channel": e.get("channel") or e.get("uploader") or "",
        })
    return out


def _ts_to_date(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return ""


def fetch_rss_entries(feed_url: str, limit: int = 15) -> list[dict]:
    """RSS/Atom без внешних зависимостей (feedparser в проекте нет) — stdlib-парсер."""
    import xml.etree.ElementTree as ET
    try:
        import requests
        resp = requests.get(feed_url, timeout=20,
                            headers={"User-Agent": "ir-storyboard/2.0"})
        resp.raise_for_status()
        body = resp.content
    except Exception as exc:
        raise RuntimeError(f"rss: {exc}") from exc
    return parse_rss(body, limit=limit)


def parse_rss(body: bytes, limit: int = 15) -> list[dict]:
    """Разбор тела фида (вынесено, чтобы тестировать без сети)."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise RuntimeError(f"rss: битый XML ({exc})") from exc
    ns = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/"}
    out: list[dict] = []

    def _text(node, *paths) -> str:
        for path in paths:
            found = node.find(path, ns) if ":" in path or path.startswith("atom") else node.find(path)
            if found is not None:
                if found.text and found.text.strip():
                    return found.text.strip()
                href = found.get("href")
                if href:
                    return href.strip()
        return ""

    items = root.findall(".//item") or root.findall(".//atom:entry", ns)
    for it in items[:limit]:
        link = _text(it, "link", "atom:link")
        if not link:
            enc = it.find("enclosure")
            link = (enc.get("url") if enc is not None else "") or ""
        if not link:
            continue
        out.append({
            "url": link,
            "title": _text(it, "title", "atom:title"),
            "published_at": (_text(it, "pubDate", "atom:published", "atom:updated") or "")[:40],
            "duration_sec": None,
            "thumb_url": "",
            "description": (_text(it, "description", "atom:summary", "media:description") or "")[:600],
            "channel": "",
        })
    return out


def fetch_search_entries(query: str, limit: int = 10, since: str = "") -> list[dict]:
    """Поиск по имени спикера — тот же web_search, что в канале online_research
    (Tavily при ключе, детерминистский стаб без него). since='YYYY-MM-DD' — нижняя
    граница выдачи."""
    from .llm import web_search
    hits = web_search(query, max_hits=limit, since=since) or []
    return [{
        "url": h.url,
        "title": h.title or "",
        "published_at": getattr(h, "published", "") or "",
        "duration_sec": None,
        "thumb_url": "",
        "description": (h.snippet or "")[:600],
        "channel": "",
    } for h in hits if getattr(h, "url", "")]


# Окно поиска. Первый обход источника должен зачерпнуть архив — выступление
# двухлетней давности для матрицы такой же материал, как вчерашнее, если мы его
# ещё не разбирали. Дальше нужен только прирост, иначе каждый прогон возвращает
# одно и то же. Нахлёст — потому что поисковые индексы отстают на несколько дней.
BACKFILL_DAYS = 365
OVERLAP_DAYS = 7
WINDOWS = {"all": 0, "year": 365, "quarter": 92, "month": 31}


def search_window_since(item: dict, today: Optional[date] = None) -> str:
    """Нижняя граница поиска для источника: '' = без ограничения.

    config.window: 'auto' (по умолчанию) | 'all' | 'year' | 'quarter' | 'month'.
    В 'auto' первый обход берёт год, последующие — «с прошлой проверки минус нахлёст».
    """
    cfg = item.get("config") or {}
    window = str(cfg.get("window") or "auto").strip().lower()
    today = today or datetime.now(timezone.utc).date()

    if window in WINDOWS:
        days = WINDOWS[window]
        return "" if days == 0 else (today - timedelta(days=days)).isoformat()

    last = (item.get("last_checked_at") or "")[:10]
    if not last:
        return (today - timedelta(days=BACKFILL_DAYS)).isoformat()
    try:
        return (date.fromisoformat(last) - timedelta(days=OVERLAP_DAYS)).isoformat()
    except ValueError:
        return (today - timedelta(days=BACKFILL_DAYS)).isoformat()


def _entries_for_item(item: dict, limit: int) -> list[dict]:
    kind, cfg = item["kind"], item.get("config") or {}
    if kind == "youtube_channel":
        return fetch_channel_entries(str(cfg.get("url", "")), limit=limit)
    if kind == "rss":
        return fetch_rss_entries(str(cfg.get("feed_url", "")), limit=limit)
    if kind == "search_query":
        return fetch_search_entries(str(cfg.get("query", "")), limit=limit,
                                    since=search_window_since(item))
    raise ValueError(f"unknown kind: {kind}")


# ── Проверка и кандидаты ─────────────────────────────────────────────────────

def speaker_names(conn: sqlite3.Connection, client_id: str,
                  speaker_entity_id: Optional[int] = None) -> list[str]:
    """Имена, по которым судим о релевантности: спикер источника, иначе все фаундеры."""
    if speaker_entity_id:
        row = conn.execute("SELECT name FROM entities WHERE id = ?", (speaker_entity_id,)).fetchone()
        if row and (row["name"] or "").strip():
            return [row["name"].strip()]
    rows = conn.execute(
        "SELECT name FROM entities WHERE client_id = ? AND kind = 'founder' ORDER BY sort_order",
        (client_id,),
    ).fetchall()
    return [r["name"].strip() for r in rows if (r["name"] or "").strip()]


def check_item(conn: sqlite3.Connection, item_id: int, *, limit: int = 15) -> dict:
    """Обойти один источник, записать новых кандидатов. Возвращает {found, new, error}."""
    item = get_item(conn, item_id)
    if not item:
        raise ValueError(f"watchlist item {item_id} not found")
    client_id = item["client_id"]
    result = {"item_id": item_id, "label": item.get("label", ""), "found": 0, "new": 0, "error": ""}
    try:
        entries = _entries_for_item(item, limit)
    except Exception as exc:  # noqa: BLE001 — ошибка источника не роняет обход остальных
        conn.execute("UPDATE watchlist_items SET last_checked_at = ?, last_error = ? WHERE id = ?",
                     (_now(), str(exc)[:400], item_id))
        conn.commit()
        result["error"] = str(exc)[:400]
        return result

    result["found"] = len(entries)
    fresh: list[dict] = []
    for e in entries:
        norm = norm_candidate_url(e.get("url", ""))
        if not norm:
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO monitor_candidates
                 (client_id, watchlist_item_id, url, norm_url, title, published_at,
                  duration_sec, thumb_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (client_id, item_id, e.get("url", ""), norm, e.get("title", ""),
             e.get("published_at", "") or "", e.get("duration_sec"),
             e.get("thumb_url", "") or "", _now()),
        )
        if cur.rowcount:
            row = conn.execute(
                "SELECT id FROM monitor_candidates WHERE client_id = ? AND norm_url = ?",
                (client_id, norm),
            ).fetchone()
            fresh.append({**e, "id": row["id"]})
    conn.commit()
    result["new"] = len(fresh)

    if fresh:
        _assess_and_store(conn, client_id, item, fresh)
    conn.execute("UPDATE watchlist_items SET last_checked_at = ?, last_error = '' WHERE id = ?",
                 (_now(), item_id))
    conn.commit()
    return result


def _assess_and_store(conn: sqlite3.Connection, client_id: str, item: dict,
                      fresh: list[dict]) -> None:
    """Дешёвый фильтр ПЕРЕД дорогой транскрипцией: модель смотрит только метаданные."""
    from .llm import assess_candidate_relevance
    names = speaker_names(conn, client_id, item.get("speaker_entity_id"))
    crow = conn.execute("SELECT name FROM clients WHERE id = ?", (client_id,)).fetchone()
    verdicts = assess_candidate_relevance(
        [{"title": e.get("title", ""), "description": e.get("description", ""),
          "channel": e.get("channel", ""), "url": e.get("url", "")} for e in fresh],
        speaker_names=names,
        company_name=(crow["name"] if crow else "") or "",
    )
    for e, v in zip(fresh, verdicts):
        relevance = v.get("relevance", "unclear")
        conn.execute(
            "UPDATE monitor_candidates SET relevance = ?, relevance_note = ? WHERE id = ?",
            (relevance, (v.get("note", "") or "")[:300], e["id"]),
        )
        # Дату знают не все источники (веб-поиск отдаёт её редко), а без даты аналитик
        # не видит, свежее это выступление или трёхлетней давности. Для ютубовских
        # ссылок дотягиваем метаданными — но только для тех, что прошли фильтр:
        # платить секундой сети за отсеянное незачем.
        if relevance != "unlikely" and not (e.get("published_at") or ""):
            date_str = _fetch_published_at(e.get("url", ""))
            if date_str:
                conn.execute("UPDATE monitor_candidates SET published_at = ?, duration_sec = "
                             "COALESCE(duration_sec, ?) WHERE id = ?",
                             (date_str[0], date_str[1], e["id"]))
    conn.commit()


def _fetch_published_at(url: str) -> Optional[tuple[str, Optional[int]]]:
    """(дата, длительность) для YouTube-ссылки. Любая осечка — молча None."""
    if not re.search(r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/)", url or ""):
        return None
    try:
        from .ingest.loaders.youtube_url import fetch_metadata, normalize_url
        meta = fetch_metadata(normalize_url(url))
        return ((meta.upload_date or "")[:10], meta.duration_sec or None)
    except Exception:
        return None


def reassess_candidates(conn: sqlite3.Connection, client_id: str,
                        states: tuple = ("new",)) -> dict:
    """Пересчитать релевантность уже собранных находок (после правки промпта).

    Судим по тому, что сохранено: заголовок и ссылка (описание из выдачи мы не храним —
    это осознанно, снимок чужого текста нам не нужен). Домен при этом сам по себе
    сильный сигнал о форме, так что переоценка осмысленна. Дальше — обычная запись
    вердикта; состояние кандидата (`dismissed`/`ingested`) не трогаем.
    """
    from .llm import assess_candidate_relevance

    placeholders = ",".join("?" * len(states))
    rows = [dict(r) for r in conn.execute(
        f"""SELECT c.id, c.title, c.url, c.norm_url, c.relevance, c.watchlist_item_id
              FROM monitor_candidates c
             WHERE c.client_id = ? AND c.state IN ({placeholders})""",
        (client_id, *states))]
    if not rows:
        return {"client_id": client_id, "checked": 0, "changed": 0}

    crow = conn.execute("SELECT name FROM clients WHERE id = ?", (client_id,)).fetchone()
    company = (crow["name"] if crow else "") or ""
    changed = 0
    by_item: dict[Any, list[dict]] = {}
    for r in rows:
        by_item.setdefault(r["watchlist_item_id"], []).append(r)

    for item_id, group in by_item.items():
        item = get_item(conn, item_id) or {}
        names = speaker_names(conn, client_id, item.get("speaker_entity_id"))
        for start in range(0, len(group), 20):
            chunk = group[start:start + 20]
            verdicts = assess_candidate_relevance(
                [{"title": r["title"], "url": r["norm_url"] or r["url"],
                  "description": "", "channel": ""} for r in chunk],
                speaker_names=names, company_name=company,
            )
            for r, v in zip(chunk, verdicts):
                new_rel = v.get("relevance", "unclear")
                if new_rel != r["relevance"]:
                    changed += 1
                conn.execute(
                    "UPDATE monitor_candidates SET relevance = ?, relevance_note = ? WHERE id = ?",
                    (new_rel, (v.get("note", "") or "")[:300], r["id"]))
    conn.commit()
    return {"client_id": client_id, "checked": len(rows), "changed": changed}


def check_client(conn: sqlite3.Connection, client_id: str, *, limit: int = 15) -> dict:
    """Обойти все активные источники клиента."""
    rows = conn.execute(
        "SELECT id FROM watchlist_items WHERE client_id = ? AND status = 'active' ORDER BY id",
        (client_id,),
    ).fetchall()
    per_item = [check_item(conn, r["id"], limit=limit) for r in rows]
    return {
        "client_id": client_id,
        "items_checked": len(per_item),
        "found": sum(r["found"] for r in per_item),
        "new": sum(r["new"] for r in per_item),
        "errors": [r for r in per_item if r["error"]],
        "per_item": per_item,
    }


_RELEVANCE_ORDER = {"likely": 0, "unclear": 1, "unlikely": 2}


def list_candidates(conn: sqlite3.Connection, client_id: str,
                    state: Optional[str] = "new") -> list[dict]:
    """Кандидаты клиента. Сначала подтягиваем разобранные (см. link_ingested)."""
    link_ingested(conn, client_id)
    sql = """SELECT c.*, w.label AS item_label, w.kind AS item_kind,
                    w.speaker_entity_id AS speaker_entity_id
               FROM monitor_candidates c
               LEFT JOIN watchlist_items w ON w.id = c.watchlist_item_id
              WHERE c.client_id = ?"""
    args: list[Any] = [client_id]
    if state:
        sql += " AND c.state = ?"
        args.append(state)
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    rows.sort(key=lambda r: (_RELEVANCE_ORDER.get(r.get("relevance") or "unclear", 1),
                             -(_date_key(r.get("published_at") or "")),
                             -(r.get("id") or 0)))
    return rows


def _date_key(value: str) -> int:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", value or "")
    if m:
        return int(m.group(1) + m.group(2) + m.group(3))
    return 0


def link_ingested(conn: sqlite3.Connection, client_id: str) -> int:
    """Связать кандидатов с источниками, которые появились после разбора.

    Путь ингеста не трогаем вообще: строка `sources` заводится им как обычно, а связка
    восстанавливается здесь по совпадению нормализованного URL. Отсюда же — переход
    state → 'ingested'.
    """
    rows = conn.execute(
        """SELECT id, norm_url FROM monitor_candidates
            WHERE client_id = ? AND state IN ('new','ingesting')""",
        (client_id,),
    ).fetchall()
    linked = 0
    for r in rows:
        src = conn.execute("SELECT id FROM sources WHERE url = ?", (r["norm_url"],)).fetchone()
        if src:
            conn.execute(
                "UPDATE monitor_candidates SET state = 'ingested', source_id = ? WHERE id = ?",
                (src["id"], r["id"]),
            )
            linked += 1
    if linked:
        conn.commit()
    return linked


def set_candidate_state(conn: sqlite3.Connection, candidate_id: int, state: str,
                        actor: str = "") -> dict:
    """Смена состояния кандидата + след, кто это сделал (журнал действий аналитика)."""
    if state not in ("new", "ingesting", "ingested", "dismissed"):
        raise ValueError("bad state")
    conn.execute(
        "UPDATE monitor_candidates SET state = ?, acted_by = ?, acted_at = ? WHERE id = ?",
        (state, actor or "", _now(), candidate_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM monitor_candidates WHERE id = ?", (candidate_id,)).fetchone()
    if not row:
        raise ValueError(f"candidate {candidate_id} not found")
    return dict(row)


def get_candidate(conn: sqlite3.Connection, candidate_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM monitor_candidates WHERE id = ?", (candidate_id,)).fetchone()
    return dict(row) if row else None


# ── Предложения: каналы, с которых уже брали руками ──────────────────────────

def suggestions(conn: sqlite3.Connection, client_id: str) -> list[dict]:
    """Каналы, откуда аналитик уже разбирал видео этого клиента, но которых нет в
    watchlist. «Вы дважды брали видео с канала X — добавить в мониторинг?»"""
    rows = conn.execute(
        """SELECT preview_json FROM ingest_audit
            WHERE client_id = ? AND ingest_kind = 'youtube' AND committed_at IS NOT NULL""",
        (client_id,),
    ).fetchall()
    seen: dict[str, dict] = {}
    for r in rows:
        try:
            meta = (json.loads(r["preview_json"] or "{}") or {}).get("meta") or {}
        except json.JSONDecodeError:
            continue
        name = (meta.get("channel_name") or "").strip()
        url = (meta.get("canonical_url") or "").strip()
        if not name or not url:
            continue
        entry = seen.setdefault(name, {"channel_name": name, "count": 0, "sample_url": url})
        entry["count"] += 1

    known = set()
    for item in list_items(conn, client_id):
        cfg = item.get("config") or {}
        label = (item.get("label") or "").strip().lower()
        known.add(label)
        for key in ("url", "feed_url"):
            if cfg.get(key):
                known.add(str(cfg[key]).strip().lower())
    out = [s for s in seen.values() if s["channel_name"].strip().lower() not in known]
    out.sort(key=lambda s: -s["count"])
    return out


# ── Планировщик ──────────────────────────────────────────────────────────────

def due_client_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT client_id FROM watchlist_items WHERE status = 'active'"
    ).fetchall()
    return [r["client_id"] for r in rows]


def run_scheduled_check(db_path=None) -> dict:
    """Один проход планировщика по всем клиентам с активными источниками."""
    from . import db as _db
    conn = _db.connect(db_path or _db.DEFAULT_DB_PATH)
    try:
        _db.init_schema(conn)
        totals = {"clients": 0, "new": 0}
        for cid in due_client_ids(conn):
            res = check_client(conn, cid)
            totals["clients"] += 1
            totals["new"] += res["new"]
        return totals
    finally:
        conn.close()


def scheduler_interval_min() -> int:
    """MONITORING_INTERVAL_MIN: 0/пусто = планировщик выключен (дефолт)."""
    try:
        return max(0, int(os.environ.get("MONITORING_INTERVAL_MIN", "0") or 0))
    except ValueError:
        return 0


def start_scheduler(db_path=None) -> bool:
    """Фоновый поток-цикл внутри приложения (системный cron на сервере не заводим —
    у проекта нет собственного планировщика, а деплой пересоздаёт контейнер)."""
    interval = scheduler_interval_min()
    if interval <= 0:
        return False
    import threading
    import time

    def _loop() -> None:
        while True:
            time.sleep(interval * 60)
            try:
                run_scheduled_check(db_path)
            except Exception:  # noqa: BLE001 — планировщик не должен падать насмерть
                pass

    threading.Thread(target=_loop, daemon=True, name="monitoring-scheduler").start()
    return True

"""Обзор эпизода: о чём говорили и что сдвинулось с прошлых выступлений.

Read-only материал для аналитика поверх УЖЕ сделанной расшифровки. Путь фактов
(атомизация → превью → коммит) не трогается вообще: обзор собирается отдельным job-ом
из кэша расшифровок (`youtube_transcripts` / `audio_transcripts`), поэтому повторной
транскрипции не требует и на результат ингеста повлиять не может.

Хранение — append-only: строка `digests` создаётся сразу со сравнением внутри
`payload.comparison`; повторный вызов по той же паре (эпизод, спикер) возвращает
существующую запись, а не переписывает её.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

from .watchlist import norm_candidate_url

_MAX_PREVIOUS = 10


# ── Расшифровка из кэша ──────────────────────────────────────────────────────

def load_cached_transcript(conn: sqlite3.Connection, url: str) -> Optional[dict]:
    """{segments, meta} по кэшу расшифровок. None — если эпизод ещё не расшифрован."""
    from .ingest.loaders.transcriber import (_ensure_transcripts_table,
                                             _ensure_audio_transcripts_table)
    _ensure_transcripts_table(conn)
    _ensure_audio_transcripts_table(conn)
    norm = norm_candidate_url(url)
    row = conn.execute(
        "SELECT * FROM youtube_transcripts WHERE canonical_url IN (?, ?)", (norm, url)
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM audio_transcripts WHERE canonical_url IN (?, ?)", (norm, url)
        ).fetchone()
    if row is None:
        return None
    try:
        segments = json.loads(row["segments_json"] or "[]")
    except json.JSONDecodeError:
        segments = []
    return {
        "segments": segments,
        "meta": {
            "title": row["title"] or "",
            "channel_name": row["channel_name"] or "",
            "duration_sec": row["duration_sec"] or 0,
            "language": row["language"] or "",
        },
    }


def episode_date(conn: sqlite3.Connection, client_id: str, norm_url: str) -> str:
    """Дата выступления — из превью ингеста этого эпизода (сети не требует)."""
    rows = conn.execute(
        """SELECT preview_json FROM ingest_audit
            WHERE client_id = ? AND source_artifact = ?
            ORDER BY parsed_at DESC LIMIT 1""",
        (client_id, norm_url),
    ).fetchall()
    for r in rows:
        try:
            meta = (json.loads(r["preview_json"] or "{}") or {}).get("meta") or {}
        except json.JSONDecodeError:
            continue
        if meta.get("upload_date"):
            return str(meta["upload_date"])[:40]
    return ""


# ── Спикер ───────────────────────────────────────────────────────────────────

def resolve_speaker(conn: sqlite3.Connection, client_id: str,
                    speaker_entity_id: Optional[int] = None) -> Optional[int]:
    """Явно выбранный спикер, иначе — единственный фаундер клиента. Двое и больше без
    явного выбора → None: обзор просто не собирается, факты идут как всегда."""
    if speaker_entity_id:
        row = conn.execute(
            "SELECT id FROM entities WHERE id = ? AND client_id = ?",
            (speaker_entity_id, client_id),
        ).fetchone()
        return int(row["id"]) if row else None
    rows = conn.execute(
        "SELECT id FROM entities WHERE client_id = ? AND kind = 'founder'", (client_id,)
    ).fetchall()
    return int(rows[0]["id"]) if len(rows) == 1 else None


def speaker_name(conn: sqlite3.Connection, entity_id: Optional[int]) -> str:
    if not entity_id:
        return ""
    row = conn.execute("SELECT name FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return (row["name"] if row else "") or ""


# ── Валидация цитат ──────────────────────────────────────────────────────────

_WS = re.compile(r"\s+")


def _norm_quote(text: str) -> str:
    return _WS.sub(" ", (text or "").lower().replace("ё", "е")).strip(" \t\n«»\"'—-–.,!?")


def validate_quotes(payload: dict, segments: list) -> dict:
    """Цитата, которой нет в расшифровке дословно, помечается unverified=True.

    Не удаляем: аналитику полезно видеть, что модель приукрасила формулировку —
    это сигнал о качестве обзора, а не мусор.
    """
    haystack = _norm_quote(" ".join((s.get("text") or "") for s in segments))
    for m in payload.get("key_moments") or []:
        q = _norm_quote(m.get("quote", ""))
        m["unverified"] = not (q and q in haystack)
    comparison = payload.get("comparison") or {}
    for d in (comparison.get("details") or []):
        now = d.get("now") or {}
        q = _norm_quote(now.get("quote", ""))
        if q:
            now["unverified"] = q not in haystack
    return payload


# ── Хранение ─────────────────────────────────────────────────────────────────

def get_digest(conn: sqlite3.Connection, norm_url: str,
               speaker_entity_id: Optional[int]) -> Optional[dict]:
    if not speaker_entity_id:
        return None
    row = conn.execute(
        "SELECT * FROM digests WHERE norm_url = ? AND speaker_entity_id = ?",
        (norm_url, speaker_entity_id),
    ).fetchone()
    return _row_to_digest(row) if row else None


def digests_for_source(conn: sqlite3.Connection, source_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM digests WHERE source_id = ? ORDER BY created_at",
                        (source_id,)).fetchall()
    return [_row_to_digest(r) for r in rows]


def _row_to_digest(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["payload"] = json.loads(d.get("payload") or "{}")
    except json.JSONDecodeError:
        d["payload"] = {}
    return d


def previous_digests(conn: sqlite3.Connection, speaker_entity_id: int,
                     exclude_norm_url: str = "") -> list[dict]:
    """Прошлые обзоры этого спикера по возрастанию даты — вход для сравнения."""
    rows = conn.execute(
        """SELECT * FROM digests
            WHERE speaker_entity_id = ? AND norm_url != ?
            ORDER BY COALESCE(NULLIF(episode_date,''), created_at) ASC""",
        (speaker_entity_id, exclude_norm_url),
    ).fetchall()
    out = []
    for r in rows[-_MAX_PREVIOUS:]:
        d = _row_to_digest(r)
        payload = d["payload"]
        out.append({
            "date": d.get("episode_date") or (d.get("created_at") or "")[:10],
            "main_motif": payload.get("main_motif", ""),
            "key_moments": payload.get("key_moments", []),
            "comparison_details": (payload.get("comparison") or {}).get("details", []),
        })
    return out


def link_source(conn: sqlite3.Connection, norm_url: str) -> None:
    """Проставить source_id обзорам эпизода, когда источник появился (после коммита)."""
    src = conn.execute("SELECT id FROM sources WHERE url = ?", (norm_url,)).fetchone()
    if src:
        conn.execute("UPDATE digests SET source_id = ? WHERE norm_url = ? AND source_id IS NULL",
                     (src["id"], norm_url))
        conn.commit()


# ── Сборка ───────────────────────────────────────────────────────────────────

def build_and_store(conn: sqlite3.Connection, client_id: str, url: str,
                    speaker_entity_id: Optional[int] = None,
                    *, force: bool = False) -> dict:
    """Собрать обзор эпизода (со сравнением, если у спикера есть прошлые).

    Возвращает {status, digest|reason}. status:
      ok            — обзор готов (или уже был: идемпотентность по эпизод×спикер);
      no_speaker    — спикер не определён, обзор не нужен;
      no_transcript — эпизод ещё не расшифрован (обзор собирается после ингеста).
    """
    from . import llm

    norm = norm_candidate_url(url)
    speaker = resolve_speaker(conn, client_id, speaker_entity_id)
    if not speaker:
        return {"status": "no_speaker", "reason": "спикер не определён"}

    existing = get_digest(conn, norm, speaker)
    if existing and not force:
        return {"status": "ok", "digest": existing, "cached": True}

    cached = load_cached_transcript(conn, url)
    if not cached or not cached["segments"]:
        return {"status": "no_transcript", "reason": "расшифровки этого эпизода ещё нет"}

    crow = conn.execute("SELECT name FROM clients WHERE id = ?", (client_id,)).fetchone()
    company = (crow["name"] if crow else "") or ""
    date = episode_date(conn, client_id, norm)
    meta = {**cached["meta"], "upload_date": date}
    sname = speaker_name(conn, speaker)

    payload = llm.build_episode_digest(cached["segments"], meta=meta,
                                       speaker_name=sname, company_name=company)
    prev = previous_digests(conn, speaker, exclude_norm_url=norm)
    payload["comparison"] = (llm.compare_with_previous_digests(payload, prev, speaker_name=sname)
                             if prev else None)
    payload = validate_quotes(payload, cached["segments"])

    src = conn.execute("SELECT id FROM sources WHERE url = ?", (norm,)).fetchone()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO digests
             (id, client_id, norm_url, source_id, speaker_entity_id, episode_date,
              title, payload, model, created_at)
           VALUES ((SELECT id FROM digests WHERE norm_url = ? AND speaker_entity_id = ?),
                   ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (norm, speaker,
         client_id, norm, (src["id"] if src else None), speaker, date,
         meta.get("title", ""), json.dumps(payload, ensure_ascii=False),
         _digest_model(), now),
    )
    conn.commit()
    return {"status": "ok", "digest": get_digest(conn, norm, speaker), "cached": False}


def _digest_model() -> str:
    import os
    return os.environ.get("LLM_DIGEST_MODEL", "") or os.environ.get(
        "LLM_CLASSIFY_MODEL", "claude-sonnet-4-6")

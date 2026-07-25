"""CRUD operations on the persistent matrix."""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import (
    LAYERS, LayerSpec, SubsectionSpec, layer_by_id, subsection_by_id,
    channel_can_fill,
    FLAG_GREEN, FLAG_RED, FLAG_GREY,
    ALL_CHANNELS,
)


# ---------- bootstrap reference data ----------

def seed_layers(conn: sqlite3.Connection) -> None:
    """Insert the canonical 8 layers + their subsections (idempotent)."""
    cur = conn.cursor()
    for L in LAYERS:
        cur.execute(
            """INSERT OR IGNORE INTO layers (id, code, name, intimacy, primary_channels)
                VALUES (?, ?, ?, ?, ?)""",
            (L.id, L.code, L.name, L.intimacy, json.dumps(L.primary_channels)),
        )
        for s in L.subsections:
            cur.execute(
                """INSERT OR IGNORE INTO subsections
                    (id, layer_id, code, name, description, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                (s.id, L.id, s.code, s.name, s.description, s.sort_order),
            )
    conn.commit()


# ---------- clients ----------

def upsert_client(conn: sqlite3.Connection, client_id: str, name: str,
                  sector: str = "", one_liner: str = "",
                  founder_name: str = "", founder_handle: str = "",
                  aliases: Optional[List[str]] = None, notes: str = "",
                  tone_preset: Optional[str] = None) -> None:
    conn.execute(
        """INSERT INTO clients (id, name, sector, one_liner, founder_name, founder_handle,
                                aliases, notes, tone_preset)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 'business'))
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, sector=excluded.sector, one_liner=excluded.one_liner,
                founder_name=excluded.founder_name, founder_handle=excluded.founder_handle,
                aliases=excluded.aliases, notes=excluded.notes,
                tone_preset=COALESCE(excluded.tone_preset, clients.tone_preset)""",
        (client_id, name, sector, one_liner,
         founder_name, founder_handle, json.dumps(aliases or []), notes, tone_preset),
    )
    conn.commit()


# ---------- methodology (per-subsection description + per-client tone) ----------

def get_subsection_descriptions(conn: sqlite3.Connection) -> Dict[str, str]:
    """Return {subsection_id: description} for all 24 cells."""
    rows = conn.execute(
        "SELECT id, COALESCE(description, '') AS description FROM subsections"
    ).fetchall()
    return {r["id"]: r["description"] for r in rows}


def update_subsection_description(conn: sqlite3.Connection,
                                  subsection_id: str,
                                  description: str) -> None:
    """Overwrite the description for one subsection."""
    cur = conn.execute(
        "UPDATE subsections SET description = ? WHERE id = ?",
        (description, subsection_id),
    )
    if cur.rowcount == 0:
        raise ValueError(f"Unknown subsection_id: {subsection_id}")
    conn.commit()


def get_client_tone_preset(conn: sqlite3.Connection, client_id: str) -> str:
    """Return the client's tone preset id, defaulting to 'business' if missing."""
    row = conn.execute(
        "SELECT tone_preset FROM clients WHERE id = ?", (client_id,)
    ).fetchone()
    if not row:
        return "business"
    return (row["tone_preset"] or "business").strip() or "business"


def set_client_tone_preset(conn: sqlite3.Connection,
                            client_id: str, preset_id: str) -> None:
    cur = conn.execute(
        "UPDATE clients SET tone_preset = ? WHERE id = ?",
        (preset_id, client_id),
    )
    if cur.rowcount == 0:
        raise ValueError(f"Unknown client_id: {client_id}")
    conn.commit()


def get_client_subsection_notes(conn: sqlite3.Connection,
                                  client_id: str) -> Dict[str, str]:
    """Return {sid: per-client note} for this client (only non-empty rows)."""
    rows = conn.execute(
        "SELECT subsection_id, note FROM client_subsection_notes WHERE client_id = ?",
        (client_id,),
    ).fetchall()
    return {r["subsection_id"]: r["note"] for r in rows if (r["note"] or "").strip()}


def set_client_subsection_note(conn: sqlite3.Connection,
                                client_id: str, subsection_id: str,
                                note: str) -> None:
    """Upsert per-client note. Empty string deletes the row."""
    if not (note or "").strip():
        conn.execute(
            "DELETE FROM client_subsection_notes WHERE client_id = ? AND subsection_id = ?",
            (client_id, subsection_id),
        )
    else:
        conn.execute(
            """INSERT INTO client_subsection_notes (client_id, subsection_id, note)
                VALUES (?, ?, ?)
                ON CONFLICT(client_id, subsection_id) DO UPDATE
                    SET note = excluded.note,
                        updated_at = CURRENT_TIMESTAMP""",
            (client_id, subsection_id, note.strip()),
        )
    conn.commit()


def count_client_facts(conn: sqlite3.Connection, client_id: str) -> int:
    row = conn.execute(
        """SELECT COUNT(*) FROM facts f
            JOIN cells c ON c.id = f.cell_id
            WHERE c.client_id = ?""",
        (client_id,),
    ).fetchone()
    return row[0] if row else 0


def list_clients(conn: sqlite3.Connection, include_hidden: bool = False) -> List[sqlite3.Row]:
    where = "" if include_hidden else "WHERE COALESCE(hidden, 0) = 0"
    return list(conn.execute(f"SELECT * FROM clients {where} ORDER BY name"))


# ---------- users + roles (multi-user) ----------

def upsert_user(conn: sqlite3.Connection, tid: int, name: str, username: str = "") -> None:
    """Запомнить Telegram-юзера (наполняется при входе). Имя обновляем, username —
    только если непустой (не затираем сохранённый)."""
    if not tid:
        return
    conn.execute(
        """INSERT INTO users (tid, name, username) VALUES (?, ?, ?)
           ON CONFLICT(tid) DO UPDATE SET
             name = excluded.name,
             username = CASE WHEN excluded.username <> '' THEN excluded.username ELSE users.username END,
             last_seen = CURRENT_TIMESTAMP""",
        (tid, name or "", username or ""))
    conn.commit()


def list_users(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT tid, name, username, last_seen FROM users ORDER BY name COLLATE NOCASE")]


def contributor_tids_for_clients(conn: sqlite3.Connection,
                                 client_ids: List[str]) -> set:
    """tid'ы всех, кто вносил факты в компании из списка (для owner-скоупа обзора юзеров)."""
    if not client_ids:
        return set()
    ph = ",".join("?" * len(client_ids))
    rows = conn.execute(
        f"""SELECT DISTINCT f.created_by_tid FROM facts f JOIN cells c ON c.id = f.cell_id
             WHERE c.client_id IN ({ph}) AND f.created_by_tid IS NOT NULL""",
        tuple(client_ids),
    ).fetchall()
    return {r[0] for r in rows}


def users_overview(conn: sqlite3.Connection,
                   only_tids: Optional[set] = None) -> List[Dict[str, Any]]:
    """«Кто есть кто»: юзеры + владелец каких компаний + активность (внёс/одобрил фактов,
    последний вход). only_tids — ограничить набор (owner-скоуп). is_admin проставляет вызывающий."""
    users = conn.execute(
        "SELECT tid, name, username, first_seen, last_seen FROM users "
        "ORDER BY name COLLATE NOCASE"
    ).fetchall()
    activity = user_activity_counts(conn)   # реальная активность из журнала (переносы/склейки/правки)
    out: List[Dict[str, Any]] = []
    for u in users:
        tid = u["tid"]
        if only_tids is not None and tid not in only_tids:
            continue
        owned = [r["name"] for r in conn.execute(
            "SELECT name FROM clients WHERE owner_tid = ? AND hidden = 0 "
            "ORDER BY name COLLATE NOCASE", (tid,))]
        created = conn.execute(
            "SELECT count(*) FROM facts WHERE created_by_tid = ?", (tid,)).fetchone()[0]
        approved = conn.execute(
            "SELECT count(*) FROM facts WHERE approved_by_tid = ?", (tid,)).fetchone()[0]
        out.append({
            "tid": tid, "name": u["name"], "username": u["username"],
            "first_seen": u["first_seen"], "last_seen": u["last_seen"],
            "owned_clients": owned, "facts_created": created, "facts_approved": approved,
            "actions": int(activity.get(tid, 0)),   # всего действий над карточками
        })
    return out


def get_user(conn: sqlite3.Connection, tid: int) -> Optional[Dict[str, Any]]:
    r = conn.execute("SELECT tid, name, username FROM users WHERE tid=?", (tid,)).fetchone()
    return dict(r) if r else None


def client_owner_tid(conn: sqlite3.Connection, client_id: str) -> Optional[int]:
    r = conn.execute("SELECT owner_tid FROM clients WHERE id=?", (client_id,)).fetchone()
    return r["owner_tid"] if r and r["owner_tid"] is not None else None


def set_client_owner(conn: sqlite3.Connection, client_id: str, tid: Optional[int]) -> None:
    conn.execute("UPDATE clients SET owner_tid=? WHERE id=?", (tid, client_id))
    conn.commit()


def set_client_hidden(conn: sqlite3.Connection, client_id: str, hidden: bool) -> None:
    conn.execute("UPDATE clients SET hidden=? WHERE id=?", (1 if hidden else 0, client_id))
    conn.commit()


# ---------- cells ----------

def get_or_create_cell(conn: sqlite3.Connection, client_id: str, subsection_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM cells WHERE client_id=? AND subsection_id=?",
        (client_id, subsection_id),
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO cells (client_id, subsection_id) VALUES (?, ?)",
        (client_id, subsection_id),
    )
    conn.commit()
    return cur.lastrowid


def ensure_full_grid(conn: sqlite3.Connection, client_id: str) -> None:
    """Ensure every (client, subsection) cell exists. New cells start empty (= implicit grey)."""
    for L in LAYERS:
        for s in L.subsections:
            get_or_create_cell(conn, client_id, s.id)


def active_facts_for_reclassify(conn: sqlite3.Connection,
                                client_id: str) -> List[sqlite3.Row]:
    """Active facts (in the matrix) с текущей подсекцией — вход переклассификации новой
    методологией. Исключаем факты, уже отнесённые к ТЕКУЩЕЙ версии методологии (не показываем
    повторно; при смене версии все переоцениваются заново)."""
    ver = get_methodology_version(conn)
    return list(conn.execute(
        """SELECT f.id AS id, f.text AS text, f.title AS title,
                  c.subsection_id AS subsection_id, f.about_company AS about_company
             FROM facts f JOIN cells c ON c.id = f.cell_id
            WHERE c.client_id = ? AND f.state = 'active'
              AND COALESCE(f.assigned_methodology_version, 0) <> ?
            ORDER BY f.id""",
        (client_id, ver),
    ))


def move_fact_to_subsection(conn: sqlite3.Connection, fact_id: int,
                            client_id: str, subsection_id: str, *,
                            method: str = "manual", moved_by: str = "",
                            moved_by_tid: Optional[int] = None) -> bool:
    """Переезд факта в другую ячейку (той же компании): cell_id → новая (client, subsection).
    Текст факта не трогается (инвариант неизменности). Возвращает False, если факт не
    принадлежит компании (защита от кросс-клиентского переезда).

    method='manual' (ручной перенос экспертом) → ставит placement_locked=1: последующие прогоны
    методологии этот факт НЕ трогают (экспертное решение выигрывает). method='reclassify'
    (применение прогона) → ставит reclassified_at. В обоих случаях пишем запись в
    fact_placement_history (для будущего админ-интерфейса)."""
    row = conn.execute(
        "SELECT c.client_id AS cid, c.subsection_id AS from_sid "
        "FROM facts f JOIN cells c ON c.id = f.cell_id WHERE f.id = ?",
        (fact_id,),
    ).fetchone()
    if not row or row["cid"] != client_id:
        return False
    from_sid = row["from_sid"]
    cell_id = get_or_create_cell(conn, client_id, subsection_id)
    ver = get_methodology_version(conn)
    assigned_by = "expert" if method == "manual" else "system"
    # отнесли карточку к текущей версии методологии + кем; reclassify для reclassify-переноса.
    conn.execute(
        "UPDATE facts SET cell_id = ?, assigned_methodology_version = ?, assigned_by = ?, "
        "reclassified_at = CASE WHEN ?='system' THEN CURRENT_TIMESTAMP ELSE reclassified_at END "
        "WHERE id = ?",
        (cell_id, ver, assigned_by, assigned_by, fact_id))
    record_activity(conn, fact_id, client_id, "moved", actor_name=moved_by, actor_tid=moved_by_tid,
                    from_sid=from_sid, to_sid=subsection_id, detail=method)
    conn.commit()
    return True


def record_activity(conn: sqlite3.Connection, fact_id: int, client_id: Optional[str],
                    action: str, *, actor_name: str = "", actor_tid: Optional[int] = None,
                    from_sid: Optional[str] = None, to_sid: Optional[str] = None,
                    detail: str = "") -> None:
    """Записать действие над карточкой в сквозной журнал (кто/что/когда + версия методологии,
    действовавшая в момент действия). Не коммитит — коммит на стороне вызывающей мутации.
    Тихо игнорирует, если таблицы нет (старые снапшоты БД)."""
    try:
        conn.execute(
            """INSERT INTO fact_activity (fact_id, client_id, action, from_sid, to_sid, detail,
                                          actor_tid, actor_name, methodology_version)
                VALUES (?,?,?,?,?,?,?,?,?)""",
            (fact_id, client_id, action, from_sid, to_sid, detail or "",
             actor_tid, actor_name or "", get_methodology_version(conn)))
    except sqlite3.OperationalError:
        pass


def fact_activity_log(conn: sqlite3.Connection, client_id: str, limit: int = 500) -> List[dict]:
    """Сквозной журнал действий над карточками клиента (change-log для админки)."""
    return [dict(r) for r in conn.execute(
        """SELECT id, fact_id, action, from_sid, to_sid, detail, actor_tid, actor_name,
                  methodology_version, at
            FROM fact_activity WHERE client_id = ? ORDER BY at DESC, id DESC LIMIT ?""",
        (client_id, int(limit)))]


def activity_log_global(conn: sqlite3.Connection, *, client_id: Optional[str] = None,
                        actor_tid: Optional[int] = None, action: Optional[str] = None,
                        limit: int = 200) -> List[dict]:
    """Глобальный журнал действий (админка): по всем компаниям, с фильтрами
    компания/пользователь/действие. С выдержкой карточки (title/text) и именем компании."""
    where, params = [], []
    if client_id:
        where.append("a.client_id = ?"); params.append(client_id)
    if actor_tid is not None:
        where.append("a.actor_tid = ?"); params.append(actor_tid)
    if action:
        where.append("a.action = ?"); params.append(action)
    wsql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(int(limit))
    return [dict(r) for r in conn.execute(
        f"""SELECT a.id, a.fact_id, a.client_id, COALESCE(cl.name, a.client_id) AS client_name,
                   a.action, a.from_sid, a.to_sid, a.detail,
                   a.actor_tid, a.actor_name, a.methodology_version, a.at,
                   COALESCE(f.title, '') AS fact_title,
                   COALESCE(substr(f.text, 1, 160), '') AS fact_text
             FROM fact_activity a
             LEFT JOIN clients cl ON cl.id = a.client_id
             LEFT JOIN facts f ON f.id = a.fact_id
             {wsql}
            ORDER BY a.at DESC, a.id DESC LIMIT ?""", params)]


def user_activity_counts(conn: sqlite3.Connection) -> Dict[int, int]:
    """Сколько действий над карточками сделал каждый пользователь (по actor_tid)."""
    return {r["actor_tid"]: r["n"] for r in conn.execute(
        "SELECT actor_tid, COUNT(*) n FROM fact_activity WHERE actor_tid IS NOT NULL "
        "GROUP BY actor_tid") if r["actor_tid"] is not None}


def get_methodology_version(conn: sqlite3.Connection) -> int:
    """Текущая версия методологии (bump при правке описаний). Дефолт 1."""
    r = conn.execute("SELECT value FROM app_meta WHERE key='methodology_version'").fetchone()
    try:
        return int(r["value"]) if r else 1
    except (TypeError, ValueError):
        return 1


def bump_methodology_version(conn: sqlite3.Connection) -> int:
    """Инкремент версии методологии (правка описаний → факты «устаревают» → reclassify снова
    их предложит). Возвращает новую версию."""
    ver = get_methodology_version(conn) + 1
    conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('methodology_version', ?)",
                 (str(ver),))
    conn.commit()
    return ver


# слои 1-2 = история фаундера (личная/профессиональная); L3-8 = текущая компания.
_L12_SUBSECTIONS = {"1.1", "1.2", "1.3", "2.1", "2.2", "2.3"}


def clamp_about_company_to_l2(about_company: str, proposed_sid: Optional[str],
                              current_sid: str) -> Optional[str]:
    """Жёсткий гард: факт про ДРУГУЮ компанию (about_company задан) не должен опускаться ниже
    L2 (в L3-8 — только текущая компания). Если предложено L3+ — оставляем в L1-2: текущую
    ячейку, если она уже L1-2, иначе 2.1 (профессиональный путь)."""
    if not (about_company or "").strip():
        return proposed_sid
    if proposed_sid and proposed_sid in _L12_SUBSECTIONS:
        return proposed_sid
    return current_sid if current_sid in _L12_SUBSECTIONS else "2.1"


def fact_placement_history(conn: sqlite3.Connection, client_id: str,
                           limit: int = 500) -> List[dict]:
    """История переездов раскладки клиента (подмножество журнала — action='moved')."""
    return [dict(r) for r in conn.execute(
        """SELECT id, fact_id, from_sid, to_sid, detail AS method,
                  actor_name AS moved_by, actor_tid AS moved_by_tid, at
            FROM fact_activity WHERE client_id = ? AND action = 'moved'
            ORDER BY at DESC, id DESC LIMIT ?""",
        (client_id, int(limit)))]


# ---------- sources ----------

ONLINE_CHANNELS = {"online_research", "online_interview", "archival"}


def validate_rationale(flag: str, rationale: Optional[str]) -> str:
    """Return normalized rationale or raise ValueError on missing red rationale.

    Rules:
      * red   → non-empty rationale required (1-2 sentences explaining the concern).
      * grey  → rationale optional (returned as-is, stripped).
      * green → rationale silently dropped (green facts don't carry rationale).
    """
    text = (rationale or "").strip()
    if flag == FLAG_RED:
        if not text:
            raise ValueError(
                "red fact requires rationale explaining the concern"
            )
        return text
    if flag == FLAG_GREEN:
        return ""
    return text


def validate_provenance(channel: str, source_url: str, evidence_snippet: str,
                        source_title: str = "", flag: str = "green") -> None:
    """Raise ValueError if provenance rules are violated.

    Rule 3: grey flag → evidence_snippet is optional (gap marker doesn't need a quote),
    but source and URL rules still apply.
    """
    snippet_required = flag != "grey"
    if channel in ONLINE_CHANNELS:
        if not source_url.startswith(("http://", "https://")):
            raise ValueError(
                f"{channel} fact requires source_url starting with http(s)://"
            )
        if snippet_required and len(evidence_snippet.strip()) < 20:
            raise ValueError(
                f"{channel} fact requires evidence_snippet ≥20 chars (literal quote from source)"
            )
    elif channel == "offline_interview":
        if not source_title.strip():
            raise ValueError(
                "offline_interview fact requires source_title "
                "(e.g. 'Interview with X 2026-05-12')"
            )


def add_source(conn: sqlite3.Connection, channel: str, title: str = "",
               url: str = "", notes: str = "",
               archive_url: str = "", publisher: str = "", author: str = "") -> int:
    if channel not in ALL_CHANNELS:
        raise ValueError(f"unknown channel {channel}")
    cur = conn.execute(
        """INSERT INTO sources (channel, title, url, notes, archive_url, publisher, author)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (channel, title, url, notes, archive_url or None, publisher, author),
    )
    conn.commit()
    return cur.lastrowid


# ---------- facts ----------

def add_fact(conn: sqlite3.Connection, *, client_id: str, subsection_id: str,
             text: str, flag: str, source_id: Optional[int] = None,
             confidence: float = 1.0, valid_until: Optional[str] = None,
             evidence_snippet: str = "", rationale: Optional[str] = None,
             created_by: Optional[str] = None, must_have: bool = False,
             created_by_tid: Optional[int] = None, state: str = "active") -> int:
    if flag not in (FLAG_GREEN, FLAG_RED, FLAG_GREY):
        raise ValueError(f"bad flag {flag}")
    rationale = validate_rationale(flag, rationale)
    # methodological guard: warn if source channel can't really fill this layer
    layer_id = int(subsection_id.split(".")[0])
    if source_id is not None:
        ch = conn.execute("SELECT channel FROM sources WHERE id=?", (source_id,)).fetchone()
        if ch and not channel_can_fill(ch["channel"], layer_id):
            conn.execute(
                "UPDATE sources SET notes = COALESCE(notes,'') || ? WHERE id=?",
                (f"\n[warn] channel {ch['channel']} not primary for layer {layer_id}", source_id),
            )

    cell_id = get_or_create_cell(conn, client_id, subsection_id)
    cur = conn.execute(
        """INSERT INTO facts (cell_id, text, flag, source_id, confidence, valid_until,
                              evidence_snippet, rationale, created_by, must_have, must_have_by,
                              created_by_tid, state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cell_id, text, flag, source_id, confidence, valid_until,
         evidence_snippet, rationale, created_by, 1 if must_have else 0,
         "client" if must_have else "", created_by_tid, state),
    )
    fact_id = cur.lastrowid
    # сквозной журнал: создание логируем ЦЕНТРАЛЬНО (покрывает и ручной ввод, и все
    # ingest-пути — LLM report / YouTube / audio / от клиента). Актор — из created_by.
    record_activity(conn, fact_id, client_id, "created", actor_name=created_by or "",
                    actor_tid=created_by_tid, to_sid=subsection_id, detail=state)
    conn.commit()

    # авто-закрытие work-item только для реально попавшего в матрицу факта (active),
    # не для черновика (review) — черновик работу ещё не закрывает.
    if flag == FLAG_GREEN and state == "active":
        from .workitems import auto_close_on_green_fact
        auto_close_on_green_fact(conn, client_id, subsection_id, fact_id)

    return fact_id


def facts_for_cell(conn: sqlite3.Connection, client_id: str,
                   subsection_id: str, *, include_rejected: bool = False) -> List[sqlite3.Row]:
    state_clause = "" if include_rejected else " AND f.state != 'rejected'"
    return list(conn.execute(
        """SELECT f.id, f.cell_id, f.text, f.title, f.flag, f.source_id, f.confidence,
                  f.captured_at, f.valid_until, f.evidence_snippet,
                  f.ingest_audit_id, f.rationale, f.created_by, f.created_by_tid,
                  f.approved_by, f.approved_by_tid, f.approved_at, f.merged_by,
                  f.snippet_start_sec,
                  f.verification, f.verification_note, f.entity, f.state,
                  f.speaker_entity_id, se.name AS speaker_name, f.must_have, f.must_have_by, f.merged_into,
                  f.about_company,
                  (SELECT COUNT(*) FROM fact_sources fs WHERE fs.fact_id=f.id) AS extra_sources,
                  s.channel AS source_channel, s.title AS source_title,
                  COALESCE(NULLIF(f.source_url, ''), s.url) AS source_url,
                  s.archive_url AS source_archive_url,
                  s.publisher AS source_publisher,
                  ia.ingest_kind AS ingest_kind,
                  ia.source_artifact AS ingest_artifact
            FROM facts f
            JOIN cells c ON c.id = f.cell_id
            LEFT JOIN sources s ON s.id = f.source_id
            LEFT JOIN ingest_audit ia ON ia.id = f.ingest_audit_id
            LEFT JOIN entities se ON se.id = f.speaker_entity_id
            WHERE c.client_id=? AND c.subsection_id=?""" + state_clause + """
            ORDER BY (f.sort_order IS NULL), f.sort_order, f.captured_at DESC""",
        (client_id, subsection_id),
    ))


def reorder_facts(conn: sqlite3.Connection, client_id: str, subsection_id: str,
                  ordered_ids: List[int]) -> int:
    """Присвоить ручной порядок карточкам ячейки: sort_order = позиция в списке.
    Принимаются только факты, реально лежащие в этой ячейке (чужие игнорируются)."""
    valid = {r["id"] for r in conn.execute(
        """SELECT f.id FROM facts f JOIN cells c ON c.id=f.cell_id
            WHERE c.client_id=? AND c.subsection_id=?""", (client_id, subsection_id))}
    n = 0
    for pos, fid in enumerate(ordered_ids):
        if fid in valid:
            conn.execute("UPDATE facts SET sort_order=? WHERE id=?", (pos, fid))
            n += 1
    conn.commit()
    return n


def must_have_facts(conn: sqlite3.Connection, client_id: str) -> List[dict]:
    """All client-provided must-have (blue) facts, ordered by layer→subsection→time.
    Used to export a numbered list for client sign-off of exact wording."""
    out: List[dict] = []
    for layer in LAYERS:
        for sub in layer.subsections:
            for r in facts_for_cell(conn, client_id, sub.id):
                if not r["must_have"]:
                    continue
                out.append({
                    "subsection_id": sub.id,
                    "subsection_name": sub.name,
                    "text": r["text"],
                    "flag": r["flag"],
                    "must_have_by": (r["must_have_by"] if "must_have_by" in r.keys() else "") or "client",
                })
    return out


def get_fact(conn: sqlite3.Connection, fact_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        """SELECT f.id, f.cell_id, f.text, f.title, f.flag, f.source_id, f.confidence,
                  f.captured_at, f.valid_until, f.evidence_snippet,
                  f.ingest_audit_id, f.rationale, f.created_by, f.created_by_tid,
                  f.approved_by, f.approved_by_tid, f.approved_at, f.merged_by,
                  f.snippet_start_sec,
                  f.verification, f.verification_note, f.entity, f.state,
                  f.speaker_entity_id, se.name AS speaker_name, f.must_have, f.must_have_by, f.merged_into,
                  f.about_company,
                  (SELECT COUNT(*) FROM fact_sources fs WHERE fs.fact_id=f.id) AS extra_sources,
                  s.channel AS source_channel, s.title AS source_title,
                  COALESCE(NULLIF(f.source_url, ''), s.url) AS source_url,
                  s.archive_url AS source_archive_url,
                  s.publisher AS source_publisher,
                  ia.ingest_kind AS ingest_kind,
                  ia.source_artifact AS ingest_artifact,
                  c.client_id, c.subsection_id
            FROM facts f
            JOIN cells c ON c.id = f.cell_id
            LEFT JOIN sources s ON s.id = f.source_id
            LEFT JOIN ingest_audit ia ON ia.id = f.ingest_audit_id
            LEFT JOIN entities se ON se.id = f.speaker_entity_id
            WHERE f.id=?""",
        (fact_id,),
    ).fetchone()


def set_fact_verification(conn: sqlite3.Connection, fact_id: int, *,
                          verification: str, note: str = "", entity: str = "",
                          sources: Optional[list] = None) -> None:
    """Set the verifier verdict on a fact (orthogonal to flag). Does not change
    lifecycle state — rejecting is a separate, human-confirmed step."""
    import json as _json
    if verification not in ("unverified", "verified", "suspect", "refuted"):
        raise ValueError(f"bad verification {verification}")
    conn.execute(
        """UPDATE facts SET verification=?, verification_note=?, entity=?,
                            verification_sources=?, verification_at=CURRENT_TIMESTAMP
            WHERE id=?""",
        (verification, note or "", entity or "", _json.dumps(sources or []), fact_id),
    )
    conn.commit()


def set_fact_title(conn: sqlite3.Connection, fact_id: int, title: str) -> None:
    """Set the short 2-3 word card title (analyst-editable)."""
    conn.execute("UPDATE facts SET title=? WHERE id=?", ((title or "").strip()[:80], fact_id))
    conn.commit()


def set_fact_must_have(conn: sqlite3.Connection, fact_id: int,
                       source: str = "client") -> None:
    """Set the must-have origin: 'client' (blue — mandatory in briefs), 'expert'
    (purple — flagged important) or '' (none). must_have stays the boolean overlay."""
    if source not in ("", "client", "expert"):
        raise ValueError(f"bad must-have source {source!r}")
    conn.execute("UPDATE facts SET must_have=?, must_have_by=? WHERE id=?",
                 (1 if source else 0, source, fact_id))
    conn.commit()


def set_fact_speaker(conn: sqlite3.Connection, fact_id: int, entity_id: Optional[int]) -> None:
    """Attribute a fact to a specific person (entities row, normally kind='founder').
    entity_id=None clears the attribution."""
    conn.execute("UPDATE facts SET speaker_entity_id=? WHERE id=?", (entity_id, fact_id))
    conn.commit()


def set_fact_about_company(conn: sqlite3.Connection, fact_id: int, about_company: str) -> None:
    """Тег «факт про другую компанию» (характеризует спикера, но не про текущего клиента —
    напр. Вайзер про GetTaxi). Метаданные, не текст факта → UPDATE допустим (инвариант #5)."""
    conn.execute("UPDATE facts SET about_company=? WHERE id=?", ((about_company or "").strip(), fact_id))
    conn.commit()


def attribute_fact(conn: sqlite3.Connection, fact_id: int, entity_id: Optional[int],
                   new_text: str) -> int:
    """Replace a fact's generic-speaker wording ("Фаундер считает …") with a concrete
    name. Immutability: instead of editing text in place, create a NEW fact carrying
    new_text + speaker_entity_id, fold the original's source onto it, and reject the
    original. Returns the new fact id."""
    text = (new_text or "").strip()
    old = get_fact(conn, fact_id)
    if old is None:
        raise ValueError(f"fact {fact_id} not found")
    if not text or text == (old["text"] or "").strip():
        # nothing to rewrite; just (re)attach the speaker
        set_fact_speaker(conn, fact_id, entity_id)
        return fact_id
    cur = conn.execute(
        """INSERT INTO facts (cell_id, text, flag, source_id, confidence, valid_until,
                              evidence_snippet, rationale, created_by, must_have, speaker_entity_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (old["cell_id"], text, old["flag"], old["source_id"], old["confidence"],
         old["valid_until"], old["evidence_snippet"], old["rationale"],
         "attribute", old["must_have"], entity_id),
    )
    new_id = cur.lastrowid
    # new fact carries the original's source_id; don't also fold it as corroboration
    conn.execute(
        """UPDATE facts SET state='rejected', merged_into=?,
                            verification_note=? WHERE id=?""",
        (new_id, f"переименован спикер → #{new_id}", fact_id))
    conn.commit()
    return new_id


def fact_client_id(conn: sqlite3.Connection, fact_id: int) -> Optional[str]:
    """Компания, которой принадлежит факт (через ячейку) — для проверки прав."""
    r = conn.execute(
        "SELECT c.client_id FROM facts f JOIN cells c ON c.id = f.cell_id WHERE f.id=?",
        (fact_id,)).fetchone()
    return r["client_id"] if r else None


def approve_fact(conn: sqlite3.Connection, fact_id: int, *, approved_by: str = "",
                 approved_by_tid: Optional[int] = None) -> None:
    """Одобрение владельцем: черновик (review) → активен, фиксируем кто/когда.
    Верификацию (фактчекинг) НЕ трогаем — это отдельная ось."""
    conn.execute(
        """UPDATE facts SET state='active', approved_by=?, approved_by_tid=?,
                            approved_at=CURRENT_TIMESTAMP WHERE id=?""",
        (approved_by or "", approved_by_tid, fact_id))
    conn.commit()


def set_fact_state(conn: sqlite3.Connection, fact_id: int, state: str) -> None:
    """Lifecycle: 'active' (in matrix + generators), 'review' (quarantine — held
    at the ingest gate, NOT in the matrix, awaiting human promote/reject), or
    'rejected' (kept for audit, excluded from everything). All restorable."""
    if state not in ("active", "review", "rejected"):
        raise ValueError(f"bad state {state}")
    conn.execute("UPDATE facts SET state=? WHERE id=?", (state, fact_id))
    conn.commit()


# ---------- identity anchor: entities + entity_facts (fact-trust phase 1) ----------

import json as _json_ent


def entities_for_client(conn: sqlite3.Connection, client_id: str) -> List[dict]:
    """All identity entities (company / founders / decoys) with their bare facts."""
    ents = conn.execute(
        """SELECT id, kind, name, role, canonical_url, links, note, confirmed, sort_order
            FROM entities WHERE client_id=? ORDER BY
            CASE kind WHEN 'company' THEN 0 WHEN 'founder' THEN 1 ELSE 2 END,
            sort_order, id""",
        (client_id,),
    ).fetchall()
    out: List[dict] = []
    for e in ents:
        d = dict(e)
        try:
            d["links"] = _json_ent.loads(d.get("links") or "{}")
        except Exception:
            d["links"] = {}
        d["confirmed"] = bool(d["confirmed"])
        d["facts"] = [dict(r) for r in conn.execute(
            """SELECT id, key, value, source_url, source_title, as_of, verified, sort_order,
                      COALESCE(section, '') AS section
                FROM entity_facts WHERE entity_id=? ORDER BY sort_order, id""",
            (e["id"],),
        )]
        for ef in d["facts"]:
            ef["verified"] = bool(ef["verified"])
            # as_of column has DATE (NUMERIC) affinity — SQLite coerces a bare
            # year like "2024" to int 2024; normalize back to str for the API
            ef["as_of"] = None if ef["as_of"] is None else str(ef["as_of"])
        out.append(d)
    return out


def add_entity(conn: sqlite3.Connection, *, client_id: str, kind: str, name: str,
               role: str = "", canonical_url: str = "", links: Optional[dict] = None,
               note: str = "", confirmed: bool = False, sort_order: int = 0) -> int:
    if kind not in ("company", "founder", "decoy"):
        raise ValueError(f"bad kind {kind}")
    cur = conn.execute(
        """INSERT INTO entities (client_id, kind, name, role, canonical_url, links,
                                 note, confirmed, sort_order)
            VALUES (?,?,?,?,?,?,?,?,?)""",
        (client_id, kind, name, role, canonical_url, _json_ent.dumps(links or {}),
         note, 1 if confirmed else 0, sort_order),
    )
    conn.commit()
    return cur.lastrowid


def update_entity(conn: sqlite3.Connection, entity_id: int, **fields) -> None:
    cols = {"kind", "name", "role", "canonical_url", "note", "confirmed", "sort_order", "links"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in cols or v is None:
            continue
        if k == "links":
            v = _json_ent.dumps(v)
        if k == "confirmed":
            v = 1 if v else 0
        sets.append(f"{k}=?"); params.append(v)
    if not sets:
        return
    params.append(entity_id)
    conn.execute(f"UPDATE entities SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()


def delete_entity(conn: sqlite3.Connection, entity_id: int) -> None:
    conn.execute("DELETE FROM entities WHERE id=?", (entity_id,))
    conn.commit()


def list_mentioned_companies(conn: sqlite3.Connection, client_id: str) -> List[dict]:
    """Внешние компании, упомянутые под клиентом (не клиенты сами по себе)."""
    return [dict(r) for r in conn.execute(
        """SELECT id, client_id, name, logo, note, sort_order FROM mentioned_companies
            WHERE client_id=? ORDER BY sort_order, name COLLATE NOCASE""", (client_id,))]


def add_mentioned_company(conn: sqlite3.Connection, client_id: str, name: str,
                          logo: str = "", note: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO mentioned_companies (client_id, name, logo, note) VALUES (?,?,?,?)",
        (client_id, (name or "").strip(), (logo or "").strip(), (note or "").strip()))
    conn.commit()
    return cur.lastrowid


def update_mentioned_company(conn: sqlite3.Connection, mc_id: int, **fields) -> None:
    cols = {"name", "logo", "note", "sort_order"}
    sets, params = [], []
    for k, v in fields.items():
        if k in cols and v is not None:
            sets.append(f"{k}=?"); params.append(v.strip() if isinstance(v, str) else v)
    if not sets:
        return
    params.append(mc_id)
    conn.execute(f"UPDATE mentioned_companies SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()


def delete_mentioned_company(conn: sqlite3.Connection, mc_id: int) -> None:
    conn.execute("DELETE FROM mentioned_companies WHERE id=?", (mc_id,))
    conn.commit()


def founders_by_name(conn: sqlite3.Connection, name: str,
                     exclude_client: Optional[str] = None) -> List[dict]:
    """Тот же человек в ДРУГИХ компаниях: фаундер-сущности с совпадающим именем
    (регистро-/пробело-независимо) у других клиентов — чтобы предложить влить профиль."""
    key = (name or "").strip().lower()
    if not key:
        return []
    rows = conn.execute(
        """SELECT e.id, e.client_id, c.name AS client_name, e.name, e.role,
                  e.canonical_url, e.links, e.note
            FROM entities e JOIN clients c ON c.id = e.client_id
            WHERE e.kind='founder' AND lower(trim(e.name))=?
              AND (? IS NULL OR e.client_id != ?)
            ORDER BY c.name""",
        (key, exclude_client, exclude_client)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["links"] = _json_ent.loads(d.get("links") or "{}")
        except Exception:
            d["links"] = {}
        out.append(d)
    return out


def import_founder_profile(conn: sqlite3.Connection, target_id: int, source_id: int) -> dict:
    """Влить профиль фаундера из source в target: links объединяются (существующие в
    target не перетираются), role/canonical_url/note заполняются, если у target пусто.
    Возвращает обновлённую сущность target."""
    tgt = conn.execute("SELECT * FROM entities WHERE id=? AND kind='founder'", (target_id,)).fetchone()
    src = conn.execute("SELECT * FROM entities WHERE id=? AND kind='founder'", (source_id,)).fetchone()
    if tgt is None or src is None:
        raise ValueError("founder entity not found")
    try:
        t_links = _json_ent.loads(tgt["links"] or "{}")
    except Exception:
        t_links = {}
    try:
        s_links = _json_ent.loads(src["links"] or "{}")
    except Exception:
        s_links = {}
    merged_links = {**s_links, **t_links}   # target выигрывает при конфликте ключей
    fields = {"links": merged_links}
    for col in ("role", "canonical_url", "note"):
        if not (tgt[col] or "").strip() and (src[col] or "").strip():
            fields[col] = src[col]
    update_entity(conn, target_id, **fields)
    return dict(conn.execute("SELECT id, client_id, kind, name, role, canonical_url, links, note, confirmed FROM entities WHERE id=?", (target_id,)).fetchone())


def add_entity_fact(conn: sqlite3.Connection, *, entity_id: int, key: str = "",
                    value: str = "", source_url: str = "", source_title: str = "",
                    as_of: Optional[str] = None, verified: bool = False,
                    sort_order: int = 0, section: str = "") -> int:
    cur = conn.execute(
        """INSERT INTO entity_facts (entity_id, key, value, source_url, source_title,
                                     as_of, verified, sort_order, section)
            VALUES (?,?,?,?,?,?,?,?,?)""",
        (entity_id, key, value, source_url, source_title, as_of,
         1 if verified else 0, sort_order, section),
    )
    conn.commit()
    return cur.lastrowid


def delete_entity_fact(conn: sqlite3.Connection, fact_id: int) -> None:
    conn.execute("DELETE FROM entity_facts WHERE id=?", (fact_id,))
    conn.commit()


def entity_anchor(conn: sqlite3.Connection, client_id: str) -> dict:
    """The identity anchor for verification: {company, founders[], decoys[]}.
    Prefers confirmed entities; falls back to drafts if nothing confirmed."""
    rows = conn.execute(
        "SELECT kind, name, confirmed FROM entities WHERE client_id=? ORDER BY sort_order, id",
        (client_id,),
    ).fetchall()
    any_confirmed = any(r["confirmed"] for r in rows)
    use = [r for r in rows if (r["confirmed"] or not any_confirmed)]
    company = next((r["name"] for r in use if r["kind"] == "company"), "")
    founders = [r["name"] for r in use if r["kind"] == "founder"]
    decoys = [r["name"] for r in use if r["kind"] == "decoy"]
    return {"company": company, "founders": founders, "decoys": decoys}


def fact_corroboration(conn: sqlite3.Connection, fact_id: int) -> int:
    """How many independent sources back a fact: 1 (primary) + folded-in sources."""
    n = conn.execute("SELECT COUNT(*) FROM fact_sources WHERE fact_id=?", (fact_id,)).fetchone()[0]
    return 1 + int(n)


def _fold_source(conn: sqlite3.Connection, into_id: int, from_fact_id: int) -> None:
    row = conn.execute(
        """SELECT f.source_id AS source_id, s.channel AS channel, s.title AS title,
                  COALESCE(NULLIF(f.source_url, ''), s.url) AS url
            FROM facts f LEFT JOIN sources s ON s.id = f.source_id WHERE f.id=?""",
        (from_fact_id,)).fetchone()
    if row:
        conn.execute(
            "INSERT INTO fact_sources (fact_id, source_id, channel, title, url) VALUES (?,?,?,?,?)",
            (into_id, row["source_id"], row["channel"] or "", row["title"] or "", row["url"] or ""))


def merge_facts(conn: sqlite3.Connection, keep_id: int, merge_ids: List[int],
                merged_text: Optional[str] = None, merged_by: Optional[str] = None) -> int:
    """Merge duplicate facts. Two modes:

    - Default (merged_text=None): fold each duplicate's source into `keep_id`'s
      corroboration and soft-reject the duplicates. keep's text is unchanged.
      Returns keep's id (corroboration grows).

    - Curated text (merged_text given): the analyst supplied a single synthesized
      wording. Honouring fact immutability (no UPDATE on text), this creates a NEW
      fact carrying merged_text in keep's cell, folds the sources of ALL originals
      (keep + merges) onto it, and soft-rejects every original (incl. the old keep).
      must_have/speaker carry over if any original had them. Returns the NEW fact id.
    """
    merge_ids = [m for m in merge_ids if m != keep_id]
    text = (merged_text or "").strip()
    keep = get_fact(conn, keep_id)
    if keep is None:
        raise ValueError(f"keep fact {keep_id} not found")

    if not text or text == (keep["text"] or "").strip():
        # NB: don't fold the duplicates' sources into keep — the joint card just LINKS
        # to the hidden originals (merged_into); each original keeps its own source.
        for mid in merge_ids:
            conn.execute(
                """UPDATE facts SET state='rejected', merged_into=?,
                                    verification_note=? WHERE id=?""",
                (keep_id, f"дубль — слит в #{keep_id}", mid))
        if merged_by:
            conn.execute("UPDATE facts SET merged_by=? WHERE id=?", (merged_by, keep_id))
        conn.commit()
        return keep_id

    # curated merged text → new immutable fact, all originals rejected
    all_ids = [keep_id] + merge_ids
    must = any((get_fact(conn, i) or {})["must_have"] for i in all_ids)
    speaker = next((get_fact(conn, i)["speaker_entity_id"] for i in all_ids
                    if get_fact(conn, i)["speaker_entity_id"] is not None), None)
    cur = conn.execute(
        """INSERT INTO facts (cell_id, text, flag, source_id, confidence, valid_until,
                              evidence_snippet, rationale, created_by, must_have, speaker_entity_id,
                              merged_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (keep["cell_id"], text, keep["flag"], keep["source_id"], keep["confidence"],
         keep["valid_until"], keep["evidence_snippet"], keep["rationale"],
         "merge", 1 if must else 0, speaker, merged_by or ""),
    )
    new_id = cur.lastrowid
    # don't fold sources — the joint references the hidden originals; sources live there
    for oid in all_ids:
        conn.execute(
            """UPDATE facts SET state='rejected', merged_into=?,
                                verification_note=? WHERE id=?""",
            (new_id, f"слит (с правкой текста) в #{new_id}", oid))
    conn.commit()
    return new_id


def fact_sources(conn: sqlite3.Connection, fact_id: int) -> List[dict]:
    """All sources backing a fact: primary (from facts/sources) + folded-in extras."""
    out: List[dict] = []
    primary = conn.execute(
        """SELECT s.channel AS channel, s.title AS title,
                  COALESCE(NULLIF(f.source_url, ''), s.url) AS url
            FROM facts f LEFT JOIN sources s ON s.id = f.source_id WHERE f.id=?""",
        (fact_id,)).fetchone()
    if primary:
        out.append({"channel": primary["channel"] or "", "title": primary["title"] or "",
                    "url": primary["url"] or "", "primary": True})
    for r in conn.execute("SELECT channel, title, url FROM fact_sources WHERE fact_id=? ORDER BY id", (fact_id,)):
        out.append({"channel": r["channel"], "title": r["title"], "url": r["url"], "primary": False})
    return out


def search_facts(conn: sqlite3.Connection, query: str,
                 client_id: Optional[str] = None, limit: int = 60) -> List[dict]:
    """Full-text-ish поиск по фактам (текст + заголовок). Регистронезависимо для
    кириллицы через pylower (SQLite LIKE/lower — только ASCII). Скрытые дубли
    (state='rejected') не показываем. client_id=None → по всем компаниям."""
    q = (query or "").strip()
    if len(q) < 2:
        return []
    conn.create_function("pylower", 1, lambda s: (s or "").lower())
    esc = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{esc}%"
    params: List = [like, like]
    where_client = ""
    if client_id:
        where_client = "AND ce.client_id = ? "
        params.append(client_id)
    params.append(int(limit))
    rows = conn.execute(
        f"""SELECT f.id AS fact_id, cl.id AS client_id, cl.name AS client_name,
                   ce.subsection_id AS subsection_id, s.name AS subsection_name,
                   COALESCE(f.title, '') AS title, f.text AS text,
                   f.flag AS flag, f.state AS state
             FROM facts f
             JOIN cells ce ON f.cell_id = ce.id
             JOIN clients cl ON ce.client_id = cl.id
             JOIN subsections s ON ce.subsection_id = s.id
            WHERE f.state != 'rejected'
              AND (pylower(f.text) LIKE ? ESCAPE '\\'
                   OR pylower(COALESCE(f.title, '')) LIKE ? ESCAPE '\\')
              {where_client}
            ORDER BY cl.name, ce.subsection_id, f.id
            LIMIT ?""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def review_facts(conn: sqlite3.Connection, client_id: str) -> List[dict]:
    """Facts held in the ingest-gate quarantine (state='review') — for the
    triage screen to promote (→ active) or reject."""
    rows = conn.execute(
        """SELECT f.id, c.subsection_id AS subsection_id, f.text, f.flag,
                  f.verification, f.verification_note, f.entity
            FROM facts f JOIN cells c ON c.id = f.cell_id
            WHERE c.client_id=? AND f.state='review'
            ORDER BY f.id DESC""",
        (client_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def bootstrap_entities(conn: sqlite3.Connection, client_id: str, canonical: dict) -> List[int]:
    """Create draft identity entities from an audit's proposed anchor
    {company, founders[], decoys[]}. No-op if the client already has entities."""
    if conn.execute("SELECT 1 FROM entities WHERE client_id=? LIMIT 1", (client_id,)).fetchone():
        return []
    created: List[int] = []
    company = (canonical.get("company") or "").strip()
    if company:
        created.append(add_entity(conn, client_id=client_id, kind="company", name=company))
    for i, f in enumerate(canonical.get("founders") or []):
        name = (f or "").strip()
        if name:
            created.append(add_entity(conn, client_id=client_id, kind="founder",
                                      name=name, sort_order=i))
    for i, d in enumerate(canonical.get("decoys") or []):
        name = (d or "").strip()
        if name:
            created.append(add_entity(conn, client_id=client_id, kind="decoy", name=name,
                                      note="другой человек/компания — не путать", sort_order=i))
    return created


def update_fact(conn: sqlite3.Connection, fact_id: int, *,
                text: Optional[str] = None, flag: Optional[str] = None,
                confidence: Optional[float] = None,
                rationale: Optional[str] = None) -> None:
    sets, params = [], []
    if text is not None:
        sets.append("text=?"); params.append(text)
    if flag is not None:
        if flag not in (FLAG_GREEN, FLAG_RED, FLAG_GREY):
            raise ValueError(f"bad flag {flag}")
        sets.append("flag=?"); params.append(flag)
    if confidence is not None:
        sets.append("confidence=?"); params.append(confidence)

    # Re-validate (flag, rationale) only when either is being changed.
    if flag is not None or rationale is not None:
        row = conn.execute(
            "SELECT flag, rationale FROM facts WHERE id=?", (fact_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"fact {fact_id} not found")
        effective_flag = flag if flag is not None else row["flag"]
        effective_rationale = rationale if rationale is not None else (row["rationale"] or "")
        normalized = validate_rationale(effective_flag, effective_rationale)
        if rationale is not None or normalized != (row["rationale"] or ""):
            sets.append("rationale=?"); params.append(normalized)

    if not sets:
        return
    params.append(fact_id)
    conn.execute(f"UPDATE facts SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()


def delete_fact(conn: sqlite3.Connection, fact_id: int) -> None:
    conn.execute("DELETE FROM facts WHERE id=?", (fact_id,))
    conn.commit()


def list_sources(conn: sqlite3.Connection, channel: Optional[str] = None) -> List[sqlite3.Row]:
    if channel:
        return list(conn.execute(
            "SELECT * FROM sources WHERE channel=? ORDER BY captured_at DESC",
            (channel,),
        ))
    return list(conn.execute("SELECT * FROM sources ORDER BY captured_at DESC"))


def get_artifact(conn: sqlite3.Connection, artifact_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()


def list_artifacts(conn: sqlite3.Connection, *, client_id: str,
                   cycle: Optional[str] = None, limit: int = 50) -> List[sqlite3.Row]:
    if cycle:
        return list(conn.execute(
            """SELECT id, client_id, cycle, title, created_at FROM artifacts
                WHERE client_id=? AND cycle=? ORDER BY created_at DESC LIMIT ?""",
            (client_id, cycle, limit),
        ))
    return list(conn.execute(
        """SELECT id, client_id, cycle, title, created_at FROM artifacts
            WHERE client_id=? ORDER BY created_at DESC LIMIT ?""",
        (client_id, limit),
    ))


# ---------- matrix views ----------

def cell_summary(conn: sqlite3.Connection, client_id: str) -> List[Dict[str, Any]]:
    """Return one row per subsection with green/red/grey counts, last update,
    and the distinct source channels feeding the cell (for matrix infographics)."""
    rows = conn.execute("""
        SELECT s.id AS subsection_id, s.layer_id, s.name AS subsection_name,
               L.name AS layer_name, L.intimacy,
               SUM(CASE WHEN f.flag='green' THEN 1 ELSE 0 END) AS n_green,
               SUM(CASE WHEN f.flag='red'   THEN 1 ELSE 0 END) AS n_red,
               SUM(CASE WHEN f.flag='grey'  THEN 1 ELSE 0 END) AS n_grey,
               SUM(CASE WHEN f.must_have=1  THEN 1 ELSE 0 END) AS n_must,
               SUM(CASE WHEN f.must_have=1 AND f.must_have_by='expert' THEN 1 ELSE 0 END) AS n_must_expert,
               SUM(CASE WHEN f.must_have=1 AND f.must_have_by<>'expert' THEN 1 ELSE 0 END) AS n_must_client,
               MAX(f.captured_at) AS last_update,
               GROUP_CONCAT(DISTINCT src.channel) AS channels
        FROM subsections s
        JOIN layers L ON L.id = s.layer_id
        LEFT JOIN cells c ON c.subsection_id = s.id AND c.client_id = ?
        LEFT JOIN facts f ON f.cell_id = c.id AND f.state = 'active'
        LEFT JOIN sources src ON src.id = f.source_id
        GROUP BY s.id
        ORDER BY L.intimacy, s.sort_order
    """, (client_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        raw = d.pop("channels", None)
        d["channels"] = sorted({c for c in (raw.split(",") if raw else []) if c})
        out.append(d)
    return out


def portfolio_summary(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """One row per client with covered/total subsection counts — for the
    sidebar portfolio health bars. `covered` = subsections with >=1 green fact."""
    total = conn.execute("SELECT COUNT(*) FROM subsections").fetchone()[0]
    rows = conn.execute("""
        SELECT cl.id, cl.name, cl.sector,
               COUNT(DISTINCT CASE WHEN f.flag='green' THEN c.subsection_id END) AS covered
        FROM clients cl
        LEFT JOIN cells c ON c.client_id = cl.id
        LEFT JOIN facts f ON f.cell_id = c.id AND f.state = 'active'
        WHERE COALESCE(cl.hidden, 0) = 0
        GROUP BY cl.id
        ORDER BY cl.name
    """).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["total"] = total
        d["covered"] = d.get("covered") or 0
        out.append(d)
    return out


def my_client_ids(conn: sqlite3.Connection, telegram_id: int) -> set:
    """Client ids the given user has marked as 'mine'."""
    return {r[0] for r in conn.execute(
        "SELECT client_id FROM client_members WHERE telegram_id=?", (telegram_id,))}


def set_client_member(conn: sqlite3.Connection, client_id: str, telegram_id: int, on: bool) -> None:
    if on:
        conn.execute(
            "INSERT OR IGNORE INTO client_members(client_id, telegram_id) VALUES(?, ?)",
            (client_id, telegram_id))
    else:
        conn.execute(
            "DELETE FROM client_members WHERE client_id=? AND telegram_id=?",
            (client_id, telegram_id))
    conn.commit()


def empty_cells(conn: sqlite3.Connection, client_id: str) -> List[Dict[str, Any]]:
    """Subsections with NO facts at all (no green, no red, no grey).
    These are 'untouched' cells — the channel hasn't been run yet."""
    return [r for r in cell_summary(conn, client_id)
            if (r["n_green"] or 0) == 0
            and (r["n_red"] or 0) == 0
            and (r["n_grey"] or 0) == 0]


def cells_with_known_gaps(conn: sqlite3.Connection, client_id: str) -> List[Dict[str, Any]]:
    """Subsections that have explicit grey-flagged facts (= 'we know we don't know').
    These are the methodologically interesting punch-list items."""
    return [r for r in cell_summary(conn, client_id) if (r["n_grey"] or 0) > 0]


def thinly_covered_cells(conn: sqlite3.Connection, client_id: str,
                         min_green: int = 2) -> List[Dict[str, Any]]:
    """Subsections with fewer than `min_green` green-flagged facts.
    Useful for prioritising what to deepen before quarterly."""
    return [r for r in cell_summary(conn, client_id)
            if (r["n_green"] or 0) < min_green]


def grey_facts_for_cell(conn: sqlite3.Connection, client_id: str,
                        subsection_id: str) -> List[sqlite3.Row]:
    return [f for f in facts_for_cell(conn, client_id, subsection_id)
            if f["flag"] == "grey"]


def cell_dominant_flag(conn: sqlite3.Connection, client_id: str, subsection_id: str) -> str:
    """Roll up a cell's facts into a single flag for scorecard purposes."""
    facts = facts_for_cell(conn, client_id, subsection_id)
    has_red = any(f["flag"] == FLAG_RED for f in facts)
    has_green = any(f["flag"] == FLAG_GREEN for f in facts)
    if has_red and has_green:
        return "mixed"
    if has_red:
        return FLAG_RED
    if has_green:
        return FLAG_GREEN
    return FLAG_GREY


# ---------- plans + tracks ----------

def upsert_plan(conn: sqlite3.Connection, client_id: str, quarter: str,
                notes: str = "") -> int:
    row = conn.execute(
        "SELECT id FROM plans WHERE client_id=? AND quarter=?",
        (client_id, quarter),
    ).fetchone()
    if row:
        conn.execute("UPDATE plans SET notes=? WHERE id=?", (notes, row["id"]))
        conn.commit()
        return row["id"]
    cur = conn.execute(
        "INSERT INTO plans (client_id, quarter, notes) VALUES (?, ?, ?)",
        (client_id, quarter, notes),
    )
    conn.commit()
    return cur.lastrowid


def add_track(conn: sqlite3.Connection, *, plan_id: int, name: str, angle: str,
              target_layer_ids: List[int], target_subsection_ids: List[str],
              priority: int = 1) -> int:
    cur = conn.execute(
        """INSERT INTO narrative_tracks
            (plan_id, name, angle, target_layer_ids, target_subsection_ids, priority)
            VALUES (?, ?, ?, ?, ?, ?)""",
        (plan_id, name, angle,
         json.dumps(target_layer_ids), json.dumps(target_subsection_ids), priority),
    )
    conn.commit()
    return cur.lastrowid


def tracks_for_quarter(conn: sqlite3.Connection, client_id: str,
                       quarter: str) -> List[Dict[str, Any]]:
    rows = conn.execute("""
        SELECT t.* FROM narrative_tracks t
        JOIN plans p ON p.id = t.plan_id
        WHERE p.client_id=? AND p.quarter=?
        ORDER BY t.priority DESC, t.id
    """, (client_id, quarter)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["target_layer_ids"] = json.loads(d.get("target_layer_ids") or "[]")
        d["target_subsection_ids"] = json.loads(d.get("target_subsection_ids") or "[]")
        out.append(d)
    return out


# ---------- artifacts ----------

def save_artifact(conn: sqlite3.Connection, *, client_id: str, cycle: str,
                  title: str, body: str, meta: Optional[Dict[str, Any]] = None) -> int:
    cur = conn.execute(
        """INSERT INTO artifacts (client_id, cycle, title, body, meta)
            VALUES (?, ?, ?, ?, ?)""",
        (client_id, cycle, title, body, json.dumps(meta or {})),
    )
    conn.commit()
    return cur.lastrowid

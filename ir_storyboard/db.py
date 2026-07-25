"""SQLite connection + schema bootstrap."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "matrix.db"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open (and create if needed) a SQLite connection with FK enforcement."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _add_column_if_missing(conn: sqlite3.Connection, table: str,
                           column: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _backfill_merged_into(conn: sqlite3.Connection) -> None:
    """One-time: facts merged/renamed before the merged_into column existed were
    wrongly marked verification='refuted'. Recover the link from their note
    ("слит … в #N" / "переименован спикер → #N") and clear the false refuted."""
    import re
    rows = conn.execute(
        """SELECT id, verification_note FROM facts
            WHERE merged_into IS NULL AND verification='refuted'
              AND (verification_note LIKE '%слит%' OR verification_note LIKE '%переименован спикер%')"""
    ).fetchall()
    for r in rows:
        nums = re.findall(r"(\d+)", r[1] or "")
        if not nums:
            continue
        conn.execute(
            "UPDATE facts SET merged_into=?, verification='unverified' WHERE id=?",
            (int(nums[-1]), r[0]))
    if rows:
        conn.commit()


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist, then apply additive migrations."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    # additive migrations — safe to run on existing DBs
    _add_column_if_missing(conn, "clients", "founder_name", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "clients", "founder_handle", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "clients", "aliases", "TEXT DEFAULT '[]'")
    _add_column_if_missing(conn, "clients", "notes", "TEXT DEFAULT ''")
    # methodology: per-client narrative tone preset used by LLM extractors
    _add_column_if_missing(conn, "clients", "tone_preset", "TEXT NOT NULL DEFAULT 'business'")
    # methodology: backfill empty subsection descriptions from models.LAYERS
    # (only fills NULL/'' rows — expert edits are preserved)
    _backfill_subsection_descriptions(conn)
    # methodology: per-client additive note on top of the global description
    conn.execute("""
        CREATE TABLE IF NOT EXISTS client_subsection_notes (
            client_id      TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            subsection_id  TEXT NOT NULL REFERENCES subsections(id) ON DELETE CASCADE,
            note           TEXT NOT NULL DEFAULT '',
            updated_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (client_id, subsection_id)
        )
    """)
    # task-2: provenance fields
    _add_column_if_missing(conn, "facts", "evidence_snippet", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "sources", "accessed_at", "TIMESTAMP")
    _add_column_if_missing(conn, "sources", "content_hash", "TEXT")
    _add_column_if_missing(conn, "sources", "archive_url", "TEXT")
    _add_column_if_missing(conn, "sources", "publisher", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "sources", "author", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "sources", "published_at", "DATE")
    # task-5: collapse L1 from 4 subsections to 3 (merge 1.4 → 1.3)
    _migrate_collapse_1_4(conn)
    # llm-report: link facts to the ingest audit row they came from
    _add_column_if_missing(conn, "facts", "ingest_audit_id", "TEXT")
    # ручная сортировка карточек в ячейке (drag вверх/вниз); NULL = не трогали (по дате)
    _add_column_if_missing(conn, "facts", "sort_order", "INTEGER")
    # факт характеризует спикера, но говорит про ДРУГУЮ компанию (Вайзер про GetTaxi) — тег
    _add_column_if_missing(conn, "facts", "about_company", "TEXT DEFAULT ''")
    # раскладка по методологии: placement_locked=1 → ручной перенос экспертом, авто-реклассификация
    # его НЕ трогает; reclassified_at → когда факт в последний раз размещён прогоном методологии.
    _add_column_if_missing(conn, "facts", "placement_locked", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "facts", "reclassified_at", "TIMESTAMP")
    # история переездов раскладки (для будущего админ-интерфейса; в UI пока не показываем)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fact_placement_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_id      INTEGER NOT NULL,
            client_id    TEXT,
            from_sid     TEXT,
            to_sid       TEXT NOT NULL,
            method       TEXT NOT NULL,          -- 'manual' | 'reclassify'
            moved_by     TEXT NOT NULL DEFAULT '',
            moved_by_tid INTEGER,
            at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # llm-5: ingest_audit table for LLM Report Ingest provenance
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingest_audit (
            id              TEXT PRIMARY KEY,
            client_id       TEXT NOT NULL,
            ingest_kind     TEXT NOT NULL CHECK(ingest_kind IN ('llm_report', 'manual_seed', 'youtube', 'audio_file')),
            source_artifact TEXT NOT NULL,
            agent           TEXT,
            cite_format     TEXT,
            parsed_at       TIMESTAMP NOT NULL,
            facts_emitted   INTEGER NOT NULL DEFAULT 0,
            facts_committed INTEGER NOT NULL DEFAULT 0,
            greys_emitted   INTEGER NOT NULL DEFAULT 0,
            channel_warnings INTEGER NOT NULL DEFAULT 0,
            expert_email    TEXT NOT NULL DEFAULT '',
            confirmed_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            preview_json    TEXT NOT NULL DEFAULT '{}'
        )
    """)
    # youtube ingest: extend CHECK constraint to include 'youtube' on existing DBs
    _migrate_audit_add_youtube(conn)
    # audio ingest: extend CHECK constraint to include 'audio_file' on existing DBs
    _migrate_audit_add_audio_file(conn)
    # youtube ingest: add youtube-specific columns to ingest_audit
    _add_column_if_missing(conn, "ingest_audit", "video_id", "TEXT")
    _add_column_if_missing(conn, "ingest_audit", "transcriber", "TEXT")
    _add_column_if_missing(conn, "ingest_audit", "transcribe_cost_usd", "REAL")
    _add_column_if_missing(conn, "ingest_audit", "transcribe_duration_sec", "INTEGER")
    # Nullable "committed" marker. The legacy confirmed_at is NOT NULL DEFAULT
    # CURRENT_TIMESTAMP, so it's set even at preview time and can't express
    # "pending". committed_at is NULL until the analyst actually commits — this is
    # what makes a reopened uncommitted preview editable instead of read-only.
    _add_column_if_missing(conn, "ingest_audit", "committed_at", "TIMESTAMP")
    # youtube ingest: add source_url to facts for timestamp deep-links
    _add_column_if_missing(conn, "facts", "source_url", "TEXT DEFAULT ''")
    # audio ingest: snippet start timecode (seconds) for clickable audio sources
    _add_column_if_missing(conn, "facts", "snippet_start_sec", "REAL")
    # polish: rationale for red-flag concerns + multi-user placeholder
    _add_column_if_missing(conn, "facts", "rationale", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "facts", "created_by", "TEXT")
    _add_column_if_missing(conn, "clients", "created_by", "TEXT")
    # auth: per-user "my companies" membership (telegram_id ↔ client)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS client_members (
            client_id    TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            telegram_id  INTEGER NOT NULL,
            PRIMARY KEY (client_id, telegram_id)
        )
    """)

    # multi-user roles (права экспертов): known Telegram users (наполняется при
    # входе из сессии — источник имён для выбора владельца/исполнителя).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            tid        INTEGER PRIMARY KEY,
            name       TEXT NOT NULL DEFAULT '',
            username   TEXT NOT NULL DEFAULT '',
            first_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # у компании есть владелец данных (финализирует правки); скрытие вместо удаления
    _add_column_if_missing(conn, "clients", "owner_tid", "INTEGER")
    _add_column_if_missing(conn, "clients", "hidden", "INTEGER NOT NULL DEFAULT 0")
    # провенанс факта: кто внёс (tid к created_by-имени), кто/когда подтвердил,
    # автор слияния. Факт от контрибьютора едет в state='review' (черновик).
    _add_column_if_missing(conn, "facts", "created_by_tid", "INTEGER")
    _add_column_if_missing(conn, "facts", "approved_by", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "facts", "approved_by_tid", "INTEGER")
    _add_column_if_missing(conn, "facts", "approved_at", "TIMESTAMP")
    _add_column_if_missing(conn, "facts", "merged_by", "TEXT NOT NULL DEFAULT ''")
    # канбан: исполнитель как реальный юзер (assignee-имя остаётся для совместимости)
    _add_column_if_missing(conn, "work_items", "assignee_tid", "INTEGER")
    # brief composer: analyst-editable prompt templates for external-LLM materials
    conn.execute("""
        CREATE TABLE IF NOT EXISTS brief_templates (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            material_type TEXT NOT NULL DEFAULT '',
            body          TEXT NOT NULL DEFAULT '',
            created_by    TEXT,
            updated_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # fact-trust (phase 1): verification axis — orthogonal to the green/red/grey
    # flag. `verification` is the verifier verdict; `state` is the lifecycle
    # (active facts feed the matrix + all generators; rejected is a soft-delete
    # kept for audit). `entity` holds the attributed subject when a fact is a
    # conflation (e.g. "Khachuyan — иное лицо").
    _add_column_if_missing(conn, "facts", "verification", "TEXT NOT NULL DEFAULT 'unverified'")
    _add_column_if_missing(conn, "facts", "verification_note", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "facts", "verification_sources", "TEXT NOT NULL DEFAULT '[]'")
    _add_column_if_missing(conn, "facts", "verification_at", "TIMESTAMP")
    _add_column_if_missing(conn, "facts", "entity", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "facts", "state", "TEXT NOT NULL DEFAULT 'active'")
    # speaker attribution: which founder (entities row, kind='founder') this fact
    # is from — interviews with several founders (e.g. both Libermans) otherwise
    # leave facts unattributed to a specific person.
    _add_column_if_missing(conn, "facts", "speaker_entity_id", "INTEGER")
    # must-have: a fact the client provided personally — rendered BLUE, weighted
    # heavily in Deliver. An overlay on the green/red/grey flag (avoids a CHECK
    # rebuild of the facts table for a 4th flag value).
    _add_column_if_missing(conn, "facts", "must_have", "INTEGER NOT NULL DEFAULT 0")
    # must-have origin: '' (none), 'client' (blue — mandatory in briefs) or 'expert'
    # (purple — flagged important). must_have stays the boolean "is must-have at all".
    _add_column_if_missing(conn, "facts", "must_have_by", "TEXT NOT NULL DEFAULT ''")
    conn.execute("UPDATE facts SET must_have_by='client' WHERE must_have=1 AND must_have_by=''")
    # short 2-3 word card title (LLM-generated, analyst-editable). '' = no title yet.
    _add_column_if_missing(conn, "facts", "title", "TEXT NOT NULL DEFAULT ''")
    # merged-away facts: this fact was folded into / renamed as fact #merged_into.
    # state stays 'rejected' (excluded from briefs/cycles/counts) but it's HIDDEN,
    # not 'refuted' — the joint card links back to it. NULL = a normal active/rejected
    # fact. (Earlier code wrongly set verification='refuted' on merges — see backfill.)
    _add_column_if_missing(conn, "facts", "merged_into", "INTEGER")
    _backfill_merged_into(conn)
    # fact-trust (phase 1): identity anchor outside the narrative matrix — the
    # company, its founders, and known decoys (different people with overlapping
    # names). Bare, source-linked facts only; the narrative lives in L1/L2 cells.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id     TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            kind          TEXT NOT NULL DEFAULT 'founder',
            name          TEXT NOT NULL,
            role          TEXT NOT NULL DEFAULT '',
            canonical_url TEXT NOT NULL DEFAULT '',
            links         TEXT NOT NULL DEFAULT '{}',
            note          TEXT NOT NULL DEFAULT '',
            confirmed     INTEGER NOT NULL DEFAULT 0,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK(kind IN ('company','founder','decoy'))
        )
    """)
    # Внешние компании, упомянутые под клиентом (GetTaxi, прошлые компании фаундеров,
    # конкуренты) — лёгкая карточка с логотипом. Пер-клиентские (не глобальный реестр).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mentioned_companies (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id   TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            logo        TEXT NOT NULL DEFAULT '',
            note        TEXT NOT NULL DEFAULT '',
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entity_facts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id    INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            key          TEXT NOT NULL DEFAULT '',
            value        TEXT NOT NULL DEFAULT '',
            source_url   TEXT NOT NULL DEFAULT '',
            source_title TEXT NOT NULL DEFAULT '',
            as_of        DATE,
            verified     INTEGER NOT NULL DEFAULT 0,
            sort_order   INTEGER NOT NULL DEFAULT 0
        )
    """)
    # company "About" card: group entity facts into business sections
    # (profile / sites / funding / history / product / metrics). Empty = ungrouped.
    _add_column_if_missing(conn, "entity_facts", "section", "TEXT NOT NULL DEFAULT ''")
    # fact-trust (phase 3): extra corroborating sources for a merged fact. The
    # canonical fact keeps facts.source_id as its primary; duplicates' sources are
    # folded in here. Corroboration = 1 (primary) + count(fact_sources) — a trust
    # signal (more independent sources/channels = stronger fact).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fact_sources (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_id   INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
            source_id INTEGER,
            channel   TEXT NOT NULL DEFAULT '',
            title     TEXT NOT NULL DEFAULT '',
            url       TEXT NOT NULL DEFAULT ''
        )
    """)
    # client dossier: LLM-сводки осведомлённости. layer_id=0 — общий exec-summary,
    # 1..8 — синтез по слою. Кэш, пересобирается по кнопке. tone: 'analyst'|'present'.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dossier_summaries (
            client_id   TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            layer_id    INTEGER NOT NULL,
            tone        TEXT NOT NULL DEFAULT 'analyst',
            text        TEXT NOT NULL DEFAULT '',
            updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (client_id, layer_id, tone)
        )
    """)
    # app-wide one-time migration flags (key/value). Keeps one-shot data fixes from
    # re-running on every startup (which would clobber later manual edits).
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.commit()
    _migrate_red_to_grey_once(conn)
    _migrate_matrix_v2_once(conn)


def _migrate_matrix_v2_once(conn: sqlite3.Connection) -> None:
    """One-time (guard-key `matrix_v3_names_desc_v1`): синхронизировать имена и описания
    подсекций из models.LAYERS в существующие БД — «финальная форма матрицы» (v3).
    Смысловой сдвиг L2: 2.1 Path of expertise, 2.2 → Founders & Core team relations
    (отношения в ПРЕДЫДУЩИХ командах), 2.3 → Investors relations (инвесторы прошлых компаний);
    + уточнённые кросс-ссылки в L3/L4/L6. Guard по app_meta: бамп ключа заставляет применить
    заново (ручные UI-правки описаний перезапишутся канонической методологией). Переселение
    фактов между ячейками — отдельно, фичей переклассификации (per-client); особенно L2.2/L2.3."""
    done = conn.execute(
        "SELECT value FROM app_meta WHERE key='matrix_v3_names_desc_v1'"
    ).fetchone()
    if done:
        return
    from .models import LAYERS
    for L in LAYERS:
        for s in L.subsections:
            conn.execute(
                "UPDATE subsections SET name=?, description=? WHERE id=?",
                (s.name, s.description, s.id),
            )
    conn.execute(
        "INSERT OR REPLACE INTO app_meta (key, value) VALUES ('matrix_v3_names_desc_v1', '1')"
    )
    conn.commit()


def _migrate_red_to_grey_once(conn: sqlite3.Connection) -> None:
    """One-time: retire the (too crude) auto red-flag — fold existing red facts into
    grey. Guarded so it runs exactly once: manual red flags set afterwards survive.
    The `red` value stays valid in the schema CHECK (flags may be set by hand later)."""
    done = conn.execute("SELECT value FROM app_meta WHERE key='reflag_red_to_grey_v1'").fetchone()
    if done:
        return
    conn.execute("UPDATE facts SET flag='grey' WHERE flag='red'")
    conn.execute("INSERT OR REPLACE INTO app_meta (key, value) VALUES ('reflag_red_to_grey_v1', '1')")
    conn.commit()


def _migrate_audit_add_youtube(conn: sqlite3.Connection) -> None:
    """Extend ingest_audit CHECK constraint to include 'youtube' kind (idempotent)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='ingest_audit'"
    ).fetchone()
    if row is None:
        return  # table not yet created
    ddl = row[0] or ""
    if "'youtube'" in ddl or '"youtube"' in ddl:
        return  # already has youtube in constraint

    # Recreate table with extended CHECK + new columns, preserving existing data
    conn.executescript("""
        ALTER TABLE ingest_audit RENAME TO _ingest_audit_old;

        CREATE TABLE ingest_audit (
            id              TEXT PRIMARY KEY,
            client_id       TEXT NOT NULL,
            ingest_kind     TEXT NOT NULL CHECK(ingest_kind IN ('llm_report', 'manual_seed', 'youtube', 'audio_file')),
            source_artifact TEXT NOT NULL,
            agent           TEXT,
            cite_format     TEXT,
            parsed_at       TIMESTAMP NOT NULL,
            facts_emitted   INTEGER NOT NULL DEFAULT 0,
            facts_committed INTEGER NOT NULL DEFAULT 0,
            greys_emitted   INTEGER NOT NULL DEFAULT 0,
            channel_warnings INTEGER NOT NULL DEFAULT 0,
            expert_email    TEXT NOT NULL DEFAULT '',
            confirmed_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            preview_json    TEXT NOT NULL DEFAULT '{}',
            video_id        TEXT,
            transcriber     TEXT,
            transcribe_cost_usd REAL,
            transcribe_duration_sec INTEGER
        );

        INSERT INTO ingest_audit
            (id, client_id, ingest_kind, source_artifact, agent, cite_format,
             parsed_at, facts_emitted, facts_committed, greys_emitted,
             channel_warnings, expert_email, confirmed_at, preview_json)
        SELECT id, client_id, ingest_kind, source_artifact, agent, cite_format,
               parsed_at,
               COALESCE(facts_emitted, 0),
               COALESCE(facts_committed, 0),
               COALESCE(greys_emitted, 0),
               COALESCE(channel_warnings, 0),
               COALESCE(expert_email, ''),
               COALESCE(confirmed_at, parsed_at),
               COALESCE(preview_json, '{}')
        FROM _ingest_audit_old;

        DROP TABLE _ingest_audit_old;
    """)


def _migrate_audit_add_audio_file(conn: sqlite3.Connection) -> None:
    """Extend ingest_audit CHECK constraint to include 'audio_file' kind (idempotent).

    Same rebuild pattern as _migrate_audit_add_youtube: SQLite cannot ALTER a CHECK,
    so the table is recreated with the extended constraint, preserving data and the
    youtube-era columns (which may or may not exist on the old table).
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='ingest_audit'"
    ).fetchone()
    if row is None:
        return  # table not yet created
    ddl = row[0] or ""
    if "'audio_file'" in ddl or '"audio_file"' in ddl:
        return  # already migrated

    old_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(ingest_audit)").fetchall()
    }
    extra = [c for c in ("video_id", "transcriber", "transcribe_cost_usd",
                         "transcribe_duration_sec") if c in old_cols]
    extra_select = ("".join(f", {c}" for c in extra))

    conn.executescript(f"""
        ALTER TABLE ingest_audit RENAME TO _ingest_audit_old;

        CREATE TABLE ingest_audit (
            id              TEXT PRIMARY KEY,
            client_id       TEXT NOT NULL,
            ingest_kind     TEXT NOT NULL CHECK(ingest_kind IN ('llm_report', 'manual_seed', 'youtube', 'audio_file')),
            source_artifact TEXT NOT NULL,
            agent           TEXT,
            cite_format     TEXT,
            parsed_at       TIMESTAMP NOT NULL,
            facts_emitted   INTEGER NOT NULL DEFAULT 0,
            facts_committed INTEGER NOT NULL DEFAULT 0,
            greys_emitted   INTEGER NOT NULL DEFAULT 0,
            channel_warnings INTEGER NOT NULL DEFAULT 0,
            expert_email    TEXT NOT NULL DEFAULT '',
            confirmed_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            preview_json    TEXT NOT NULL DEFAULT '{{}}',
            video_id        TEXT,
            transcriber     TEXT,
            transcribe_cost_usd REAL,
            transcribe_duration_sec INTEGER
        );

        INSERT INTO ingest_audit
            (id, client_id, ingest_kind, source_artifact, agent, cite_format,
             parsed_at, facts_emitted, facts_committed, greys_emitted,
             channel_warnings, expert_email, confirmed_at, preview_json{extra_select})
        SELECT id, client_id, ingest_kind, source_artifact, agent, cite_format,
               parsed_at,
               COALESCE(facts_emitted, 0),
               COALESCE(facts_committed, 0),
               COALESCE(greys_emitted, 0),
               COALESCE(channel_warnings, 0),
               COALESCE(expert_email, ''),
               COALESCE(confirmed_at, parsed_at),
               COALESCE(preview_json, '{{}}'){extra_select}
        FROM _ingest_audit_old;

        DROP TABLE _ingest_audit_old;
    """)


def _backfill_subsection_descriptions(conn: sqlite3.Connection) -> None:
    """Populate empty subsections.description from models.LAYERS defaults.

    Idempotent: only updates rows where description IS NULL or empty.
    Expert-edited descriptions are never overwritten.
    """
    from .models import LAYERS
    for layer in LAYERS:
        for sub in layer.subsections:
            if not (sub.description or "").strip():
                continue
            conn.execute(
                """UPDATE subsections
                      SET description = ?
                    WHERE id = ?
                      AND (description IS NULL OR description = '')""",
                (sub.description, sub.id),
            )


def _migrate_collapse_1_4(conn: sqlite3.Connection) -> None:
    """Idempotent migration: merge subsection 1.4 into 1.3 across all client data."""
    old_exists = conn.execute(
        "SELECT 1 FROM subsections WHERE id = '1.4'"
    ).fetchone()
    if not old_exists:
        return  # already migrated or fresh DB with new models

    # Update subsection 1.3 name/code to merged scope
    conn.execute(
        "UPDATE subsections SET code='FEARS_DREAMS_IDENTITY', "
        "name='Fears, Dreams & Identity', "
        "description='Inner self: fears, vulnerabilities, dreams and identity of the founder' "
        "WHERE id='1.3'"
    )

    # For each client that has a 1.4 cell, ensure a 1.3 cell exists, then reparent facts
    rows_14 = conn.execute(
        "SELECT id, client_id FROM cells WHERE subsection_id='1.4'"
    ).fetchall()
    for cell_14 in rows_14:
        client_id = cell_14["client_id"]
        # Ensure 1.3 cell exists
        cell_13 = conn.execute(
            "SELECT id FROM cells WHERE client_id=? AND subsection_id='1.3'",
            (client_id,)
        ).fetchone()
        if cell_13 is None:
            conn.execute(
                "INSERT INTO cells (client_id, subsection_id) VALUES (?, '1.3')",
                (client_id,)
            )
            cell_13 = conn.execute(
                "SELECT id FROM cells WHERE client_id=? AND subsection_id='1.3'",
                (client_id,)
            ).fetchone()
        # Reparent all facts from 1.4 cell to 1.3 cell
        conn.execute(
            "UPDATE facts SET cell_id=? WHERE cell_id=?",
            (cell_13["id"], cell_14["id"])
        )
        # Delete the now-empty 1.4 cell
        conn.execute("DELETE FROM cells WHERE id=?", (cell_14["id"],))

    # Migrate active work_items: remap subsection_id 1.4 → 1.3
    conn.execute(
        "UPDATE work_items SET subsection_id='1.3' "
        "WHERE subsection_id='1.4' AND status IN ('queued','in_progress','needs_review')"
    )
    # Completed/cancelled work_items: NULL out subsection_id (can't keep FK to deleted subsection;
    # historical context is preserved in title/notes)
    conn.execute(
        "UPDATE work_items SET subsection_id=NULL "
        "WHERE subsection_id='1.4' AND status IN ('done','cancelled','blocked')"
    )

    # Migrate narrative_tracks: replace '1.4' with '1.3' in target_subsection_ids JSON
    import json as _json
    tracks = conn.execute(
        "SELECT id, target_subsection_ids FROM narrative_tracks "
        "WHERE target_subsection_ids LIKE '%1.4%'"
    ).fetchall()
    for t in tracks:
        ids = _json.loads(t["target_subsection_ids"] or "[]")
        updated = list(dict.fromkeys(
            ("1.3" if sid == "1.4" else sid) for sid in ids
        ))
        conn.execute(
            "UPDATE narrative_tracks SET target_subsection_ids=? WHERE id=?",
            (_json.dumps(updated), t["id"])
        )

    # Finally remove subsection 1.4 from reference table
    conn.execute("DELETE FROM subsections WHERE id='1.4'")


def reset(db_path: Optional[Path] = None) -> None:
    """Wipe the DB file (for clean demo runs)."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if path.exists():
        path.unlink()

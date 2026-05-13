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


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist, then apply additive migrations."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    # additive migrations — safe to run on existing DBs
    _add_column_if_missing(conn, "clients", "founder_name", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "clients", "founder_handle", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "clients", "aliases", "TEXT DEFAULT '[]'")
    _add_column_if_missing(conn, "clients", "notes", "TEXT DEFAULT ''")
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
    # llm-5: ingest_audit table for LLM Report Ingest provenance
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingest_audit (
            id              TEXT PRIMARY KEY,
            client_id       TEXT NOT NULL,
            ingest_kind     TEXT NOT NULL CHECK(ingest_kind IN ('llm_report', 'manual_seed')),
            source_artifact TEXT NOT NULL,
            agent           TEXT,
            cite_format     TEXT,
            parsed_at       TIMESTAMP NOT NULL,
            facts_emitted   INTEGER NOT NULL,
            facts_committed INTEGER NOT NULL,
            greys_emitted   INTEGER NOT NULL,
            channel_warnings INTEGER NOT NULL,
            expert_email    TEXT NOT NULL,
            confirmed_at    TIMESTAMP NOT NULL,
            preview_json    TEXT NOT NULL
        )
    """)
    conn.commit()


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

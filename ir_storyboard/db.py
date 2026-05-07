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
    conn = sqlite3.connect(path)
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
    conn.commit()


def reset(db_path: Optional[Path] = None) -> None:
    """Wipe the DB file (for clean demo runs)."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if path.exists():
        path.unlink()

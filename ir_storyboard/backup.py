"""Client-scoped data backup / restore — "rebar" safety around clear-data.

Two independent safety nets sit in front of the destructive
``DELETE /api/clients/{id}/data`` endpoint:

1. **Per-client JSON snapshot** (:func:`snapshot_client` + :func:`write_backup`):
   every client-scoped row serialized to a single JSON file that can be replayed
   with :func:`restore_client`. Restore re-issues autoincrement ids and re-threads
   foreign keys, so it never collides with rows another client created in the
   meantime.

2. **Full DB snapshot** (:func:`backup_full_db`): a gzip'd copy of the whole
   SQLite file taken via the online backup API — a disaster net independent of
   the per-client logic and our understanding of the schema.

Foreign-key map handled by restore (autoincrement ids are *not* preserved):

    cells.id     (old → new)  →  facts.cell_id
    sources.id   (old → new)  →  facts.source_id
    plans.id     (old → new)  →  narrative_tracks.plan_id
    ingest_audit.id   TEXT, preserved as-is  →  facts.ingest_audit_id

``sources`` has no ``client_id``; rows are reached only through this client's
``facts.source_id`` and we snapshot only the ones actually used by those facts.
``narrative_tracks`` is reached through ``plans.id``.
"""
from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db, matrix

SCHEMA_VERSION = 1

# Order matters for restore: parents before children so FK remap is available.
# (clients first — INSERT OR IGNORE; cells/sources/plans before their children.)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _safe_ts() -> str:
    """UTC ISO timestamp with no characters illegal in filenames (no colons)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")


def default_backups_dir() -> Path:
    """Where backups live in production: <db parent>/backups (inside the volume)."""
    return db.DEFAULT_DB_PATH.parent / "backups"


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ──────────────────────────────────────────────────────────────────────────
# Snapshot
# ──────────────────────────────────────────────────────────────────────────

def snapshot_client(conn: sqlite3.Connection, client_id: str) -> Dict[str, Any]:
    """Collect every client-scoped row into a serializable dict.

    Only sources actually referenced by this client's facts are captured (sources
    have no client_id and may be shared with other clients).
    """
    clients = _rows(conn, "SELECT * FROM clients WHERE id=?", (client_id,))

    cells = _rows(conn, "SELECT * FROM cells WHERE client_id=?", (client_id,))

    facts = _rows(
        conn,
        "SELECT f.* FROM facts f "
        "JOIN cells c ON c.id = f.cell_id "
        "WHERE c.client_id=?",
        (client_id,),
    )

    # Sources reachable through this client's facts (de-duplicated).
    src_ids = sorted({f["source_id"] for f in facts if f["source_id"] is not None})
    sources: List[Dict[str, Any]] = []
    if src_ids:
        placeholders = ",".join("?" for _ in src_ids)
        sources = _rows(
            conn,
            f"SELECT * FROM sources WHERE id IN ({placeholders})",
            tuple(src_ids),
        )

    ingest_audit = _rows(
        conn, "SELECT * FROM ingest_audit WHERE client_id=?", (client_id,)
    )
    work_items = _rows(
        conn, "SELECT * FROM work_items WHERE client_id=?", (client_id,)
    )
    plans = _rows(conn, "SELECT * FROM plans WHERE client_id=?", (client_id,))
    narrative_tracks = _rows(
        conn,
        "SELECT nt.* FROM narrative_tracks nt "
        "JOIN plans p ON p.id = nt.plan_id "
        "WHERE p.client_id=?",
        (client_id,),
    )
    artifacts = _rows(
        conn, "SELECT * FROM artifacts WHERE client_id=?", (client_id,)
    )
    client_subsection_notes = _rows(
        conn, "SELECT * FROM client_subsection_notes WHERE client_id=?", (client_id,)
    )

    return {
        "client_id": client_id,
        "created_at": _utc_now_iso(),
        "schema_version": SCHEMA_VERSION,
        "tables": {
            "clients": clients,
            "cells": cells,
            "facts": facts,
            "sources": sources,
            "ingest_audit": ingest_audit,
            "work_items": work_items,
            "plans": plans,
            "narrative_tracks": narrative_tracks,
            "artifacts": artifacts,
            "client_subsection_notes": client_subsection_notes,
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# Write / list JSON backups
# ──────────────────────────────────────────────────────────────────────────

def _meta_from_snapshot(backup_id: str, snapshot: Dict[str, Any],
                        path: Path) -> Dict[str, Any]:
    counts = {t: len(rows) for t, rows in snapshot["tables"].items()}
    return {
        "id": backup_id,
        "created_at": snapshot.get("created_at"),
        "path": str(path),
        "counts": counts,
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }


def write_backup(client_id: str, snapshot: Dict[str, Any],
                 backups_dir: Path) -> Dict[str, Any]:
    """Write the snapshot JSON to <backups_dir>/<client_id>/<ts>.json, return meta."""
    client_dir = Path(backups_dir) / client_id
    client_dir.mkdir(parents=True, exist_ok=True)
    backup_id = _safe_ts()
    path = client_dir / f"{backup_id}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return _meta_from_snapshot(backup_id, snapshot, path)


def list_backups(client_id: str, backups_dir: Path) -> List[Dict[str, Any]]:
    """Return meta for every JSON backup of this client, newest first."""
    client_dir = Path(backups_dir) / client_id
    if not client_dir.is_dir():
        return []
    metas: List[Dict[str, Any]] = []
    for fp in client_dir.glob("*.json"):
        try:
            snapshot = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        metas.append(_meta_from_snapshot(fp.stem, snapshot, fp))
    # newest first — backup_id is a sortable UTC timestamp
    metas.sort(key=lambda m: m["id"], reverse=True)
    return metas


def read_backup(client_id: str, backup_id: str,
                backups_dir: Path) -> Optional[Dict[str, Any]]:
    """Load one backup snapshot by id, or None if it doesn't exist."""
    path = Path(backups_dir) / client_id / f"{backup_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ──────────────────────────────────────────────────────────────────────────
# Purge (shared by clear endpoint and restore)
# ──────────────────────────────────────────────────────────────────────────

def _purge_client(conn: sqlite3.Connection, client_id: str) -> Dict[str, int]:
    """Delete all client-scoped data and reset the empty 24-cell grid.

    Does NOT commit and does NOT create a backup — callers own the transaction.
    ``sources`` shared with other clients are preserved (only orphaned ones are
    removed). Returns a per-table deletion count dict.
    """
    deleted: Dict[str, int] = {}

    def _count(sql: str, params: tuple = ()) -> int:
        row = conn.execute(sql, params).fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    # facts (live in this client's cells)
    deleted["facts"] = _count(
        "SELECT COUNT(*) FROM facts WHERE cell_id IN "
        "(SELECT id FROM cells WHERE client_id=?)",
        (client_id,),
    )

    # sources reachable only through this client's facts — capture before delete
    src_ids = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT f.source_id FROM facts f "
            "JOIN cells c ON c.id = f.cell_id "
            "WHERE c.client_id=? AND f.source_id IS NOT NULL",
            (client_id,),
        ).fetchall()
    ]

    conn.execute(
        "DELETE FROM facts WHERE cell_id IN "
        "(SELECT id FROM cells WHERE client_id=?)",
        (client_id,),
    )

    # only sources now orphaned for every client get removed
    sources_deleted = 0
    for sid in src_ids:
        still_used = conn.execute(
            "SELECT 1 FROM facts WHERE source_id=? LIMIT 1", (sid,)
        ).fetchone()
        if still_used is None:
            conn.execute("DELETE FROM sources WHERE id=?", (sid,))
            sources_deleted += 1
    deleted["sources"] = sources_deleted

    deleted["ingest_audit"] = _count(
        "SELECT COUNT(*) FROM ingest_audit WHERE client_id=?", (client_id,)
    )
    conn.execute("DELETE FROM ingest_audit WHERE client_id=?", (client_id,))

    deleted["work_items"] = _count(
        "SELECT COUNT(*) FROM work_items WHERE client_id=?", (client_id,)
    )
    conn.execute("DELETE FROM work_items WHERE client_id=?", (client_id,))

    deleted["narrative_tracks"] = _count(
        "SELECT COUNT(*) FROM narrative_tracks WHERE plan_id IN "
        "(SELECT id FROM plans WHERE client_id=?)",
        (client_id,),
    )
    conn.execute(
        "DELETE FROM narrative_tracks WHERE plan_id IN "
        "(SELECT id FROM plans WHERE client_id=?)",
        (client_id,),
    )

    deleted["plans"] = _count(
        "SELECT COUNT(*) FROM plans WHERE client_id=?", (client_id,)
    )
    conn.execute("DELETE FROM plans WHERE client_id=?", (client_id,))

    deleted["artifacts"] = _count(
        "SELECT COUNT(*) FROM artifacts WHERE client_id=?", (client_id,)
    )
    conn.execute("DELETE FROM artifacts WHERE client_id=?", (client_id,))

    deleted["client_subsection_notes"] = _count(
        "SELECT COUNT(*) FROM client_subsection_notes WHERE client_id=?",
        (client_id,),
    )
    conn.execute(
        "DELETE FROM client_subsection_notes WHERE client_id=?", (client_id,)
    )

    deleted["cells"] = _count(
        "SELECT COUNT(*) FROM cells WHERE client_id=?", (client_id,)
    )
    conn.execute("DELETE FROM cells WHERE client_id=?", (client_id,))
    matrix.ensure_full_grid(conn, client_id)

    return deleted


# ──────────────────────────────────────────────────────────────────────────
# Restore
# ──────────────────────────────────────────────────────────────────────────

def _insert_remap(conn: sqlite3.Connection, table: str, row: Dict[str, Any],
                  drop_id: bool = True, overrides: Optional[Dict[str, Any]] = None,
                  or_ignore: bool = False) -> Optional[int]:
    """Insert one row dict, optionally dropping its 'id' so SQLite re-issues it.

    ``overrides`` replaces column values (used to thread remapped FKs).
    Returns the new rowid (lastrowid) so callers can build old→new maps.
    """
    data = dict(row)
    if overrides:
        data.update(overrides)
    if drop_id:
        data.pop("id", None)
    if not data:
        return None
    cols = list(data.keys())
    placeholders = ",".join("?" for _ in cols)
    prefix = "INSERT OR IGNORE INTO" if or_ignore else "INSERT INTO"
    cur = conn.execute(
        f"{prefix} {table} ({','.join(cols)}) VALUES ({placeholders})",
        tuple(data[c] for c in cols),
    )
    return cur.lastrowid


def restore_client(conn: sqlite3.Connection, client_id: str,
                   snapshot: Dict[str, Any]) -> Dict[str, int]:
    """Replay a snapshot for ``client_id``, re-issuing ids and re-threading FKs.

    The current client data is purged first (same logic as clear, no extra
    backup), then rows are inserted fresh. Autoincrement ids are NOT preserved —
    we let SQLite assign new ones and remap every foreign key, so restore never
    collides with rows another client created since the backup was taken.

    Whole thing runs in one transaction; any error rolls back.
    """
    tables = snapshot["tables"]
    restored: Dict[str, int] = {}
    try:
        # 1. purge current data (no commit inside)
        _purge_client(conn, client_id)

        # 2. client row — usually already present, so INSERT OR IGNORE
        for row in tables.get("clients", []):
            _insert_remap(conn, "clients", row, drop_id=False, or_ignore=True)

        # 3. cells — re-issue ids, but reuse the empty cells ensure_full_grid just
        #    created for the same (client_id, subsection_id) to honour the UNIQUE
        #    constraint. Build old cell id → live cell id map.
        cell_map: Dict[int, int] = {}
        for row in tables.get("cells", []):
            live = conn.execute(
                "SELECT id FROM cells WHERE client_id=? AND subsection_id=?",
                (client_id, row["subsection_id"]),
            ).fetchone()
            if live is not None:
                cell_map[row["id"]] = live["id"]
            else:
                new_id = _insert_remap(
                    conn, "cells", row,
                    overrides={"client_id": client_id},
                )
                cell_map[row["id"]] = new_id
        restored["cells"] = len(cell_map)

        # 4. sources — re-issue ids, build old→new map
        source_map: Dict[int, int] = {}
        for row in tables.get("sources", []):
            new_id = _insert_remap(conn, "sources", row)
            source_map[row["id"]] = new_id
        restored["sources"] = len(source_map)

        # 5. plans — re-issue ids, build old→new map
        plan_map: Dict[int, int] = {}
        for row in tables.get("plans", []):
            new_id = _insert_remap(
                conn, "plans", row, overrides={"client_id": client_id}
            )
            plan_map[row["id"]] = new_id
        restored["plans"] = len(plan_map)

        # 6. ingest_audit — TEXT primary key, preserve as-is (facts reference it)
        for row in tables.get("ingest_audit", []):
            _insert_remap(conn, "ingest_audit", row, drop_id=False,
                          overrides={"client_id": client_id})
        restored["ingest_audit"] = len(tables.get("ingest_audit", []))

        # 7. facts — remap cell_id + source_id (ingest_audit_id is TEXT, kept)
        for row in tables.get("facts", []):
            overrides: Dict[str, Any] = {"cell_id": cell_map[row["cell_id"]]}
            if row.get("source_id") is not None:
                overrides["source_id"] = source_map[row["source_id"]]
            _insert_remap(conn, "facts", row, overrides=overrides)
        restored["facts"] = len(tables.get("facts", []))

        # 8. narrative_tracks — remap plan_id
        for row in tables.get("narrative_tracks", []):
            _insert_remap(
                conn, "narrative_tracks", row,
                overrides={"plan_id": plan_map[row["plan_id"]]},
            )
        restored["narrative_tracks"] = len(tables.get("narrative_tracks", []))

        # 9. work_items — autoincrement id re-issued; related_track_id / related_fact_id
        #    are ON DELETE SET NULL soft refs — null them to avoid dangling ids
        #    (restored tracks/facts got new ids and we don't track that mapping).
        for row in tables.get("work_items", []):
            _insert_remap(
                conn, "work_items", row,
                overrides={
                    "client_id": client_id,
                    "related_track_id": None,
                    "related_fact_id": None,
                },
            )
        restored["work_items"] = len(tables.get("work_items", []))

        # 10. artifacts — re-issue id
        for row in tables.get("artifacts", []):
            _insert_remap(conn, "artifacts", row,
                          overrides={"client_id": client_id})
        restored["artifacts"] = len(tables.get("artifacts", []))

        # 11. client_subsection_notes — composite PK (client_id, subsection_id),
        #     no autoincrement id to drop
        for row in tables.get("client_subsection_notes", []):
            _insert_remap(conn, "client_subsection_notes", row, drop_id=False,
                          overrides={"client_id": client_id})
        restored["client_subsection_notes"] = len(
            tables.get("client_subsection_notes", [])
        )

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return restored


# ──────────────────────────────────────────────────────────────────────────
# Full DB backup (disaster net)
# ──────────────────────────────────────────────────────────────────────────

_FULL_DB_KEEP = 20


def backup_full_db(db_path: Path, backups_dir: Path,
                   client_id: str = "") -> Path:
    """Gzip a consistent copy of the whole SQLite DB into <backups_dir>/_full/.

    Uses the SQLite online backup API (handles a live connection / WAL safely)
    into a temp .db, then gzips that. Keeps the newest ``_FULL_DB_KEEP`` files.
    Returns the path to the written .db.gz.
    """
    db_path = Path(db_path)
    full_dir = Path(backups_dir) / "_full"
    full_dir.mkdir(parents=True, exist_ok=True)

    ts = _safe_ts()
    slug = (client_id or "all").replace("/", "_")
    out_path = full_dir / f"{ts}-before-clear-{slug}.db.gz"

    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".db")
    tmp_db = Path(tmp_name)
    try:
        import os
        os.close(tmp_fd)
        # Consistent snapshot via the online backup API.
        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(tmp_db)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

        with open(tmp_db, "rb") as f_in, gzip.open(out_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    finally:
        if tmp_db.exists():
            tmp_db.unlink()

    _prune_full_backups(full_dir)
    return out_path


def _prune_full_backups(full_dir: Path) -> None:
    """Keep only the newest _FULL_DB_KEEP gz files; delete older ones."""
    files = sorted(
        full_dir.glob("*.db.gz"),
        key=lambda p: p.name,
        reverse=True,
    )
    for stale in files[_FULL_DB_KEEP:]:
        try:
            stale.unlink()
        except OSError:
            pass

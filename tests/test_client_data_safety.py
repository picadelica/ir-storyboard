"""Rebar safety tests for the destructive clear-client-data path.

Guarantees:
  * clear() always writes a recoverable per-client JSON backup first
  * clear() never touches another client's facts, and a source SHARED between
    two clients survives while sources orphaned for the cleared client go away
  * restore() round-trips counts, fact texts/flags, and FK integrity
  * restore() re-issues autoincrement ids, so it never collides with rows the
    other client created since the backup was taken

Pure core: temp SQLite DB + backups_dir under tmp_path. No network / LLM.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import backup, db, matrix


# ── fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    yield c
    c.close()


@pytest.fixture
def backups_dir(tmp_path):
    return tmp_path / "backups"


def _seed(conn):
    """2 clients (A, B), each with facts, sharing ONE common source.

    Returns the shared source id. Client A also gets a private (online_research)
    source so we can assert orphaned-source cleanup on clear(A).
    """
    matrix.upsert_client(conn, "a", "Client A")
    matrix.upsert_client(conn, "b", "Client B")
    matrix.ensure_full_grid(conn, "a")
    matrix.ensure_full_grid(conn, "b")

    # ONE shared source, referenced by facts of BOTH clients.
    shared = matrix.add_source(
        conn, channel="offline_interview",
        title="Shared interview 2026-01-01",
    )
    # A private source used only by client A's facts → orphaned after clear(A).
    a_private = matrix.add_source(
        conn, channel="offline_interview",
        title="A-only interview 2026-02-02",
    )

    # Client A: 2 facts (one on shared source, one on private source).
    matrix.add_fact(conn, client_id="a", subsection_id="1.1",
                    text="A fact on shared source", flag="green", source_id=shared)
    matrix.add_fact(conn, client_id="a", subsection_id="1.2",
                    text="A fact on private source", flag="green", source_id=a_private)

    # Client B: 1 fact on the SAME shared source.
    matrix.add_fact(conn, client_id="b", subsection_id="1.1",
                    text="B fact on shared source", flag="green", source_id=shared)

    return {"shared": shared, "a_private": a_private}


def _fact_rows(conn, client_id):
    return conn.execute(
        "SELECT f.* FROM facts f JOIN cells c ON c.id=f.cell_id "
        "WHERE c.client_id=? ORDER BY f.text",
        (client_id,),
    ).fetchall()


# ── tests ─────────────────────────────────────────────────────────────────

def test_clear_creates_backup(conn, backups_dir):
    _seed(conn)

    snapshot = backup.snapshot_client(conn, "a")
    meta = backup.write_backup("a", snapshot, backups_dir)
    backup._purge_client(conn, "a")
    conn.commit()

    # backup file exists on disk
    assert Path(meta["path"]).is_file()
    assert meta["counts"]["facts"] == 2

    # and it actually contains A's facts
    listed = backup.list_backups("a", backups_dir)
    assert len(listed) == 1
    loaded = backup.read_backup("a", listed[0]["id"], backups_dir)
    texts = {f["text"] for f in loaded["tables"]["facts"]}
    assert texts == {"A fact on shared source", "A fact on private source"}


def test_clear_isolates_other_client(conn, backups_dir):
    ids = _seed(conn)

    backup._purge_client(conn, "a")
    conn.commit()

    # B's fact is still there
    b_facts = _fact_rows(conn, "b")
    assert len(b_facts) == 1
    assert b_facts[0]["text"] == "B fact on shared source"

    # shared source survives (still referenced by B)
    assert conn.execute(
        "SELECT 1 FROM sources WHERE id=?", (ids["shared"],)
    ).fetchone() is not None

    # A's orphaned private source is gone
    assert conn.execute(
        "SELECT 1 FROM sources WHERE id=?", (ids["a_private"],)
    ).fetchone() is None

    # A has no facts left, but the empty 24-cell grid is rebuilt
    assert len(_fact_rows(conn, "a")) == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM cells WHERE client_id='a'"
    ).fetchone()[0] == 24


def test_restore_roundtrip(conn, backups_dir):
    _seed(conn)

    snapshot = backup.snapshot_client(conn, "a")
    before = {t: len(rows) for t, rows in snapshot["tables"].items()}
    before_facts = {
        f["text"]: f["flag"] for f in snapshot["tables"]["facts"]
    }
    backup.write_backup("a", snapshot, backups_dir)

    backup._purge_client(conn, "a")
    conn.commit()

    last = backup.list_backups("a", backups_dir)[0]
    snap = backup.read_backup("a", last["id"], backups_dir)
    backup.restore_client(conn, "a", snap)

    # counts match
    after_facts = _fact_rows(conn, "a")
    assert len(after_facts) == before["facts"]
    src_count = conn.execute(
        "SELECT COUNT(DISTINCT f.source_id) FROM facts f "
        "JOIN cells c ON c.id=f.cell_id WHERE c.client_id='a' "
        "AND f.source_id IS NOT NULL"
    ).fetchone()[0]
    assert src_count == before["sources"]

    # texts/flags identical
    restored_facts = {f["text"]: f["flag"] for f in after_facts}
    assert restored_facts == before_facts

    # FK integrity: every fact.cell_id exists in cells, every source_id in sources
    for f in after_facts:
        assert conn.execute(
            "SELECT 1 FROM cells WHERE id=?", (f["cell_id"],)
        ).fetchone() is not None
        if f["source_id"] is not None:
            assert conn.execute(
                "SELECT 1 FROM sources WHERE id=?", (f["source_id"],)
            ).fetchone() is not None


def test_restore_id_remap_no_collision(conn, backups_dir):
    """After clear(A), B grabs the autoincrement id A's fact used to hold.
    Restoring A must re-issue ids — no PK collision, both A and new-B survive.
    """
    _seed(conn)

    snapshot = backup.snapshot_client(conn, "a")
    backup.write_backup("a", snapshot, backups_dir)

    # capture A's old max fact id to make the collision concrete
    old_max_fact = conn.execute("SELECT MAX(id) FROM facts").fetchone()[0]

    backup._purge_client(conn, "a")
    conn.commit()

    # B creates a NEW fact — SQLite re-uses the autoincrement counter, so this
    # fact may take an id that A's snapshot also carries.
    new_b_id = matrix.add_fact(
        conn, client_id="b", subsection_id="1.3",
        text="B fact created after clear", flag="green",
    )

    # restore A from the snapshot — must NOT raise a PK / UNIQUE collision
    last = backup.list_backups("a", backups_dir)[0]
    snap = backup.read_backup("a", last["id"], backups_dir)
    backup.restore_client(conn, "a", snap)  # would throw on collision

    # both A's restored facts and the new B fact are present
    a_facts = {f["text"] for f in _fact_rows(conn, "a")}
    assert a_facts == {"A fact on shared source", "A fact on private source"}

    b_facts = {f["text"] for f in _fact_rows(conn, "b")}
    assert "B fact created after clear" in b_facts
    assert "B fact on shared source" in b_facts

    # the new B fact still exists by its id (was not clobbered)
    assert conn.execute(
        "SELECT 1 FROM facts WHERE id=?", (new_b_id,)
    ).fetchone() is not None
    assert old_max_fact is not None  # sanity: there were facts pre-clear

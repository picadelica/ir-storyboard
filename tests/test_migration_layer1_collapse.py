"""Task 5: migration test — L1 collapse from 4 subsections to 3 (1.4 → 1.3)."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix


def _inject_old_state(conn) -> None:
    """Build a fixture that looks like a pre-migration DB: subsection 1.4 present,
    a fact under it, an active and a done work-item, and a narrative track referencing it."""
    # Insert subsection 1.4 (layer 1 already seeded by seed_layers)
    conn.execute(
        "INSERT OR IGNORE INTO subsections (id, layer_id, code, name, sort_order) "
        "VALUES ('1.4', 1, 'DREAMS_IDENTITY', 'Dreams & Identity', 4)"
    )
    conn.commit()

    matrix.upsert_client(conn, "old-client", "Old Client")
    matrix.ensure_full_grid(conn, "old-client")

    # Ensure a 1.4 cell exists (ensure_full_grid inserts only LAYERS subsections, so add manually)
    conn.execute(
        "INSERT OR IGNORE INTO cells (client_id, subsection_id) VALUES ('old-client', '1.4')"
    )
    conn.commit()

    cell_14 = conn.execute(
        "SELECT id FROM cells WHERE client_id='old-client' AND subsection_id='1.4'"
    ).fetchone()

    src_id = conn.execute(
        "INSERT INTO sources (channel, title, url) VALUES ('offline_interview', 'Interview 2025-01-01', '')"
    ).lastrowid
    conn.execute(
        "INSERT INTO facts (cell_id, text, flag, source_id) VALUES (?, 'Old dream fact', 'green', ?)",
        (cell_14["id"], src_id)
    )

    # Active work-item on 1.4
    conn.execute(
        "INSERT INTO work_items (client_id, type, subsection_id, source_signal, title, status) "
        "VALUES ('old-client', 'fill_gap', '1.4', 'empty_cells', 'Fill 1.4', 'queued')"
    )
    # Done work-item on 1.4 — should NOT be migrated (historical record)
    conn.execute(
        "INSERT INTO work_items (client_id, type, subsection_id, source_signal, title, status) "
        "VALUES ('old-client', 'fill_gap', '1.4', 'empty_cells', 'Old done 1.4', 'done')"
    )

    # Narrative track with "1.4" in target_subsection_ids (including duplicate "1.3" to test dedup)
    plan_id = matrix.upsert_plan(conn, "old-client", "2025Q4")
    conn.execute(
        "INSERT INTO narrative_tracks (plan_id, name, angle, target_layer_ids, target_subsection_ids) "
        "VALUES (?, 'Track with 1.4', 'test angle', '[1]', ?)",
        (plan_id, json.dumps(["1.3", "1.4", "2.1"]))
    )
    conn.commit()


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    # init_schema creates tables and runs _migrate_collapse_1_4 (no-op on empty DB)
    db.init_schema(c)
    # seed layers/subsections (new model: 24 subsections, no 1.4)
    matrix.seed_layers(c)
    # inject old state AFTER seeding (1.4 manually re-introduced to simulate legacy DB)
    _inject_old_state(c)
    return c


def test_subsection_1_4_removed(conn):
    db._migrate_collapse_1_4(conn)
    conn.commit()
    row = conn.execute("SELECT 1 FROM subsections WHERE id='1.4'").fetchone()
    assert row is None


def test_subsection_1_3_renamed(conn):
    db._migrate_collapse_1_4(conn)
    conn.commit()
    row = conn.execute("SELECT code, name FROM subsections WHERE id='1.3'").fetchone()
    assert row["code"] == "FEARS_DREAMS_IDENTITY"
    assert "Dreams" in row["name"] or "Fears" in row["name"]


def test_facts_migrated_to_1_3(conn):
    db._migrate_collapse_1_4(conn)
    conn.commit()
    cell_13 = conn.execute(
        "SELECT id FROM cells WHERE client_id='old-client' AND subsection_id='1.3'"
    ).fetchone()
    assert cell_13 is not None
    facts = conn.execute(
        "SELECT id FROM facts WHERE cell_id=?", (cell_13["id"],)
    ).fetchall()
    assert len(facts) >= 1  # the old dream fact moved here


def test_no_1_4_cell_remains(conn):
    db._migrate_collapse_1_4(conn)
    conn.commit()
    cell_14 = conn.execute(
        "SELECT id FROM cells WHERE client_id='old-client' AND subsection_id='1.4'"
    ).fetchone()
    assert cell_14 is None


def test_active_work_item_migrated_to_1_3(conn):
    db._migrate_collapse_1_4(conn)
    conn.commit()
    queued_14 = conn.execute(
        "SELECT 1 FROM work_items WHERE subsection_id='1.4' AND status='queued'"
    ).fetchone()
    assert queued_14 is None
    queued_13 = conn.execute(
        "SELECT 1 FROM work_items WHERE subsection_id='1.3' AND status='queued'"
    ).fetchone()
    assert queued_13 is not None


def test_done_work_item_preserved_with_null_subsection(conn):
    db._migrate_collapse_1_4(conn)
    conn.commit()
    # Done record survives migration; subsection_id is NULLed (FK to deleted subsection)
    done_row = conn.execute(
        "SELECT subsection_id FROM work_items WHERE title='Old done 1.4' AND status='done'"
    ).fetchone()
    assert done_row is not None   # item not deleted
    assert done_row["subsection_id"] is None  # FK released


def test_narrative_track_updated_and_deduplicated(conn):
    db._migrate_collapse_1_4(conn)
    conn.commit()
    track = conn.execute(
        "SELECT target_subsection_ids FROM narrative_tracks WHERE name='Track with 1.4'"
    ).fetchone()
    ids = json.loads(track["target_subsection_ids"])
    assert "1.4" not in ids
    assert "1.3" in ids
    assert ids.count("1.3") == 1  # deduplicated (was "1.3" + "1.4"→"1.3")


def test_migration_idempotent(conn):
    db._migrate_collapse_1_4(conn)
    conn.commit()
    # Second call is a no-op — 1.4 no longer in subsections
    db._migrate_collapse_1_4(conn)
    conn.commit()
    assert conn.execute("SELECT 1 FROM subsections WHERE id='1.4'").fetchone() is None


def test_total_subsections_is_24(conn):
    db._migrate_collapse_1_4(conn)
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM subsections").fetchone()[0]
    assert count == 24

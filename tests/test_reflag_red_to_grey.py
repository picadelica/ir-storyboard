"""Авто-красный убран: одноразовая миграция red→grey, гард не трогает ручные red."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "test_reflag.db")
    db.init_schema(c)            # миграция отрабатывает (фактов ещё нет, гард выставлен)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "acme", "Acme")
    yield c
    c.close()


def _flag(conn, fid):
    return conn.execute("SELECT flag FROM facts WHERE id=?", (fid,)).fetchone()["flag"]


def test_existing_red_folded_to_grey_once(conn):
    # имитируем «старую» БД с красным фактом ДО миграции: снимаем гард
    fid = matrix.add_fact(conn, client_id="acme", subsection_id="1.1",
                          text="CEO под следствием", flag="red",
                          rationale="ручной риск")
    conn.execute("DELETE FROM app_meta WHERE key='reflag_red_to_grey_v1'")
    conn.commit()

    db._migrate_red_to_grey_once(conn)
    assert _flag(conn, fid) == "grey"            # красный свёрнут в серый

    # гард выставлен → ручной red ПОСЛЕ миграции переживает повторный прогон
    manual = matrix.add_fact(conn, client_id="acme", subsection_id="1.2",
                             text="спорный момент", flag="red",
                             rationale="аналитик отметил риск")
    db._migrate_red_to_grey_once(conn)
    assert _flag(conn, manual) == "red"          # ручной флаг не тронут

#!/usr/bin/env python3
"""Клонировать клиента целиком под новым id — песочница для проверок на проде.

Зачем: обкатывать новое (мониторинг, переклассификацию, ингесты) на копии реального
клиента, не трогая рабочего. Копия полноценная: матрица с фактами и источниками,
сущности (фаундеры), упомянутые компании, история ингестов, планы и артефакты.

Что НЕ копируется осознанно:
  * fact_activity — журнал действий принадлежит оригиналу, у копии своя история;
  * dossier_summaries — кэш LLM-текстов, пересобирается кнопкой;
  * watchlist/кандидаты/обзоры — у песочницы свой мониторинг с нуля.

Использование (внутри контейнера прода):
    python3 scripts/clone_client.py --from gonka --to g2 --name "G2" \
        --db /app/data/matrix.db
Без --force откажется писать в существующего клиента.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import backup, db, matrix  # noqa: E402


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def clone(conn: sqlite3.Connection, src: str, dst: str, name: str) -> dict:
    counts: dict[str, int] = {}

    # 0. Чистим то, что restore_client не покрывает (он сносит только матрицу),
    #    иначе повторный прогон с --force удвоит сущности и компании.
    conn.execute("DELETE FROM entity_facts WHERE entity_id IN "
                 "(SELECT id FROM entities WHERE client_id=?)", (dst,))
    conn.execute("DELETE FROM entities WHERE client_id=?", (dst,))
    conn.execute("DELETE FROM mentioned_companies WHERE client_id=?", (dst,))

    # 1. Сущности — первыми: на них ссылаются факты (speaker_entity_id).
    entity_map: dict[int, int] = {}
    for e in _rows(conn, "SELECT * FROM entities WHERE client_id=?", (src,)):
        old_id = e.pop("id")
        e["client_id"] = dst
        cols = ",".join(e.keys())
        cur = conn.execute(f"INSERT INTO entities ({cols}) VALUES ({','.join('?' * len(e))})",
                           tuple(e.values()))
        entity_map[old_id] = int(cur.lastrowid)
    counts["entities"] = len(entity_map)

    n_ef = 0
    for old_eid, new_eid in entity_map.items():
        for ef in _rows(conn, "SELECT * FROM entity_facts WHERE entity_id=?", (old_eid,)):
            ef.pop("id")
            ef["entity_id"] = new_eid
            cols = ",".join(ef.keys())
            conn.execute(f"INSERT INTO entity_facts ({cols}) VALUES ({','.join('?' * len(ef))})",
                         tuple(ef.values()))
            n_ef += 1
    counts["entity_facts"] = n_ef

    # 2. Матрица целиком — снимком/восстановлением (там уже есть переклейка FK и
    #    аккуратная работа с общими sources).
    snap = backup.snapshot_client(conn, src)
    snap["client_id"] = dst

    # id прогонов ингеста — TEXT PRIMARY KEY (UUID) и восстанавливаются как есть,
    # поэтому копии нужны свои: иначе UNIQUE-конфликт с прогонами оригинала.
    # Ссылку facts.ingest_audit_id переклеиваем на новые id.
    audit_map: dict[str, str] = {}
    for row in snap["tables"].get("ingest_audit", []):
        old = row.get("id")
        if old:
            audit_map[old] = str(uuid.uuid4())
            row["id"] = audit_map[old]

    for table, rows in snap["tables"].items():
        for row in rows:
            if "client_id" in row:
                row["client_id"] = dst
            if table == "facts":
                if row.get("speaker_entity_id"):
                    row["speaker_entity_id"] = entity_map.get(row["speaker_entity_id"])
                if row.get("ingest_audit_id"):
                    row["ingest_audit_id"] = audit_map.get(row["ingest_audit_id"])
    snap["tables"]["clients"] = [{**snap["tables"]["clients"][0], "id": dst, "name": name}]

    restored = backup.restore_client(conn, dst, snap)
    counts.update({f"matrix.{k}": v for k, v in restored.items()})

    # 3. Упомянутые компании. Автосозданная «текущая компания» копии заменяется
    #    записями оригинала — иначе тег «про компанию» поменял бы смысл: у копии
    #    факты про компанию оригинала, они и должны считаться «про текущую».
    src_mc = _rows(conn, "SELECT * FROM mentioned_companies WHERE client_id=?", (src,))
    if any(m["is_current"] for m in src_mc):
        conn.execute("DELETE FROM mentioned_companies WHERE client_id=? AND is_current=1", (dst,))
    for m in src_mc:
        m.pop("id")
        m["client_id"] = dst
        cols = ",".join(m.keys())
        conn.execute(f"INSERT INTO mentioned_companies ({cols}) VALUES ({','.join('?' * len(m))})",
                     tuple(m.values()))
    counts["mentioned_companies"] = len(src_mc)

    conn.commit()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src", required=True, help="id клиента-оригинала")
    ap.add_argument("--to", dest="dst", required=True, help="id копии")
    ap.add_argument("--name", default="", help="название копии (по умолчанию «<имя> (копия)»)")
    ap.add_argument("--db", default="", help="путь к БД (по умолчанию рабочая)")
    ap.add_argument("--force", action="store_true", help="писать в существующего клиента")
    args = ap.parse_args()

    conn = db.connect(Path(args.db) if args.db else None)
    db.init_schema(conn)
    matrix.seed_layers(conn)

    row = conn.execute("SELECT * FROM clients WHERE id=?", (args.src,)).fetchone()
    if row is None:
        print(f"нет клиента {args.src!r}", file=sys.stderr)
        return 1
    existing = conn.execute("SELECT 1 FROM clients WHERE id=?", (args.dst,)).fetchone()
    if existing and not args.force:
        print(f"клиент {args.dst!r} уже есть — прерываюсь (--force чтобы перезаписать)",
              file=sys.stderr)
        return 1

    name = args.name or f"{row['name']} (копия)"
    matrix.upsert_client(conn, args.dst, name,
                         sector=row["sector"] if "sector" in row.keys() else "",
                         founder_name=(row["founder_name"] if "founder_name" in row.keys() else "") or "")

    counts = clone(conn, args.src, args.dst, name)
    print(f"копия {args.src} → {args.dst} ({name}):")
    for k, v in counts.items():
        if v:
            print(f"  {k}: {v}")
    facts = conn.execute(
        "SELECT COUNT(*) FROM facts f JOIN cells c ON c.id=f.cell_id WHERE c.client_id=?",
        (args.dst,)).fetchone()[0]
    print(f"итого фактов у копии: {facts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

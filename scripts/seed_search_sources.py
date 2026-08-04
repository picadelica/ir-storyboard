#!/usr/bin/env python3
"""Завести поисковые источники по фаундерам рабочих клиентов.

Правила:
  * пропускаем явно тестовых (`test`) и песочницу `g2` (у неё свои источники);
  * пропускаем клиентов, у которых нет ни фактов, ни фаундеров-сущностей;
  * фаундеры берутся из сущностей (тогда у источника есть спикер), иначе из
    `clients.founder_name`;
  * имена-неимена (аналитиковы пометки вроде «Liberman siblings (…) — через
    Product Science как инкубатор») в запрос не годятся и отсеиваются;
  * запрос: «<Фаундер> <Компания> интервью|interview», окно — auto.

Запуск: --apply, чтобы писать; без него — только показать, что будет заведено.
"""
import re
import sys

from ir_storyboard import db, watchlist

SKIP = {"test", "g2"}
APPLY = "--apply" in sys.argv

conn = db.connect("/app/data/matrix.db")
db.init_schema(conn)


def is_person_name(name: str) -> bool:
    """Отсечь аналитиковы пометки: имя — это 2-4 слова без скобок, запятых и тире."""
    n = (name or "").strip()
    if not n or len(n) > 40:
        return False
    if re.search(r"[(),;]|—|\bInc\b|\bLtd\b", n):
        return False
    return 1 < len(n.split()) <= 4


def short_company(name: str) -> str:
    return (name or "").split(",")[0].strip()


def build_query(founder: str, company: str) -> str:
    both = f"{founder} {company}"
    word = "интервью" if re.search(r"[А-Яа-яЁё]", both) else "interview"
    return f"{founder} {company} {word}".strip()


planned = []
for row in conn.execute("SELECT id, name, founder_name FROM clients ORDER BY id"):
    cid = row["id"]
    if cid in SKIP:
        continue
    facts = conn.execute(
        "SELECT COUNT(*) n FROM facts f JOIN cells ce ON ce.id=f.cell_id WHERE ce.client_id=?",
        (cid,)).fetchone()["n"]
    ents = [dict(e) for e in conn.execute(
        "SELECT id, name FROM entities WHERE client_id=? AND kind='founder' ORDER BY id", (cid,))]
    if facts == 0 and not ents:
        print(f"— пропускаю {cid}: ни фактов, ни фаундеров")
        continue

    have = {(i.get("config") or {}).get("query") for i in watchlist.list_items(conn, cid)}
    company = short_company(row["name"])

    founders = [(e["name"], e["id"]) for e in ents if is_person_name(e["name"])]
    skipped_ents = [e["name"] for e in ents if not is_person_name(e["name"])]
    if not founders and (row["founder_name"] or "").strip():
        founders = [(row["founder_name"].strip(), None)]

    if not founders:
        print(f"— пропускаю {cid}: имя фаундера не распознано "
              f"({', '.join(s[:40] for s in skipped_ents) or 'пусто'})")
        continue
    for name, eid in founders:
        q = build_query(name, company)
        if q in have:
            print(f"= {cid}: уже есть «{q}»")
            continue
        planned.append((cid, q, eid, name))

print(f"\nк заведению: {len(planned)}")
for cid, q, eid, name in planned:
    print(f"  {cid:30} {q}" + (f"   [спикер #{eid}]" if eid else "   [спикер не задан]"))

if not APPLY:
    print("\n(сухой прогон, ничего не записано — повторить с --apply)")
    raise SystemExit(0)

for cid, q, eid, name in planned:
    watchlist.add_item(conn, cid, "search_query", {"query": q, "window": "auto"},
                       speaker_entity_id=eid, created_by="claudecode")
print(f"\nзаведено источников: {len(planned)}")

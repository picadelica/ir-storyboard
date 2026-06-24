"""Deliver: plain JSON export of the matrix content.

Texts only — NO source links / quotes. Three blocks:
  1. export       — описание выгрузки (клиент, легенда, счётчики)
  2. company_card — карточка компании (значения из About, без ссылок)
  3. cards        — состав: номер в матрице, заголовок, текст, цвет звезды, цвет карточки

Only active cards are exported (rejected / merged-away originals are excluded —
`facts_for_cell` already drops state='rejected'), matching what the matrix shows.
"""
from __future__ import annotations

from typing import Optional

from . import matrix
from .models import LAYERS

# цвет карточки = флаг факта
CARD_COLORS = {
    "green": "подтверждённый факт",
    "red": "риск / проблема",
    "grey": "явный пробел (gap)",
}
# цвет звезды = происхождение must-have
STAR_COLORS = {
    "blue": "must-have от клиента (обязательно)",
    "purple": "важное от эксперта (приоритет)",
}


def _star(row) -> Optional[str]:
    keys = row.keys()
    by = (row["must_have_by"] if "must_have_by" in keys else "") or ""
    if not by and ("must_have" in keys and row["must_have"]):
        by = "client"
    if by == "client":
        return "blue"
    if by == "expert":
        return "purple"
    return None


def build_matrix_export(conn, client_id: str) -> dict:
    crow = conn.execute(
        "SELECT id, name, sector, one_liner FROM clients WHERE id=?", (client_id,)
    ).fetchone()
    client = dict(crow) if crow else {"id": client_id, "name": client_id, "sector": "", "one_liner": ""}

    # 3. cards — обход в порядке матрицы (слой → подсекция → факты ячейки)
    cards = []
    for layer in LAYERS:
        for sub in layer.subsections:
            for r in matrix.facts_for_cell(conn, client_id, sub.id):
                cards.append({
                    "matrix_no": sub.id,                # номер в матрице (координата ячейки)
                    "subsection_name": sub.name,
                    "layer_id": layer.id,
                    "layer_name": layer.name,
                    "fact_id": r["id"],
                    "title": (r["title"] if "title" in r.keys() else "") or "",
                    "text": r["text"],
                    "card_color": r["flag"],            # цвет карточки
                    "star": _star(r),                   # цвет звезды (или null)
                })

    # 2. company_card — карточка компании (kind='company'), только значения, без ссылок
    company = None
    for e in matrix.entities_for_client(conn, client_id):
        if e["kind"] == "company":
            company = {
                "name": e["name"],
                "role": e.get("role") or "",
                "note": e.get("note") or "",
                "facts": [
                    {"section": f.get("section") or "", "key": f["key"], "value": f["value"]}
                    for f in e["facts"]
                ],
            }
            break

    return {
        # 1. export — основное описание выгрузки
        "export": {
            "client_id": client["id"],
            "client_name": client["name"],
            "sector": client.get("sector") or "",
            "one_liner": client.get("one_liner") or "",
            "card_count": len(cards),
            "description": (
                "Выгрузка содержания нарративной матрицы: тексты карточек без ссылок на источники. "
                "card_color — цвет карточки (флаг факта); star — цвет звёздочки (приоритет must-have, "
                "null если обычная карточка); matrix_no — номер ячейки в матрице."
            ),
            "legend": {"card_color": CARD_COLORS, "star_color": STAR_COLORS},
        },
        "company_card": company,
        "cards": cards,
    }

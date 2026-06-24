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

    data = {
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
    # самодокументируемость: вкладываем markdown-описание формата прямо в JSON
    data["readme"] = describe_json_format(data)
    return data


def describe_json_format(data: dict) -> str:
    """Markdown-описание формата JSON-выгрузки (передаётся заказчику, чтобы он
    мог разобрать JSON). Описывает структуру и допустимые значения полей."""
    legend = data["export"]["legend"]
    cc = legend["card_color"]
    sc = legend["star_color"]
    L: list[str] = []
    L.append("# Формат JSON-выгрузки матрицы")
    L.append("")
    L.append("Кодировка UTF-8. Корень — объект с ключами `export`, `company_card`, "
             "`cards`, `readme`. Тексты приведены без ссылок на источники.")
    L.append("")
    L.append("## `export` — метаданные выгрузки")
    L.append("- `client_id` (строка) — идентификатор клиента")
    L.append("- `client_name` (строка) — название клиента")
    L.append("- `sector` (строка) — сектор")
    L.append("- `one_liner` (строка) — краткое описание")
    L.append("- `card_count` (число) — количество карточек в массиве `cards`")
    L.append("- `generated_at` (строка) — время формирования, ISO-8601 (UTC)")
    L.append("- `legend` (объект) — расшифровка значений `card_color` и `star`")
    L.append("- `description` (строка) — краткая памятка по выгрузке")
    L.append("")
    L.append("## `company_card` — карточка компании (объект или `null`)")
    L.append("- `name` (строка) — название компании")
    L.append("- `role` (строка) — род деятельности")
    L.append("- `note` (строка) — заметка")
    L.append("- `facts` (массив объектов) — бизнес-факты, каждый: `{section, key, value}` (строки)")
    L.append("")
    L.append("## `cards` — массив карточек матрицы")
    L.append("Карточки идут в порядке матрицы. Каждый объект:")
    L.append("")
    L.append('- `matrix_no` (строка) — номер ячейки в матрице, напр. `"1.1"`')
    L.append("- `subsection_name` (строка) — название подсекции (ячейки)")
    L.append("- `layer_id` (число) — номер слоя (1–8)")
    L.append("- `layer_name` (строка) — название слоя")
    L.append("- `fact_id` (число) — внутренний id факта")
    L.append("- `title` (строка) — короткий заголовок карточки (может быть пустым)")
    L.append("- `text` (строка) — текст карточки")
    L.append("- `card_color` (строка) — цвет карточки, одно из:")
    for k, v in cc.items():
        L.append(f"    - `{k}` — {v}")
    L.append("- `star` (строка или `null`) — цвет звёздочки (приоритет), одно из:")
    for k, v in sc.items():
        L.append(f"    - `{k}` — {v}")
    L.append("    - `null` — обычная карточка (без звёздочки)")
    L.append("")
    L.append("## `readme`")
    L.append("Строка с этим же описанием формата — вложена в JSON, чтобы файл был "
             "самодокументируемым.")
    L.append("")
    L.append("> В выгрузку попадают только активные карточки; объединённые и отклонённые "
             "исходники исключены. Карточки сгруппированы по слою (`layer_id`), внутри "
             "слоя — по ячейке (`matrix_no`).")
    return "\n".join(L)

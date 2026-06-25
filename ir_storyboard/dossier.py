"""Client dossier — консолидированное представление осведомлённости о клиенте.

Слой над матрицей: не ячейки-факты, а целостная картина —
  • exec-summary (3-4 предложения по клиенту),
  • синтез по каждому из 8 слоёв (2-3 предложения),
  • метрики «сколько знаем» по слою (факты/покрытие/источники/свежесть/
    корроборация/сигналы) — считаются из матрицы на лету.

Тексты генерит LLM (кэш в dossier_summaries), метрики — из данных.
Тон 'analyst' (рабочий) сейчас; 'present' (клиентский) — на будущее.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import llm, matrix
from .models import LAYERS

_FACTS_PER_LAYER = 14   # сколько фактов слоя отдаём модели (ограничиваем промпт)


# ───────────────────────── метрики (из данных, без LLM) ─────────────────────────

def _layer_metrics(conn, client_id: str) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    for layer in LAYERS:
        out[layer.id] = {
            "layer_id": layer.id, "name": layer.name, "intimacy": layer.intimacy,
            "n_green": 0, "n_red": 0, "n_grey": 0, "n_must_client": 0, "n_must_expert": 0,
            "cells_total": 0, "cells_filled": 0, "channels": set(), "last_update": None,
            "corroborated": 0, "facts_total": 0,
        }
    for r in matrix.cell_summary(conn, client_id):
        m = out.get(r["layer_id"])
        if m is None:
            continue
        g, rd, gr = r["n_green"] or 0, r["n_red"] or 0, r["n_grey"] or 0
        m["n_green"] += g; m["n_red"] += rd; m["n_grey"] += gr
        m["n_must_client"] += r.get("n_must_client", 0) or 0
        m["n_must_expert"] += r.get("n_must_expert", 0) or 0
        m["cells_total"] += 1
        if g + rd + gr > 0:
            m["cells_filled"] += 1
        for ch in (r.get("channels") or []):
            m["channels"].add(ch)
        lu = r.get("last_update")
        if lu and (m["last_update"] is None or lu > m["last_update"]):
            m["last_update"] = lu
    # корроборация: активные факты с >=1 дополнительным источником
    for row in conn.execute(
        """SELECT s.layer_id AS lid,
                  COUNT(*) AS total,
                  SUM(CASE WHEN (SELECT COUNT(*) FROM fact_sources fs WHERE fs.fact_id=f.id) > 0
                           THEN 1 ELSE 0 END) AS corro
             FROM facts f
             JOIN cells c ON c.id = f.cell_id
             JOIN subsections s ON s.id = c.subsection_id
             WHERE c.client_id=? AND f.state='active'
             GROUP BY s.layer_id""",
        (client_id,),
    ):
        m = out.get(row["lid"])
        if m:
            m["facts_total"] = row["total"] or 0
            m["corroborated"] = row["corro"] or 0
    for m in out.values():
        m["channels"] = sorted(m["channels"])
    return out


def _cells_by_layer(conn, client_id: str) -> Dict[int, list]:
    """Per-subsection raw для «карты знаний» (тепловая решётка 8×3)."""
    corr: Dict[str, int] = {}
    for row in conn.execute(
        """SELECT c.subsection_id AS sid,
                  SUM(CASE WHEN (SELECT COUNT(*) FROM fact_sources fs WHERE fs.fact_id=f.id) > 0
                           THEN 1 ELSE 0 END) AS corro
             FROM facts f JOIN cells c ON c.id = f.cell_id
             WHERE c.client_id=? AND f.state='active' GROUP BY c.subsection_id""",
        (client_id,),
    ):
        corr[row["sid"]] = row["corro"] or 0
    out: Dict[int, list] = {}
    for r in matrix.cell_summary(conn, client_id):
        g, rd, gr = r["n_green"] or 0, r["n_red"] or 0, r["n_grey"] or 0
        out.setdefault(r["layer_id"], []).append({
            "subsection_id": r["subsection_id"], "subsection_name": r["subsection_name"],
            "n_green": g, "n_red": rd, "n_grey": gr, "facts": g + rd + gr,
            "must_have": (r.get("n_must_client", 0) or 0) + (r.get("n_must_expert", 0) or 0) > 0,
            "corroborated": corr.get(r["subsection_id"], 0) > 0,
            "last_update": r["last_update"],
        })
    return out


def _summaries(conn, client_id: str, tone: str = "analyst") -> Dict[int, dict]:
    rows = conn.execute(
        "SELECT layer_id, text, updated_at FROM dossier_summaries WHERE client_id=? AND tone=?",
        (client_id, tone),
    ).fetchall()
    return {r["layer_id"]: {"text": r["text"], "updated_at": r["updated_at"]} for r in rows}


def build_dossier(conn, client_id: str, *, tone: str = "analyst") -> dict:
    crow = conn.execute(
        "SELECT id, name, sector, one_liner FROM clients WHERE id=?", (client_id,)
    ).fetchone()
    client = dict(crow) if crow else {"id": client_id, "name": client_id, "sector": "", "one_liner": ""}

    met = _layer_metrics(conn, client_id)
    summ = _summaries(conn, client_id, tone)
    cells = _cells_by_layer(conn, client_id)

    layers = []
    tot_f = tot_cells = filled = red = mustc = muste = corro = corro_tot = 0
    last_update = None
    for layer in LAYERS:
        m = met[layer.id]
        facts = m["n_green"] + m["n_red"] + m["n_grey"]
        layers.append({
            "layer_id": layer.id, "name": layer.name, "intimacy": layer.intimacy,
            "summary": summ.get(layer.id, {}).get("text", ""),
            "n_green": m["n_green"], "n_red": m["n_red"], "n_grey": m["n_grey"],
            "facts": facts, "cells_total": m["cells_total"], "cells_filled": m["cells_filled"],
            "channels": m["channels"], "last_update": m["last_update"],
            "n_must_client": m["n_must_client"], "n_must_expert": m["n_must_expert"],
            "corroborated": m["corroborated"], "facts_total": m["facts_total"],
            "cells": cells.get(layer.id, []),
        })
        tot_f += facts; tot_cells += m["cells_total"]; filled += m["cells_filled"]
        red += m["n_red"]; mustc += m["n_must_client"]; muste += m["n_must_expert"]
        corro += m["corroborated"]; corro_tot += m["facts_total"]
        if m["last_update"] and (last_update is None or m["last_update"] > last_update):
            last_update = m["last_update"]

    overall = {
        "facts": tot_f,
        "coverage_pct": round(100 * filled / tot_cells) if tot_cells else 0,
        "red": red, "must_client": mustc, "must_expert": muste,
        "corroborated_pct": round(100 * corro / corro_tot) if corro_tot else 0,
        "last_update": last_update,
    }
    exec_row = summ.get(0, {})
    generated_at = exec_row.get("updated_at")
    # актуальность: сколько активных фактов добавлено ПОСЛЕ генерации досье
    new_facts = 0
    if generated_at:
        new_facts = conn.execute(
            """SELECT COUNT(*) FROM facts f JOIN cells c ON c.id = f.cell_id
               WHERE c.client_id=? AND f.state='active' AND f.captured_at > ?""",
            (client_id, generated_at),
        ).fetchone()[0]
    return {
        "client": client,
        "exec_summary": exec_row.get("text", ""),
        "generated_at": generated_at,
        "tone": tone,
        "overall": overall,
        "layers": layers,
        "staleness": {"generated_at": generated_at, "new_facts": new_facts},
    }


# ───────────────────────── генерация сводок (LLM) ─────────────────────────

_SYSTEM = """Ты — IR-аналитик. По собранным фактам делаешь КОНСОЛИДИРОВАННОЕ ДОСЬЕ осведомлённости о компании — целостную картину, без воды и без выдумок (опираться только на факты).

Дай:
1) exec — 3-4 предложения по клиенту: кто и чем берёт, сильные стороны, главные риски, главные пробелы знаний.
2) для каждого слоя — 2-3 предложения (≈40-60 слов): что мы знаем, чем подтверждено, где пробел. Если фактов нет — честно «данных почти нет».

Пиши по-русски, по делу, без маркетинга. НЕ придумывай факты, которых нет во входных данных.

Верни СТРОГО валидный JSON (без markdown):
{"exec": "<...>", "layers": [{"layer_id": <int>, "text": "<...>"}]}"""


def _facts_by_layer(conn, client_id: str) -> Dict[int, List[str]]:
    by: Dict[int, List[str]] = {layer.id: [] for layer in LAYERS}
    for layer in LAYERS:
        for sub in layer.subsections:
            for r in matrix.facts_for_cell(conn, client_id, sub.id):
                if r["flag"] == "grey":
                    continue
                t = (r["text"] or "").strip()
                if t and len(by[layer.id]) < _FACTS_PER_LAYER:
                    by[layer.id].append(t)
    return by


def generate_dossier(conn, client_id: str, *, tone: str = "analyst",
                     model: Optional[str] = None) -> dict:
    """Сгенерировать exec + синтез по слоям и сохранить в dossier_summaries."""
    by = _facts_by_layer(conn, client_id)
    crow = conn.execute("SELECT name FROM clients WHERE id=?", (client_id,)).fetchone()
    name = (crow["name"] if crow else client_id) or client_id

    blocks = [f"Компания: {name}", ""]
    any_facts = False
    for layer in LAYERS:
        fs = by[layer.id]
        any_facts = any_facts or bool(fs)
        lines = "\n".join(f"  - {t[:200]}" for t in fs) or "  (фактов нет)"
        blocks.append(f"[Слой {layer.id}] {layer.name}:\n{lines}")
    user = "\n".join(blocks)

    data = llm.generate_json(_SYSTEM, user, max_tokens=2600, model=model)
    if data is None:
        return {"available": False, "written": 0}

    written = 0
    exec_text = (data.get("exec") or "").strip()
    if exec_text:
        _save(conn, client_id, 0, tone, exec_text[:1200]); written += 1
    by_id = {int(it["layer_id"]): (it.get("text") or "").strip()
             for it in (data.get("layers") or []) if isinstance(it, dict) and "layer_id" in it}
    for layer in LAYERS:
        t = by_id.get(layer.id, "")
        if t:
            _save(conn, client_id, layer.id, tone, t[:800]); written += 1
    conn.commit()
    return {"available": True, "written": written}


def _save(conn, client_id: str, layer_id: int, tone: str, text: str) -> None:
    conn.execute(
        """INSERT INTO dossier_summaries (client_id, layer_id, tone, text, updated_at)
           VALUES (?,?,?,?,CURRENT_TIMESTAMP)
           ON CONFLICT(client_id, layer_id, tone)
           DO UPDATE SET text=excluded.text, updated_at=CURRENT_TIMESTAMP""",
        (client_id, layer_id, tone, text),
    )

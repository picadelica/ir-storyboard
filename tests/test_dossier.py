"""Client dossier: metrics from data + LLM summaries cached per layer."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ir_storyboard import db, matrix, dossier, llm


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "dossier.db")
    db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "co", "Co", sector="fintech", one_liner="платежи")
    matrix.ensure_full_grid(c, "co")
    return c


def test_metrics_and_overall(conn):
    matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Раунд A $46M", flag="green")
    b = matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Риск оттока", flag="red", rationale="нет данных")
    matrix.set_fact_must_have(conn, b, source="expert")
    matrix.add_fact(conn, client_id="co", subsection_id="2.2", text="HQ Майами", flag="green")

    d = dossier.build_dossier(conn, "co")
    assert d["client"]["name"] == "Co"
    assert len(d["layers"]) == 8
    l2 = next(l for l in d["layers"] if l["layer_id"] == 2)
    assert l2["facts"] == 3 and l2["n_red"] == 1 and l2["n_must_expert"] == 1
    assert l2["cells_filled"] == 2 and l2["cells_total"] == 3
    assert d["overall"]["facts"] == 3 and d["overall"]["red"] == 1
    assert d["exec_summary"] == ""   # ещё не генерили


def test_generate_caches_summaries(conn, monkeypatch):
    matrix.add_fact(conn, client_id="co", subsection_id="2.1", text="Раунд A $46M от Tencent", flag="green")
    matrix.add_fact(conn, client_id="co", subsection_id="6.1", text="Продукт: equity pooling", flag="green")

    def _gen(system, user, *a, **k):
        return json.dumps({
            "exec": "Co — финтех для ликвидности. Сильна продуктом, риски в регуляторике, пробел в личной истории.",
            "layers": [{"layer_id": i, "text": f"Синтез слоя {i}."} for i in range(1, 9)],
        }, ensure_ascii=False)
    monkeypatch.setattr(llm, "generate", _gen)

    res = dossier.generate_dossier(conn, "co")
    assert res["available"] and res["written"] == 9   # exec + 8 layers

    d = dossier.build_dossier(conn, "co")
    assert d["exec_summary"].startswith("Co — финтех")
    assert next(l for l in d["layers"] if l["layer_id"] == 6)["summary"] == "Синтез слоя 6."

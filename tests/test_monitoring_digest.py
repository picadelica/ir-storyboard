"""Мониторинг, фаза 2-3: обзор эпизода, сравнение с прошлыми, чип «возможный дубль».

Гарантии:
  * обзор идемпотентен по (эпизод, спикер);
  * цитата, которой нет в расшифровке дословно → unverified;
  * прошлые `comparison.details` подаются в следующее сравнение (не всплывают заново);
  * спикер не определён → обзора нет, факты создаются как обычно;
  * путь атомизации не изменился (golden по фиксированной расшифровке);
  * чип дубля показывается только внутри ОДНОЙ ячейки.
"""
from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_audio_ingest import MOCK_SEGMENTS, MockTranscriber, _make_conn  # noqa: E402
from tests.test_youtube_progress import _yt_patches  # noqa: E402

URL = "https://www.youtube.com/watch?v=abc123"

# Цитата #1 есть в MOCK_SEGMENTS дословно, #2 — приглаженная моделью (нет в расшифровке).
DIGEST_PAYLOAD = {
    "main_motif": "Фаундер рассказывает, как пришёл в индустрию и куда ведёт продукт.",
    "blocks": [{"theme": "Приход в Bitfury", "start_sec": 4, "end_sec": 9,
                "gist": "Как попал в компанию на раннем этапе."}],
    "key_moments": [
        {"quote": "I joined Bitfury in 2014 as one of the early engineers there.",
         "timecode_sec": 4, "note": "точка отсчёта профессионального пути"},
        {"quote": "Мы хотим сделать искусственный интеллект доступным каждому.",
         "timecode_sec": 9, "note": "формулировка миссии"},
    ],
    "indirect": ["О деньгах говорит осторожнее, чем о технологии."],
}

COMPARISON = {
    "text": "Позиция по срокам сдвинулась: раньше говорил про год, теперь про два.",
    "details": [{"topic": "сроки выхода на рынок", "kind": "shifted",
                 "was": {"quote": "за год", "date": "2026-01-01"},
                 "now": {"quote": "I joined Bitfury in 2014 as one of the early engineers there.",
                         "timecode_sec": 4},
                 "note": "срок удвоился"}],
}


@pytest.fixture
def conn(tmp_path):
    return _make_conn(tmp_path)


def _transcribed(conn, tmp_path, client_id="test_founder"):
    """Прогнать обычный ингест — после него расшифровка лежит в кэше, как в проде."""
    from ir_storyboard.ingest.youtube_pipeline import run_youtube_preview
    with ExitStack() as stack:
        _yt_patches(stack, MockTranscriber())
        return run_youtube_preview(client_id, URL, conn, cache_dir=tmp_path)


# ── §6.7 спикер не определён → обзора нет ────────────────────────────────────

def test_no_speaker_no_digest_facts_untouched(conn, tmp_path):
    from ir_storyboard import digest, matrix

    preview = _transcribed(conn, tmp_path)
    assert len(preview.facts) == 2, "факты извлекаются независимо от обзора"

    # ни одного фаундера → спикера не определить
    res = digest.build_and_store(conn, "test_founder", URL)
    assert res["status"] == "no_speaker"
    assert conn.execute("SELECT COUNT(*) c FROM digests").fetchone()["c"] == 0

    # двое фаундеров без явного выбора — тоже не гадаем
    matrix.add_entity(conn, client_id="test_founder", kind="founder", name="Иван Петров")
    matrix.add_entity(conn, client_id="test_founder", kind="founder", name="Пётр Иванов")
    assert digest.build_and_store(conn, "test_founder", URL)["status"] == "no_speaker"


def test_single_founder_is_resolved_automatically(conn, tmp_path):
    from ir_storyboard import digest, matrix

    eid = matrix.add_entity(conn, client_id="test_founder", kind="founder", name="Иван Петров")
    _transcribed(conn, tmp_path)
    with patch("ir_storyboard.llm.build_episode_digest", return_value=dict(DIGEST_PAYLOAD)):
        res = digest.build_and_store(conn, "test_founder", URL)
    assert res["status"] == "ok"
    assert res["digest"]["speaker_entity_id"] == eid


def test_no_transcript_yet(conn):
    from ir_storyboard import digest, matrix
    matrix.add_entity(conn, client_id="test_founder", kind="founder", name="Иван Петров")
    assert digest.build_and_store(conn, "test_founder", URL)["status"] == "no_transcript"


# ── §6.4 идемпотентность по (эпизод, спикер) ─────────────────────────────────

def test_digest_is_idempotent_per_episode_and_speaker(conn, tmp_path):
    from ir_storyboard import digest, matrix

    matrix.add_entity(conn, client_id="test_founder", kind="founder", name="Иван Петров")
    _transcribed(conn, tmp_path)
    calls = []

    def _build(*a, **kw):
        calls.append(1)
        return dict(DIGEST_PAYLOAD)

    with patch("ir_storyboard.llm.build_episode_digest", side_effect=_build):
        first = digest.build_and_store(conn, "test_founder", URL)
        second = digest.build_and_store(conn, "test_founder", URL)
        # та же ссылка в другой записи — тот же эпизод
        third = digest.build_and_store(conn, "test_founder", "https://youtu.be/abc123?t=30")

    assert len(calls) == 1, "повторный запрос обзора не должен идти в модель"
    assert second["cached"] and third["cached"]
    assert first["digest"]["id"] == third["digest"]["id"]
    assert conn.execute("SELECT COUNT(*) c FROM digests").fetchone()["c"] == 1


# ── §6.5 валидация цитат ─────────────────────────────────────────────────────

def test_quote_not_in_transcript_is_marked_unverified(conn, tmp_path):
    from ir_storyboard import digest, matrix

    matrix.add_entity(conn, client_id="test_founder", kind="founder", name="Иван Петров")
    _transcribed(conn, tmp_path)
    with patch("ir_storyboard.llm.build_episode_digest", return_value=dict(DIGEST_PAYLOAD)):
        res = digest.build_and_store(conn, "test_founder", URL)

    moments = res["digest"]["payload"]["key_moments"]
    assert moments[0]["unverified"] is False, "дословная цитата — проверена"
    assert moments[1]["unverified"] is True, "приглаженная моделью — помечена"


# ── §6.6 сравнение опирается на прошлые details ──────────────────────────────

def test_comparison_receives_previous_details(conn, tmp_path):
    from ir_storyboard import digest, matrix

    eid = matrix.add_entity(conn, client_id="test_founder", kind="founder", name="Иван Петров")
    _transcribed(conn, tmp_path)

    # прошлое выступление с уже зафиксированным сдвигом
    conn.execute(
        """INSERT INTO digests (client_id, norm_url, speaker_entity_id, episode_date,
                                title, payload, model, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("test_founder", "https://www.youtube.com/watch?v=old111", eid, "2026-01-01",
         "Прошлое интервью",
         json.dumps({"main_motif": "Про запуск продукта",
                     "key_moments": [{"quote": "выйдем за год", "timecode_sec": 10}],
                     "comparison": {"text": "", "details": [
                         {"topic": "сроки выхода на рынок", "kind": "shifted"}]}},
                    ensure_ascii=False),
         "test", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()

    seen = {}

    def _compare(new_digest, previous, speaker_name="", model=None):
        seen["previous"] = previous
        return dict(COMPARISON)

    with patch("ir_storyboard.llm.build_episode_digest", return_value=dict(DIGEST_PAYLOAD)), \
         patch("ir_storyboard.llm.compare_with_previous_digests", side_effect=_compare):
        res = digest.build_and_store(conn, "test_founder", URL)

    prev = seen["previous"]
    assert len(prev) == 1 and prev[0]["date"] == "2026-01-01"
    assert prev[0]["comparison_details"][0]["topic"] == "сроки выхода на рынок", \
        "прошлые сдвиги обязаны попадать в контекст следующего сравнения"
    comparison = res["digest"]["payload"]["comparison"]
    assert comparison["text"].startswith("Позиция по срокам")
    assert comparison["details"][0]["now"]["unverified"] is False


def test_first_episode_has_no_comparison(conn, tmp_path):
    from ir_storyboard import digest, matrix

    matrix.add_entity(conn, client_id="test_founder", kind="founder", name="Иван Петров")
    _transcribed(conn, tmp_path)
    with patch("ir_storyboard.llm.build_episode_digest", return_value=dict(DIGEST_PAYLOAD)), \
         patch("ir_storyboard.llm.compare_with_previous_digests",
               side_effect=AssertionError("сравнивать не с чем — вызывать нельзя")):
        res = digest.build_and_store(conn, "test_founder", URL)
    assert res["digest"]["payload"]["comparison"] is None


def test_digest_links_source_after_commit(conn, tmp_path):
    """source_id проставляется, когда после коммита появляется строка sources."""
    from ir_storyboard import digest, matrix
    from ir_storyboard.ingest.youtube_pipeline import run_youtube_commit

    matrix.add_entity(conn, client_id="test_founder", kind="founder", name="Иван Петров")
    preview = _transcribed(conn, tmp_path)
    with patch("ir_storyboard.llm.build_episode_digest", return_value=dict(DIGEST_PAYLOAD)):
        digest.build_and_store(conn, "test_founder", URL)
    assert digest.get_digest(conn, URL, 1)["source_id"] is None

    run_youtube_commit(preview_id=preview.preview_id, accepted_fact_ids=[0],
                       overrides=[], conn=conn, expert_email="a@b.com")
    digest.link_source(conn, URL)
    d = digest.get_digest(conn, URL, 1)
    assert d["source_id"] and digest.digests_for_source(conn, d["source_id"])


# ── §6.3 (golden) путь атомизации не изменился ───────────────────────────────

GOLDEN_FACTS = [
    {"text": "Founder joined Bitfury in 2014 as an early engineer.", "subsection_id": "2.1",
     "flag": "green", "snippet_start_sec": 4.1},
    {"text": "Mission: make AI accessible to everyone on the planet.", "subsection_id": "7.1",
     "flag": "green", "snippet_start_sec": 9.1},
]
# L8 отсекает LayerGuard (веб-слои недоступны каналу online_interview) — это часть
# golden'а: факт уходит в skipped с правом override, а не в матрицу.
GOLDEN_SKIPPED = [{"text": "DePIN market revenue projections — L8 content.",
                   "subsection_id": "8.2"}]


def test_atomization_path_unchanged_golden(conn, tmp_path):
    """Фиксированная расшифровка → ровно те же факты, в том же порядке, с теми же
    ячейками, флагами и таймкодами. Мониторинг в этот путь не вмешивается."""
    preview = _transcribed(conn, tmp_path)
    got = [{"text": f.text, "subsection_id": f.subsection_id, "flag": f.flag,
            "snippet_start_sec": round(f.snippet_start_sec, 3)} for f in preview.facts]
    assert got == GOLDEN_FACTS
    assert [{"text": s.fact.text, "subsection_id": s.fact.subsection_id}
            for s in preview.skipped] == GOLDEN_SKIPPED

    stored = json.loads(conn.execute(
        "SELECT preview_json FROM ingest_audit WHERE id = ?", (preview.preview_id,)
    ).fetchone()["preview_json"])
    assert [f["text"] for f in stored["facts"]] == [f["text"] for f in GOLDEN_FACTS]
    assert "digest" not in stored, "обзор не должен подмешиваться в превью ингеста"


# ── §6.8 чип «возможный дубль» ───────────────────────────────────────────────

def test_duplicate_hint_only_within_same_cell(conn):
    from ir_storyboard import matrix, verification

    src = matrix.add_source(conn, channel="online_interview", title="Интервью",
                            url="https://example.com/1")
    matrix.add_fact(conn, client_id="test_founder", subsection_id="2.1",
                    text="Фаундер пришёл в Bitfury в 2014 году одним из первых инженеров",
                    flag="green", source_id=src)

    near = "Фаундер пришёл в Bitfury в 2014 году одним из первых инженеров команды"
    same_cell = verification.duplicate_hints(
        conn, "test_founder", [{"subsection_id": "2.1", "text": near}])
    assert len(same_cell) == 1 and same_cell[0]["idx"] == 0
    assert same_cell[0]["fact"]["text"].startswith("Фаундер пришёл")

    other_cell = verification.duplicate_hints(
        conn, "test_founder", [{"subsection_id": "4.2", "text": near}])
    assert other_cell == [], "тот же текст в другой ячейке — не дубль"

    unrelated = verification.duplicate_hints(
        conn, "test_founder",
        [{"subsection_id": "2.1", "text": "Компания открыла офис в Лиссабоне в 2025 году"}])
    assert unrelated == [], "непохожий факт не должен получать чип"


def test_duplicate_hint_ignores_too_short_texts(conn):
    from ir_storyboard import matrix, verification

    src = matrix.add_source(conn, channel="online_interview", title="t", url="https://e.com/2")
    matrix.add_fact(conn, client_id="test_founder", subsection_id="3.1",
                    text="Растёт команда", flag="green", source_id=src)
    hints = verification.duplicate_hints(
        conn, "test_founder", [{"subsection_id": "3.1", "text": "Растёт команда"}])
    assert hints == [], "на коротких текстах пересечение слов шумит — чип не показываем"


def test_api_duplicate_hints_and_digest(tmp_path):
    from fastapi.testclient import TestClient
    from ir_storyboard import db as _db, matrix
    from backend.main import app, get_conn

    db_path = tmp_path / "dup_api.db"

    def _override():
        c = _db.connect(db_path)
        _db.init_schema(c)
        matrix.seed_layers(c)
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_conn] = _override
    c = _db.connect(db_path)
    _db.init_schema(c)
    matrix.seed_layers(c)
    matrix.upsert_client(c, "test_founder", "Test Founder Co")
    matrix.add_entity(c, client_id="test_founder", kind="founder", name="Иван Петров")
    src = matrix.add_source(c, channel="online_interview", title="t", url="https://e.com/3")
    matrix.add_fact(c, client_id="test_founder", subsection_id="2.1",
                    text="Фаундер пришёл в Bitfury в 2014 году одним из первых инженеров",
                    flag="green", source_id=src)
    c.close()

    with patch("ir_storyboard.db.DEFAULT_DB_PATH", db_path), TestClient(app) as tc:
        r = tc.post("/api/monitoring/duplicate-hints", json={
            "client_id": "test_founder",
            "items": [{"subsection_id": "2.1",
                       "text": "Фаундер пришёл в Bitfury в 2014 году одним из первых инженеров команды"},
                      {"subsection_id": "7.1", "text": "Миссия — сделать ИИ доступным каждому"}]})
        assert r.status_code == 200
        hints = r.json()
        assert len(hints) == 1 and hints[0]["idx"] == 0

        # обзора ещё нет — пустой список, а не 404
        assert tc.get("/api/monitoring/digests",
                      params={"client_id": "test_founder", "url": URL}).json() == []

    app.dependency_overrides.clear()

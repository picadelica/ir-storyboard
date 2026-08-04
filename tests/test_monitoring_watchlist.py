"""Мониторинг, фаза 1: watchlist, кандидаты, релевантность, связка с ингестом.

Всё внешнее замокано (yt-dlp, сеть, LLM). Ключевые гарантии:
  * повторная проверка источника не плодит кандидатов (norm_url);
  * relevance-стаб детерминирован (имя спикера в заголовке → likely);
  * «Разобрать» НЕ трогает путь ингеста: связка кандидат↔источник восстанавливается
    по URL уже после коммита.
"""
from __future__ import annotations

import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_audio_ingest import MockTranscriber, _make_conn  # noqa: E402
from tests.test_youtube_progress import _yt_patches  # noqa: E402

CHANNEL = "https://www.youtube.com/@testfounder"


def _entries():
    """Одно и то же видео в двух формах записи + второе видео."""
    return [
        {"url": "https://youtu.be/abc123?t=42", "title": "Иван Петров про рынок",
         "duration_sec": 1800, "published_at": "2026-07-01", "thumb_url": "",
         "description": "Подкаст с фаундером", "channel": "Test Pod"},
        {"url": "https://www.youtube.com/watch?v=abc123&list=PL1", "title": "Иван Петров про рынок",
         "duration_sec": 1800, "published_at": "2026-07-01", "thumb_url": "",
         "description": "тот же эпизод, другая ссылка", "channel": "Test Pod"},
        {"url": "https://www.youtube.com/watch?v=zzz999", "title": "Обзор индустрии без гостей",
         "duration_sec": 600, "published_at": "2026-07-02", "thumb_url": "",
         "description": "нарезка новостей", "channel": "Test Pod"},
    ]


@pytest.fixture
def conn(tmp_path):
    c = _make_conn(tmp_path)
    from ir_storyboard import matrix
    matrix.add_entity(c, client_id="test_founder", kind="founder", name="Иван Петров")
    return c


@pytest.fixture
def api(tmp_path):
    """TestClient с изолированной БД (как в остальных API-тестах)."""
    from ir_storyboard import db as _db, matrix
    from backend.main import app, get_conn

    db_path = tmp_path / "monitoring_api.db"

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
    matrix.upsert_client(c, "test_founder", "Test Founder Co", sector="deeptech")
    matrix.add_entity(c, client_id="test_founder", kind="founder", name="Иван Петров")
    c.close()

    # Фоновый job открывает СВОЁ соединение по db.DEFAULT_DB_PATH — уводим и его
    # в тестовую БД, иначе job уйдёт работать в рабочую data/matrix.db.
    with patch("ir_storyboard.db.DEFAULT_DB_PATH", db_path), TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


# ── §6.1 идемпотентность кандидатов ──────────────────────────────────────────

def test_repeat_check_does_not_duplicate_candidates(conn):
    from ir_storyboard import watchlist

    item_id = watchlist.add_item(conn, "test_founder", "youtube_channel", {"url": CHANNEL})
    with patch("ir_storyboard.watchlist.fetch_channel_entries", return_value=_entries()), \
         patch("ir_storyboard.llm.generate_json", return_value=None):
        first = watchlist.check_item(conn, item_id)
        second = watchlist.check_item(conn, item_id)

    assert first["new"] == 2, "две ссылки на abc123 — это один кандидат"
    assert second["new"] == 0, "повторная проверка не должна плодить кандидатов"
    rows = watchlist.list_candidates(conn, "test_founder", state=None)
    assert len(rows) == 2
    assert sorted(r["norm_url"] for r in rows) == [
        "https://www.youtube.com/watch?v=abc123",
        "https://www.youtube.com/watch?v=zzz999",
    ]


# ── §6.2 relevance-стаб ──────────────────────────────────────────────────────

def test_relevance_stub_marks_speaker_in_title(conn):
    from ir_storyboard import watchlist

    item_id = watchlist.add_item(conn, "test_founder", "youtube_channel", {"url": CHANNEL})
    with patch("ir_storyboard.watchlist.fetch_channel_entries", return_value=_entries()), \
         patch("ir_storyboard.llm.generate_json", return_value=None):
        watchlist.check_item(conn, item_id)

    by_url = {r["norm_url"]: r for r in watchlist.list_candidates(conn, "test_founder", state=None)}
    assert by_url["https://www.youtube.com/watch?v=abc123"]["relevance"] == "likely"
    assert by_url["https://www.youtube.com/watch?v=zzz999"]["relevance"] == "unclear"


def test_relevance_uses_llm_when_available(conn):
    """При живой модели берём её вердикт, а не стаб."""
    from ir_storyboard import watchlist

    item_id = watchlist.add_item(conn, "test_founder", "youtube_channel", {"url": CHANNEL})
    verdicts = {"results": [{"relevance": "unlikely", "note": "полный тёзка из другой отрасли"},
                            {"relevance": "likely", "note": "доклад нужного человека"}]}
    with patch("ir_storyboard.watchlist.fetch_channel_entries", return_value=_entries()), \
         patch("ir_storyboard.llm.generate_json", return_value=verdicts):
        watchlist.check_item(conn, item_id)

    by_url = {r["norm_url"]: r for r in watchlist.list_candidates(conn, "test_founder", state=None)}
    assert by_url["https://www.youtube.com/watch?v=abc123"]["relevance"] == "unlikely"
    assert by_url["https://www.youtube.com/watch?v=abc123"]["relevance_note"]


# ── §6.3 «Разобрать» связывает кандидата с источником ────────────────────────

def test_ingest_links_candidate_to_source_without_touching_pipeline(conn, tmp_path):
    """Кандидат → обычный YouTube-ингест → кандидат сам становится ingested.

    Пайплайн ингеста при этом ничего не знает о мониторинге: связка ищется по
    нормализованному URL источника.
    """
    from ir_storyboard import watchlist
    from ir_storyboard.ingest.youtube_pipeline import run_youtube_preview, run_youtube_commit

    item_id = watchlist.add_item(conn, "test_founder", "youtube_channel", {"url": CHANNEL})
    with patch("ir_storyboard.watchlist.fetch_channel_entries", return_value=_entries()), \
         patch("ir_storyboard.llm.generate_json", return_value=None):
        watchlist.check_item(conn, item_id)

    cand = [r for r in watchlist.list_candidates(conn, "test_founder")
            if r["norm_url"].endswith("abc123")][0]
    watchlist.set_candidate_state(conn, cand["id"], "ingesting", actor="аналитик")

    with ExitStack() as stack:
        _yt_patches(stack, MockTranscriber())
        preview = run_youtube_preview("test_founder", cand["norm_url"], conn, cache_dir=tmp_path)
        run_youtube_commit(preview_id=preview.preview_id,
                           accepted_fact_ids=list(range(len(preview.facts))),
                           overrides=[], conn=conn, expert_email="a@b.com")

    after = [r for r in watchlist.list_candidates(conn, "test_founder", state=None)
             if r["id"] == cand["id"]][0]
    assert after["state"] == "ingested"
    assert after["source_id"], "должен появиться source_id разобранного эпизода"
    src = conn.execute("SELECT url FROM sources WHERE id=?", (after["source_id"],)).fetchone()
    assert src["url"] == cand["norm_url"]


def test_dismiss_keeps_candidate_out_of_the_queue(conn):
    from ir_storyboard import watchlist

    item_id = watchlist.add_item(conn, "test_founder", "youtube_channel", {"url": CHANNEL})
    with patch("ir_storyboard.watchlist.fetch_channel_entries", return_value=_entries()), \
         patch("ir_storyboard.llm.generate_json", return_value=None):
        watchlist.check_item(conn, item_id)
    cand = watchlist.list_candidates(conn, "test_founder")[0]
    watchlist.set_candidate_state(conn, cand["id"], "dismissed", actor="аналитик")

    assert all(r["id"] != cand["id"] for r in watchlist.list_candidates(conn, "test_founder"))
    row = watchlist.get_candidate(conn, cand["id"])
    assert row["state"] == "dismissed" and row["acted_by"] == "аналитик"


# ── URL-нормализация ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("https://youtu.be/abc123?t=90", "https://www.youtube.com/watch?v=abc123"),
    ("https://www.youtube.com/watch?v=abc123&list=PL9", "https://www.youtube.com/watch?v=abc123"),
    ("https://example.com/podcast/ep12/?utm_source=tg", "https://example.com/podcast/ep12"),
    ("https://Example.com/Ep/", "https://example.com/Ep"),
])
def test_norm_candidate_url(raw, expected):
    from ir_storyboard.watchlist import norm_candidate_url
    assert norm_candidate_url(raw) == expected


# ── RSS без сети ─────────────────────────────────────────────────────────────

def test_rss_parsing_and_candidates(conn):
    from ir_storyboard import watchlist

    feed = """<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>
      <title>Pod</title>
      <item><title>Иван Петров: интервью</title>
            <link>https://pod.example/ep1?utm_campaign=x</link>
            <pubDate>2026-06-30</pubDate>
            <description>Разговор с фаундером</description></item>
      <item><title>Выпуск без гостя</title>
            <link>https://pod.example/ep2</link><pubDate>2026-07-03</pubDate></item>
    </channel></rss>""".encode("utf-8")
    entries = watchlist.parse_rss(feed)
    assert [e["url"] for e in entries] == ["https://pod.example/ep1?utm_campaign=x",
                                           "https://pod.example/ep2"]

    item_id = watchlist.add_item(conn, "test_founder", "rss", {"feed_url": "https://pod.example/rss"})
    with patch("ir_storyboard.watchlist.fetch_rss_entries", return_value=entries), \
         patch("ir_storyboard.llm.generate_json", return_value=None):
        res = watchlist.check_item(conn, item_id)
    assert res["new"] == 2
    urls = sorted(r["norm_url"] for r in watchlist.list_candidates(conn, "test_founder"))
    assert urls == ["https://pod.example/ep1", "https://pod.example/ep2"]


def test_source_error_is_recorded_not_raised(conn):
    from ir_storyboard import watchlist

    item_id = watchlist.add_item(conn, "test_founder", "youtube_channel", {"url": CHANNEL})
    with patch("ir_storyboard.watchlist.fetch_channel_entries",
               side_effect=RuntimeError("yt-dlp: channel unavailable")):
        res = watchlist.check_item(conn, item_id)
    assert res["error"] and res["new"] == 0
    assert watchlist.get_item(conn, item_id)["last_error"]


# ── предложения ──────────────────────────────────────────────────────────────

def test_suggestions_from_past_ingests(conn, tmp_path):
    from ir_storyboard import watchlist
    from ir_storyboard.ingest.youtube_pipeline import run_youtube_preview, run_youtube_commit

    with ExitStack() as stack:
        _yt_patches(stack, MockTranscriber())
        preview = run_youtube_preview("test_founder", "https://youtu.be/abc123", conn,
                                      cache_dir=tmp_path)
        run_youtube_commit(preview_id=preview.preview_id, accepted_fact_ids=[],
                           overrides=[], conn=conn, expert_email="a@b.com")

    sug = watchlist.suggestions(conn, "test_founder")
    assert sug and sug[0]["channel_name"] == "Some Pod"
    assert sug[0]["sample_url"].endswith("abc123")

    watchlist.add_item(conn, "test_founder", "youtube_channel", {"url": CHANNEL},
                       label="Some Pod")
    assert watchlist.suggestions(conn, "test_founder") == [], "уже в мониторинге — не предлагать"


# ── API ──────────────────────────────────────────────────────────────────────

def test_api_watchlist_crud_and_candidates(api):
    r = api.post("/api/monitoring/watchlist", json={
        "client_id": "test_founder", "kind": "youtube_channel",
        "config": {"url": CHANNEL}, "label": "Канал фаундера"})
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["kind"] == "youtube_channel" and item["status"] == "active"

    assert api.get("/api/monitoring/watchlist?client_id=test_founder").json()[0]["id"] == item["id"]

    assert api.post(f"/api/monitoring/watchlist/{item['id']}/pause").json()["status"] == "paused"
    assert api.post(f"/api/monitoring/watchlist/{item['id']}/resume").json()["status"] == "active"

    with patch("ir_storyboard.watchlist.fetch_channel_entries", return_value=_entries()), \
         patch("ir_storyboard.llm.generate_json", return_value=None):
        job = api.post("/api/monitoring/check", json={"client_id": "test_founder"}).json()
        assert job["job_id"]
        for _ in range(100):
            status = api.get(f"/api/jobs/{job['job_id']}").json()
            if status["status"] in ("done", "error"):
                break
            import time
            time.sleep(0.05)
    assert status["status"] == "done", status
    assert status["result"]["new"] == 2

    cands = api.get("/api/monitoring/candidates?client_id=test_founder").json()
    assert len(cands) == 2
    assert cands[0]["relevance"] == "likely", "likely — первым в очереди"

    started = api.post(f"/api/monitoring/candidates/{cands[0]['id']}/ingest").json()
    assert started["url"].endswith("abc123") and started["candidate"]["state"] == "ingesting"

    api.post(f"/api/monitoring/candidates/{cands[1]['id']}/dismiss")
    assert api.get("/api/monitoring/candidates?client_id=test_founder").json() == []

    assert api.delete(f"/api/monitoring/watchlist/{item['id']}").json() == {"ok": True}
    assert api.get("/api/monitoring/watchlist?client_id=test_founder").json() == []


def test_api_rejects_unknown_client_and_bad_kind(api):
    assert api.post("/api/monitoring/watchlist", json={
        "client_id": "nope", "kind": "rss", "config": {"feed_url": "x"}}).status_code == 404
    assert api.post("/api/monitoring/watchlist", json={
        "client_id": "test_founder", "kind": "telepathy", "config": {}}).status_code == 400
    assert api.post("/api/monitoring/watchlist", json={
        "client_id": "test_founder", "kind": "rss", "config": {}}).status_code == 400


# ── окно поиска ──────────────────────────────────────────────────────────────

def test_search_window_backfills_then_narrows(conn):
    """Первый обход поиска берёт год (архив тоже материал), дальше — только прирост
    с прошлой проверки, с нахлёстом на отставание поисковых индексов."""
    from datetime import date

    from ir_storyboard import watchlist

    today = date(2026, 8, 4)
    item = {"kind": "search_query", "config": {"query": "David Liberman"},
            "last_checked_at": None}
    assert watchlist.search_window_since(item, today) == "2025-08-04"

    item["last_checked_at"] = "2026-07-30T09:00:00+00:00"
    assert watchlist.search_window_since(item, today) == "2026-07-23"   # −7 дней нахлёста

    item["config"]["window"] = "all"
    assert watchlist.search_window_since(item, today) == ""
    item["config"]["window"] = "month"
    assert watchlist.search_window_since(item, today) == "2026-07-04"


def test_search_source_passes_window_to_provider(conn):
    """Окно доезжает до провайдера, а дата публикации из выдачи — в кандидата."""
    from ir_storyboard import watchlist
    from ir_storyboard.llm import SearchHit

    item_id = watchlist.add_item(conn, "test_founder", "search_query",
                                 {"query": "Иван Петров интервью"})
    seen = {}

    def _fake_search(query, max_hits=5, since=""):
        seen["query"], seen["since"] = query, since
        return [SearchHit(title="Иван Петров о найме", url="https://podcast.example/e1",
                          snippet="разговор", published="2026-07-15")]

    with patch("ir_storyboard.llm.web_search", _fake_search), \
         patch("ir_storyboard.llm.generate_json", return_value=None):
        res = watchlist.check_item(conn, item_id)

    assert res["new"] == 1
    assert seen["query"] == "Иван Петров интервью"
    assert seen["since"], "первый обход должен идти с нижней границей, а не по всему вебу"
    cand = watchlist.list_candidates(conn, "test_founder")[0]
    assert cand["published_at"] == "2026-07-15"
    assert cand["relevance"] == "likely"


def test_bad_window_rejected(conn):
    from ir_storyboard import watchlist
    with pytest.raises(ValueError):
        watchlist.add_item(conn, "test_founder", "search_query",
                           {"query": "x", "window": "с прошлого вторника"})


def test_missing_date_is_resolved_only_for_survivors(conn):
    """Дату дотягиваем метаданными лишь у находок, прошедших фильтр: за отсеянное
    платить секундой сети незачем."""
    from ir_storyboard import watchlist
    from ir_storyboard.llm import SearchHit

    item_id = watchlist.add_item(conn, "test_founder", "search_query",
                                 {"query": "Иван Петров"})
    hits = [SearchHit(title="Иван Петров: интервью", url="https://youtu.be/keepme", snippet="s"),
            SearchHit(title="Обзор рынка без гостей", url="https://youtu.be/dropme", snippet="s")]
    asked: list[str] = []

    def _meta(url):
        asked.append(url)
        from ir_storyboard.ingest.loaders.youtube_url import YouTubeVideoMeta
        return YouTubeVideoMeta(video_id="keepme", canonical_url=url, title="t",
                                channel_name="c", channel_url="", duration_sec=1800,
                                upload_date="2026-07-09", description="", language="en")

    verdicts = {"results": [{"relevance": "likely", "note": "нужный человек"},
                            {"relevance": "unlikely", "note": "чужая тема"}]}
    with patch("ir_storyboard.llm.web_search", lambda q, max_hits=5, since="": hits), \
         patch("ir_storyboard.llm.generate_json", return_value=verdicts), \
         patch("ir_storyboard.ingest.loaders.youtube_url.fetch_metadata", side_effect=_meta):
        watchlist.check_item(conn, item_id)

    by_url = {c["norm_url"]: c for c in watchlist.list_candidates(conn, "test_founder", state=None)}
    kept = by_url["https://www.youtube.com/watch?v=keepme"]
    dropped = by_url["https://www.youtube.com/watch?v=dropme"]
    assert kept["published_at"] == "2026-07-09" and kept["duration_sec"] == 1800
    assert dropped["published_at"] == "", "за отсеянным в сеть не ходим"
    assert len(asked) == 1


def test_reassess_updates_verdicts_without_touching_state(conn):
    """Переоценка меняет вердикт и причину у собранных находок, но не их состояние:
    что аналитик уже скрыл или разобрал — его решение, а не модели."""
    from ir_storyboard import watchlist

    item_id = watchlist.add_item(conn, "test_founder", "youtube_channel", {"url": CHANNEL})
    with patch("ir_storyboard.watchlist.fetch_channel_entries", return_value=_entries()), \
         patch("ir_storyboard.llm.generate_json", return_value=None):
        watchlist.check_item(conn, item_id)

    cands = watchlist.list_candidates(conn, "test_founder", state=None)
    watchlist.set_candidate_state(conn, cands[0]["id"], "dismissed")

    seen = {}

    def _fake(items, speaker_names=None, company_name="", model=None):
        seen["items"] = items
        return [{"relevance": "unlikely", "note": "это карточка спикера, а не выступление"}
                for _ in items]

    with patch("ir_storyboard.llm.assess_candidate_relevance", _fake):
        res = watchlist.reassess_candidates(conn, "test_founder")

    assert res["checked"] == 1, "скрытые находки не переоцениваем"
    assert all(i.get("url") for i in seen["items"]), "ссылка обязана уходить в оценку формы"
    left = watchlist.list_candidates(conn, "test_founder", state=None)
    by_id = {c["id"]: c for c in left}
    assert by_id[cands[0]["id"]]["state"] == "dismissed"
    rest = [c for c in left if c["id"] != cands[0]["id"]][0]
    assert rest["relevance"] == "unlikely" and "карточка спикера" in rest["relevance_note"]

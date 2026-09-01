"""Разбор ссылки, которую аналитик принёс сам: POST /research/url + загрузчик страницы.

Сеть здесь не трогаем: Tavily-путь и HTTP-путь подменяются моками. Проверяем то,
что должно быть верно независимо от провайдера — куда сервер ходить не должен,
как HTML превращается в текст, и три случая, которые точка входа обязана
различать до вызова модели (YouTube / уже разбирали / текст не достался).
"""
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from ir_storyboard import db as _db, matrix
    from backend.main import app, get_conn

    db_path = tmp_path / "test_research_url.db"

    def _override_conn():
        conn = _db.connect(db_path)
        _db.init_schema(conn)
        matrix.seed_layers(conn)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_conn] = _override_conn

    conn = _db.connect(db_path)
    _db.init_schema(conn)
    matrix.seed_layers(conn)
    matrix.upsert_client(conn, "test_client", "Test Client", sector="test")
    conn.close()

    with TestClient(app) as tc:
        tc._db_path = db_path
        yield tc

    app.dependency_overrides.clear()


# ── куда сервер ходить не должен ───────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:5000/ui/api/projects",   # оркестратор на этой же машине
    "http://localhost:8080/api/clients",
    "http://169.254.169.254/latest/meta-data/",  # облачная метадата
    "http://[::1]:5000/",
])
def test_private_targets_rejected(url):
    """Ссылка во внутреннюю сеть не забирается: иначе форма разбора превращается
    в средство читать соседние сервисы с сервера."""
    from ir_storyboard.ingest.loaders.web_page import UnsafeUrl, check_public_url
    with pytest.raises(UnsafeUrl):
        check_public_url(url)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)"])
def test_non_http_schemes_rejected(url):
    from ir_storyboard.ingest.loaders.web_page import UnsafeUrl, check_public_url
    with pytest.raises(UnsafeUrl):
        check_public_url(url)


def test_public_host_allowed():
    """Публичный адрес пропускаем. DNS подменён — набор не должен зависеть от сети."""
    import socket
    from ir_storyboard.ingest.loaders.web_page import check_public_url

    resolved = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))]
    with patch("socket.getaddrinfo", return_value=resolved):
        check_public_url("https://example.com/article")   # не бросает


def test_dns_failure_is_reported_not_swallowed():
    import socket
    from ir_storyboard.ingest.loaders.web_page import UnsafeUrl, check_public_url

    with patch("socket.getaddrinfo", side_effect=socket.gaierror("no such host")):
        with pytest.raises(UnsafeUrl):
            check_public_url("https://nope.example/article")


# ── HTML → текст ───────────────────────────────────────────────────────────────

def test_html_to_text_drops_chrome_and_keeps_prose():
    from ir_storyboard.ingest.loaders.web_page import html_to_text

    html = """
    <html><head><title>Интервью с фаундером</title>
      <style>.a{color:red}</style><script>var x = 1;</script>
    </head>
    <body>
      <nav>Главная Контакты</nav>
      <h1>Как мы строили сеть</h1>
      <p>Первый абзац про запуск.</p>
      <p>Второй абзац про инвесторов.</p>
      <script>tracker();</script>
    </body></html>
    """
    title, text = html_to_text(html)

    assert title == "Интервью с фаундером"
    assert "Как мы строили сеть" in text
    assert "Первый абзац про запуск." in text
    assert "Второй абзац про инвесторов." in text
    # обвязка страницы в текст не идёт — иначе модель классифицирует меню
    assert "color:red" not in text
    assert "var x = 1" not in text
    assert "tracker()" not in text
    # меню и боковые панели — тоже обвязка: без них модель не жуёт «Главная Контакты»
    assert "Главная Контакты" not in text
    # абзацы не слиплись
    assert "запуск.Второй" not in text


def test_html_to_text_survives_broken_markup():
    """Битую разметку не роняем: что успели разобрать — то и берём."""
    from ir_storyboard.ingest.loaders.web_page import html_to_text
    title, text = html_to_text("<p>Начало<div><span>хвост оборван")
    assert "Начало" in text and "хвост оборван" in text


# ── точка входа ────────────────────────────────────────────────────────────────

def test_youtube_link_routed_to_its_own_pipeline(client):
    """У YouTube свой пайплайн (расшифровка, таймкоды) — страницу не тянем."""
    with patch("ir_storyboard.ingest.loaders.web_page.fetch_page") as fetch:
        r = client.post("/api/clients/test_client/research/url",
                        json={"url": "https://youtu.be/dQw4w9WgXcQ?t=30"})
    assert r.status_code == 200
    body = r.json()
    assert body["is_youtube"] is True
    assert body["suggested_channel"] == "online_interview"
    assert body["text"] == ""
    fetch.assert_not_called()
    # ссылка приведена к каноническому виду — по нему потом сойдётся идемпотентность
    assert "watch?v=dQw4w9WgXcQ" in body["url"]


def test_article_fetched_and_channel_suggested(client):
    from ir_storyboard.ingest.loaders.web_page import PageContent

    page = PageContent(url="https://example.com/a", title="Заголовок",
                       text="Фаундер рассказал про раунд.", via="tavily")
    with patch("ir_storyboard.ingest.loaders.web_page.fetch_page", return_value=page):
        r = client.post("/api/clients/test_client/research/url",
                        json={"url": "https://example.com/a"})
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Заголовок"
    assert body["text"] == "Фаундер рассказал про раунд."
    assert body["via"] == "tavily"
    assert body["suggested_channel"] == "online_research"
    assert body["is_youtube"] is False


def test_archival_domain_suggests_archival_channel(client):
    from ir_storyboard.ingest.loaders.web_page import PageContent

    page = PageContent(url="https://en.wikipedia.org/wiki/X", title="X",
                       text="текст", via="http")
    with patch("ir_storyboard.ingest.loaders.web_page.fetch_page", return_value=page):
        r = client.post("/api/clients/test_client/research/url",
                        json={"url": "https://en.wikipedia.org/wiki/X"})
    assert r.json()["suggested_channel"] == "archival"


def test_empty_text_is_not_an_error(client):
    """Не достали текст — не ошибка: аналитик вставит руками. Важно, что мы
    честно говорим об этом (`via` пустой), а не делаем вид, что всё хорошо."""
    from ir_storyboard.ingest.loaders.web_page import PageContent

    page = PageContent(url="https://example.com/js-only", title="", text="", via="")
    with patch("ir_storyboard.ingest.loaders.web_page.fetch_page", return_value=page):
        r = client.post("/api/clients/test_client/research/url",
                        json={"url": "https://example.com/js-only"})
    assert r.status_code == 200
    assert r.json()["text"] == ""
    assert r.json()["via"] == ""


def test_already_ingested_link_is_reported(client):
    """Ссылку уже разбирали — сказать об этом ДО того, как потрачен вызов модели.
    Сверка идёт по нормализованному URL, поэтому utm-хвост и www не мешают."""
    from ir_storyboard import db as _db, matrix
    from ir_storyboard.ingest.loaders.web_page import PageContent

    conn = _db.connect(client._db_path)
    _db.init_schema(conn)
    src = matrix.add_source(conn, channel="online_research", title="Старая статья",
                            url="https://www.example.com/piece?utm_source=tg")
    matrix.add_fact(conn, client_id="test_client", subsection_id="6.1",
                    text="Факт из этой статьи", flag="green", source_id=src,
                    evidence_snippet="Фаундер рассказал про архитектуру решения.")
    conn.close()

    page = PageContent(url="https://example.com/piece", title="Та же статья",
                       text="текст", via="http")
    with patch("ir_storyboard.ingest.loaders.web_page.fetch_page", return_value=page):
        r = client.post("/api/clients/test_client/research/url",
                        json={"url": "https://example.com/piece"})
    body = r.json()
    assert body["known_source"] is True
    assert body["known_facts"] == 1


def test_fresh_link_is_not_reported_as_known(client):
    from ir_storyboard.ingest.loaders.web_page import PageContent

    page = PageContent(url="https://example.com/new", title="Новая", text="текст", via="http")
    with patch("ir_storyboard.ingest.loaders.web_page.fetch_page", return_value=page):
        r = client.post("/api/clients/test_client/research/url",
                        json={"url": "https://example.com/new"})
    assert r.json()["known_source"] is False
    assert r.json()["known_facts"] == 0


def test_internal_url_rejected_through_the_endpoint(client):
    r = client.post("/api/clients/test_client/research/url",
                    json={"url": "http://127.0.0.1:5000/ui/api/projects"})
    assert r.status_code == 422


def test_blank_url_rejected(client):
    r = client.post("/api/clients/test_client/research/url", json={"url": "   "})
    assert r.status_code == 422


def test_unknown_client_404(client):
    r = client.post("/api/clients/nope/research/url",
                    json={"url": "https://example.com/a"})
    assert r.status_code == 404

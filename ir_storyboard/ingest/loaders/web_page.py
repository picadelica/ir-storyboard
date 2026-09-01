"""Загрузка веб-страницы в текст — для ссылки, которую аналитик принёс сам.

Два пути, в этом порядке:

1. **Tavily extract** (`llm.extract_page`) — когда есть ключ. Чище: отбрасывает
   навигацию, футеры и прочую обвязку, отдаёт основной материал.
2. **Прямой HTTP + вычистка HTML на stdlib** — фоллбек, работает без ключей.
   Грубее (в текст попадают крошки меню), но лучше, чем ничего: аналитик всё
   равно видит результат до классификации и может поправить руками.

Отдельный загрузчик, а не ветка в пайплайне: разбор такой страницы идёт через тот
же канал `online_research` и ту же точку `/ingest/preview`, что и находки поиска.
Новых каналов здесь не заводится (инвариант 3).
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import List, Optional
from urllib.parse import urlparse

from ... import llm

__all__ = ["PageContent", "UnsafeUrl", "fetch_page", "html_to_text", "check_public_url"]

# Теги, чьё содержимое в текст не идёт: это обвязка страницы, а не материал.
# `nav`/`aside`/`menu`/`form` — меню, боковые панели и формы: в прямом HTTP-пути
# без них текст заметно чище, а модель не тратит внимание на «Перейти к содержанию».
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head",
              "nav", "aside", "menu", "form", "button", "select", "option"}
# Теги, после которых нужен перенос строки, иначе абзацы слипаются в кашу.
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "section", "article", "header", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "figcaption",
}

_MAX_BYTES = 5 * 1024 * 1024        # страницы больше 5 МБ не тянем
_MAX_CHARS = 60_000                 # и в LLM отдаём не больше этого
_TIMEOUT = 20

_UA = ("Mozilla/5.0 (compatible; ir-storyboard/1.0; "
       "+internal research tool)")


class UnsafeUrl(ValueError):
    """URL ведёт не туда, куда можно ходить с сервера (см. check_public_url)."""


@dataclass
class PageContent:
    url: str
    title: str
    text: str
    via: str          # "tavily" | "http" | "" — чем достали, для честности в UI


# ──────────────────────────────────────────────────────────────────────────
# Куда ходить можно
# ──────────────────────────────────────────────────────────────────────────

def check_public_url(url: str) -> None:
    """Пускать сервер только на публичный http(s). Иначе — `UnsafeUrl`.

    Аналитик вставляет произвольную ссылку, а забирает её НАШ сервер, у которого
    есть доступ к внутренней сети (на этой же машине живёт оркестратор). Без
    проверки вставленный `http://127.0.0.1:5000/...` превратил бы форму разбора
    в средство читать внутренние сервисы. Поэтому: только http/https и только
    публичные адреса.

    Оговорка: имя резолвится здесь, а соединение открывается чуть позже — между
    этим возможна подмена DNS. Закрывать это полностью означало бы пинить
    resolved-IP в соединение; для внутреннего инструмента с доверенными
    аналитиками такая проверка соразмерна, и лучше знать её границу, чем считать
    защиту полной.
    """
    p = urlparse((url or "").strip())
    if p.scheme not in ("http", "https"):
        raise UnsafeUrl("Ссылка должна начинаться с http:// или https://")
    host = p.hostname or ""
    if not host:
        raise UnsafeUrl("В ссылке нет адреса хоста")
    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except OSError as e:
        raise UnsafeUrl(f"Не удалось разрешить имя {host}: {e}") from e

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise UnsafeUrl(
                f"{host} резолвится во внутренний адрес ({ip}) — такие ссылки "
                f"сервер не забирает"
            )


# ──────────────────────────────────────────────────────────────────────────
# HTML → текст
# ──────────────────────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.title: str = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._skip_depth == 0:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """`(title, text)` из HTML. Ошибки разбора не роняют: что успели — то и берём."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return parser.title.strip(), text


# ──────────────────────────────────────────────────────────────────────────
# Загрузка
# ──────────────────────────────────────────────────────────────────────────

def _fetch_http(url: str, timeout: int) -> tuple[str, str]:
    """`(title, text)` прямым запросом. Пусто, если это не текстовая страница."""
    import requests

    resp = requests.get(url, timeout=timeout, headers={"User-Agent": _UA},
                        stream=True)
    resp.raise_for_status()
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if ctype and not any(t in ctype for t in ("text/html", "text/plain", "application/xhtml")):
        # PDF и прочие бинарники — это отдельные загрузчики, не наше дело
        return "", ""

    chunks, size = [], 0
    for chunk in resp.iter_content(64 * 1024):
        size += len(chunk)
        if size > _MAX_BYTES:
            break
        chunks.append(chunk)
    raw = b"".join(chunks)
    encoding = resp.encoding or "utf-8"
    html = raw.decode(encoding, errors="replace")
    if "text/plain" in ctype:
        return "", html.strip()
    return html_to_text(html)


def fetch_page(url: str, *, timeout: int = _TIMEOUT,
               max_chars: int = _MAX_CHARS,
               fallback_title: str = "") -> PageContent:
    """Достать текст страницы. Не бросает на сетевых ошибках — возвращает пустой
    `text` и пустой `via`, чтобы аналитик увидел «не смогли» и вставил текст сам.

    `UnsafeUrl` пробрасывается: это не «не получилось», а «так нельзя».
    """
    url = (url or "").strip()
    check_public_url(url)

    title, text, via = "", "", ""

    try:
        tavily_text = llm.extract_page(url)
    except Exception:
        tavily_text = ""
    if tavily_text.strip():
        text, via = tavily_text.strip(), "tavily"

    if not text:
        try:
            title, text = _fetch_http(url, timeout)
            if text:
                via = "http"
        except Exception:
            title, text, via = title, "", ""

    # Заголовок Tavily не отдаёт — если его нет, доберём из HTML первой строкой
    if not title and text:
        first = text.split("\n", 1)[0].strip()
        title = first[:200] if len(first) <= 200 else ""

    return PageContent(
        url=url,
        title=(title or fallback_title or url)[:300],
        text=text[:max_chars],
        via=via,
    )

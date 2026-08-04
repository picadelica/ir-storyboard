"""Мониторинг: watchlist источников, кандидаты на разбор, обзор эпизода.

Роутер не заводит новых каналов и не разбирает ничего сам: «Разобрать» отдаёт URL
существующему YouTube-ингесту (тем же способом, что вкладка Research), а обзор
эпизода читает уже готовую расшифровку из кэша. Долгие вызовы (обход источников,
LLM-обзор) — через общий job-store (`POST …/start` → `GET /api/jobs/{id}`).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.deps import get_conn
from ir_storyboard import digest as digest_mod
from ir_storyboard import verification, watchlist

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


# ── общее ────────────────────────────────────────────────────────────────────

def _check_client(client_id: str, conn) -> None:
    row = conn.execute("SELECT id FROM clients WHERE id = ?", (client_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"client {client_id} not found")


def _actor(request: Request) -> str:
    from backend.main import current_user
    u = current_user(request) or {}
    return str(u.get("name") or u.get("tid") or "")


class JobOut(BaseModel):
    job_id: str
    status: str = "processing"


def _start_job(fn, client_id: str) -> JobOut:
    from backend.main import _start_llm_job
    return JobOut(job_id=_start_llm_job(fn, client_id))


# ── watchlist ────────────────────────────────────────────────────────────────

class WatchlistIn(BaseModel):
    client_id: str
    kind: str                      # youtube_channel | rss | search_query
    config: Dict[str, Any] = {}
    label: str = ""
    speaker_entity_id: Optional[int] = None
    schedule: str = "daily"


@router.post("/watchlist")
def create_watchlist_item(body: WatchlistIn, request: Request, conn=Depends(get_conn)):
    _check_client(body.client_id, conn)
    try:
        item_id = watchlist.add_item(
            conn, body.client_id, body.kind, body.config,
            label=body.label, speaker_entity_id=body.speaker_entity_id,
            schedule=body.schedule, created_by=_actor(request),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return watchlist.get_item(conn, item_id)


@router.get("/watchlist")
def list_watchlist(client_id: str, conn=Depends(get_conn)):
    _check_client(client_id, conn)
    return watchlist.list_items(conn, client_id)


@router.post("/watchlist/{item_id}/pause")
def pause_item(item_id: int, conn=Depends(get_conn)):
    if not watchlist.get_item(conn, item_id):
        raise HTTPException(404, "источник не найден")
    watchlist.set_item_status(conn, item_id, "paused")
    return watchlist.get_item(conn, item_id)


@router.post("/watchlist/{item_id}/resume")
def resume_item(item_id: int, conn=Depends(get_conn)):
    if not watchlist.get_item(conn, item_id):
        raise HTTPException(404, "источник не найден")
    watchlist.set_item_status(conn, item_id, "active")
    return watchlist.get_item(conn, item_id)


@router.delete("/watchlist/{item_id}")
def delete_item(item_id: int, conn=Depends(get_conn)):
    if not watchlist.get_item(conn, item_id):
        raise HTTPException(404, "источник не найден")
    watchlist.delete_item(conn, item_id)
    return {"ok": True}


@router.get("/watchlist/suggestions")
def watchlist_suggestions(client_id: str, conn=Depends(get_conn)):
    """Каналы, с которых уже брали видео этого клиента, но которых нет в мониторинге."""
    _check_client(client_id, conn)
    return watchlist.suggestions(conn, client_id)


# ── проверка источников ──────────────────────────────────────────────────────

class CheckIn(BaseModel):
    client_id: Optional[str] = None
    item_id: Optional[int] = None


@router.post("/check", response_model=JobOut)
def check(body: CheckIn, conn=Depends(get_conn)):
    """Обойти источники (сеть + дешёвый LLM-фильтр по метаданным) фоновым job-ом."""
    if body.item_id:
        item = watchlist.get_item(conn, body.item_id)
        if not item:
            raise HTTPException(404, "источник не найден")
        item_id = body.item_id
        return _start_job(lambda c, _cid: watchlist.check_item(c, item_id), item["client_id"])
    if not body.client_id:
        raise HTTPException(400, "нужен client_id или item_id")
    _check_client(body.client_id, conn)
    return _start_job(lambda c, cid: watchlist.check_client(c, cid), body.client_id)


# ── кандидаты ────────────────────────────────────────────────────────────────

@router.get("/candidates")
def list_candidates(client_id: str, state: Optional[str] = "new", conn=Depends(get_conn)):
    _check_client(client_id, conn)
    return watchlist.list_candidates(conn, client_id, state=state or None)


@router.post("/candidates/{candidate_id}/dismiss")
def dismiss_candidate(candidate_id: int, request: Request, conn=Depends(get_conn)):
    if not watchlist.get_candidate(conn, candidate_id):
        raise HTTPException(404, "кандидат не найден")
    return watchlist.set_candidate_state(conn, candidate_id, "dismissed", actor=_actor(request))


@router.post("/candidates/{candidate_id}/ingest")
def ingest_candidate(candidate_id: int, request: Request, conn=Depends(get_conn)):
    """Отдать кандидата существующему ингесту.

    Сам разбор здесь НЕ запускается: возвращаем URL, аналитик попадает на обычный
    экран YouTube-ингеста с предзаполненной ссылкой (тот же приём, что у Research).
    Кандидат помечается ingesting; в ingested он перейдёт сам, когда после коммита
    появится строка sources с этим URL (watchlist.link_ingested).
    """
    cand = watchlist.get_candidate(conn, candidate_id)
    if not cand:
        raise HTTPException(404, "кандидат не найден")
    row = watchlist.set_candidate_state(conn, candidate_id, "ingesting", actor=_actor(request))
    return {"candidate": row, "client_id": cand["client_id"], "url": cand["norm_url"] or cand["url"]}


# ── обзор эпизода ────────────────────────────────────────────────────────────

class DigestIn(BaseModel):
    client_id: str
    url: str
    speaker_entity_id: Optional[int] = None
    force: bool = False


@router.get("/digests")
def get_digests(client_id: Optional[str] = None, url: Optional[str] = None,
                speaker_entity_id: Optional[int] = None,
                source_id: Optional[int] = None, conn=Depends(get_conn)):
    """Готовый обзор: по source_id (со страницы источника) или по url+спикеру (в превью)."""
    if source_id:
        return digest_mod.digests_for_source(conn, source_id)
    if not (client_id and url):
        raise HTTPException(400, "нужен source_id или client_id+url")
    speaker = digest_mod.resolve_speaker(conn, client_id, speaker_entity_id)
    if not speaker:
        return []
    d = digest_mod.get_digest(conn, watchlist.norm_candidate_url(url), speaker)
    return [d] if d else []


@router.post("/digests/start", response_model=JobOut)
def start_digest(body: DigestIn, conn=Depends(get_conn)):
    """Собрать обзор (LLM + сравнение с прошлыми выступлениями спикера) — job."""
    _check_client(body.client_id, conn)
    url, speaker, force = body.url, body.speaker_entity_id, body.force
    return _start_job(
        lambda c, cid: digest_mod.build_and_store(c, cid, url, speaker, force=force),
        body.client_id,
    )


# ── подсказка «возможный дубль» ──────────────────────────────────────────────

class DupHintItem(BaseModel):
    subsection_id: str
    text: str


class DupHintsIn(BaseModel):
    client_id: str
    items: List[DupHintItem] = []


@router.post("/duplicate-hints")
def duplicate_hints(body: DupHintsIn, conn=Depends(get_conn)):
    """Похожие активные факты той же ячейки для карточек превью (механический скоринг)."""
    _check_client(body.client_id, conn)
    return verification.duplicate_hints(
        conn, body.client_id, [i.model_dump() for i in body.items]
    )

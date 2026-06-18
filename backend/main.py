"""FastAPI backend for IR Storyboard.

Wraps the ir_storyboard Python module as a REST API.

Run:
    cd ir-storyboard
    uvicorn backend.main:app --reload --port 8080
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import yaml
from fastapi import FastAPI, File, Form, HTTPException, Depends, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, model_validator

# Make sure the ir_storyboard package is importable when running from repo root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ir_storyboard import backup, brief, db, matrix, outputs, seed, verification
from ir_storyboard.archive import lookup_snapshot, enqueue_save
from ir_storyboard.cycles import run_event, run_quarterly, run_weekly
from ir_storyboard.llm import web_search, classify_facts_batch
from ir_storyboard.models import LAYERS, ALL_CHANNELS, subsection_by_id, layer_by_id
from ir_storyboard.workitems import synthesize_work_items


app = FastAPI(title="IR Storyboard API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend import auth  # noqa: E402

_AUTH_PUBLIC = {"/api/health"}


@app.on_event("startup")
def _start_auth_poller():
    auth.start_poller()


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    """Gate /api/* behind a Telegram-group session when auth is configured.
    /api/health and /api/auth/* stay open; everything else needs a valid cookie."""
    if auth.enabled():
        p = request.url.path
        if p.startswith("/api/") and p not in _AUTH_PUBLIC and not p.startswith("/api/auth/"):
            if not auth.verify_session(request.cookies.get(auth.COOKIE, "")):
                return JSONResponse({"detail": "auth required"}, status_code=401)
    return await call_next(request)


@app.post("/api/auth/start")
def auth_start():
    if not auth.enabled():
        raise HTTPException(400, "auth not configured")
    token = auth.create_login_token()
    bu = auth.bot_username()
    return {"token": token, "bot_username": bu, "deep_link": f"https://t.me/{bu}?start={token}"}


@app.get("/api/auth/status")
def auth_status(token: str, response: Response):
    tok = auth.get_login_token(token)
    if not tok:
        return {"status": "expired"}
    if tok["status"] == "approved":
        auth.consume_login_token(token)
        response.set_cookie(
            auth.COOKIE, auth.issue_session(tok["tid"], tok["name"]),
            httponly=True, samesite="lax", max_age=auth.SESSION_TTL, path="/",
        )
        return {"status": "approved", "user": {"name": tok["name"], "tid": tok["tid"]}}
    return {"status": tok["status"]}


@app.post("/api/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request):
    if not auth.enabled():
        return {"name": "dev", "tid": 0, "auth": False}
    data = auth.verify_session(request.cookies.get(auth.COOKIE, ""))
    if not data:
        raise HTTPException(401, "not authenticated")
    return {**data, "auth": True}


# ---------- DB dependency ----------

def get_conn() -> sqlite3.Connection:
    conn = db.connect()
    db.init_schema(conn)
    matrix.seed_layers(conn)
    try:
        yield conn
    finally:
        conn.close()


# ---------- pydantic schemas ----------

class ClientOut(BaseModel):
    id: str
    name: str
    sector: Optional[str] = None
    one_liner: Optional[str] = None
    founder_name: Optional[str] = None
    founder_handle: Optional[str] = None
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None
    tone_preset: Optional[str] = None
    created_at: Optional[str] = None
    created_by: Optional[str] = None


class SeedFactIn(BaseModel):
    subsection_id: str
    text: str
    flag: Literal["green", "red", "grey"]
    channel: Literal["online_research", "online_interview", "archival", "offline_interview"]
    source_title: str = ""
    source_url: str = ""
    evidence_snippet: str = ""


class SeedTrackIn(BaseModel):
    name: str
    angle: str = ""
    target_layer_ids: List[int] = []
    target_subsection_ids: List[str] = []
    priority: int = 1


class ClientSeedIn(BaseModel):
    client: ClientOut
    founder_name: str = ""
    founder_handle: str = ""
    aliases: List[str] = []
    initial_quarter: Optional[str] = None
    seed_facts: List[SeedFactIn] = []
    seed_tracks: List[SeedTrackIn] = []
    notes: str = ""


class ClientSeedYamlIn(BaseModel):
    yaml_content: str


class SeedImportResult(BaseModel):
    client_id: str
    fact_count: int
    source_count: int
    track_count: int


class WorkItemOut(BaseModel):
    id: int
    client_id: str
    type: str
    subsection_id: Optional[str] = None
    source_signal: str
    status: str
    assignee: str = ""
    priority: int = 3
    title: str
    rationale: str = ""
    suggested_channel: Optional[str] = None
    related_track_id: Optional[int] = None
    related_fact_id: Optional[int] = None
    due_date: Optional[str] = None
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    notes: str = ""


class WorkItemCreate(BaseModel):
    type: Literal["fill_gap", "discover", "verify", "deepen",
                  "interview", "adjacent", "cross_ref"]
    subsection_id: Optional[str] = None
    source_signal: Literal["empty_cells", "known_gaps", "thin_coverage",
                           "low_confidence", "manual", "track_alignment", "contradiction"] = "manual"
    title: str
    rationale: str = ""
    suggested_channel: Optional[str] = None
    related_track_id: Optional[int] = None
    priority: int = 3
    assignee: str = ""
    due_date: Optional[str] = None
    notes: str = ""


class WorkItemUpdate(BaseModel):
    status: Optional[Literal["queued", "in_progress", "needs_review",
                             "done", "blocked", "cancelled"]] = None
    assignee: Optional[str] = None
    priority: Optional[int] = None
    due_date: Optional[str] = None
    notes: Optional[str] = None
    related_fact_id: Optional[int] = None


class SynthesizeResult(BaseModel):
    created: List[int]
    skipped: int


class SubsectionOut(BaseModel):
    id: str
    name: str
    sort_order: int


class LayerOut(BaseModel):
    id: int
    name: str
    intimacy: int
    primary_channels: List[str]
    subsections: List[SubsectionOut]


class CellSummaryOut(BaseModel):
    subsection_id: str
    subsection_name: str
    layer_id: int
    layer_name: str
    intimacy: int
    n_green: int
    n_red: int
    n_grey: int
    last_update: Optional[str] = None
    channels: List[str] = []


class FactOut(BaseModel):
    id: int
    text: str
    flag: str
    confidence: float
    captured_at: str
    evidence_snippet: Optional[str] = None
    source_channel: Optional[str] = None
    source_title: Optional[str] = None
    source_url: Optional[str] = None
    source_archive_url: Optional[str] = None
    ingest_audit_id: Optional[str] = None
    rationale: str = ""
    created_by: Optional[str] = None
    snippet_start_sec: Optional[float] = None
    ingest_kind: Optional[str] = None
    audio_sha: Optional[str] = None
    verification: str = "unverified"
    verification_note: str = ""
    entity: str = ""
    state: str = "active"
    n_sources: int = 1   # corroboration: 1 (primary) + folded-in sources


class FactCreate(BaseModel):
    text: str
    flag: Literal["green", "red", "grey"]
    channel: Literal["online_research", "online_interview", "archival", "offline_interview"]
    source_title: str = ""
    source_url: str = ""
    evidence_snippet: str = ""
    confidence: float = 1.0
    rationale: Optional[str] = None

    @model_validator(mode="after")
    def _check_provenance(self):
        try:
            matrix.validate_provenance(
                self.channel, self.source_url,
                self.evidence_snippet, self.source_title, self.flag,
            )
        except ValueError as e:
            raise ValueError(str(e))
        return self


class FactUpdate(BaseModel):
    text: Optional[str] = None
    flag: Optional[str] = Field(default=None, pattern="^(green|red|grey)$")
    confidence: Optional[float] = None
    rationale: Optional[str] = None


class TrackOut(BaseModel):
    id: int
    plan_id: int
    name: str
    angle: Optional[str] = None
    target_layer_ids: List[int]
    target_subsection_ids: List[str]
    priority: int


class TrackCreate(BaseModel):
    name: str
    angle: Optional[str] = ""
    target_layer_ids: List[int]
    target_subsection_ids: List[str]
    priority: int = 1


class ArtifactSummary(BaseModel):
    id: int
    client_id: str
    cycle: str
    title: str
    created_at: str


class ArtifactOut(BaseModel):
    id: int
    client_id: str
    cycle: str
    title: str
    body: str
    meta: dict
    created_at: str


class WeeklyRunIn(BaseModel):
    quarter: str
    week_label: Optional[str] = None
    max_facts: int = 3


class EventRunIn(BaseModel):
    event_text: str
    landed_subsection_id: str
    quarter: Optional[str] = None


class QuarterlyRunIn(BaseModel):
    quarter: str
    traversal: str = "inside_out"
    facts_per_subsection: int = 2


# ---------- meta routes ----------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/layers", response_model=List[LayerOut])
def get_layers():
    return [
        LayerOut(
            id=L.id, name=L.name, intimacy=L.intimacy,
            primary_channels=L.primary_channels,
            subsections=[
                SubsectionOut(id=s.id, name=s.name, sort_order=s.sort_order)
                for s in L.subsections
            ],
        )
        for L in LAYERS
    ]


@app.get("/api/channels")
def get_channels():
    return list(ALL_CHANNELS)


# ---------- clients ----------

def _row_to_fact(row) -> FactOut:
    keys = row.keys()
    source_url = row["source_url"]
    # Don't expose internal:// pseudo-URLs to the frontend — use ingest_audit_id link instead
    if source_url and source_url.startswith("internal://"):
        source_url = None

    ingest_kind = row["ingest_kind"] if "ingest_kind" in keys else None
    # audio_sha: for audio-file facts, the ingest_audit.source_artifact is the
    # canonical 'file://<sha16>' url — strip the scheme so the frontend can hit
    # the audio source/transcript endpoints (which accept sha or sha-prefix).
    audio_sha = None
    if ingest_kind == "audio_file" and "ingest_artifact" in keys:
        artifact = row["ingest_artifact"] or ""
        if artifact.startswith("file://"):
            audio_sha = artifact[len("file://"):]
        elif artifact:
            audio_sha = artifact
    snippet_start_sec = (
        row["snippet_start_sec"] if "snippet_start_sec" in keys else None
    )

    return FactOut(
        id=row["id"], text=row["text"], flag=row["flag"],
        confidence=row["confidence"] or 1.0,
        captured_at=row["captured_at"],
        evidence_snippet=row["evidence_snippet"] if "evidence_snippet" in keys else None,
        source_channel=row["source_channel"],
        source_title=row["source_title"],
        source_url=source_url,
        source_archive_url=row["source_archive_url"] if "source_archive_url" in keys else None,
        ingest_audit_id=row["ingest_audit_id"] if "ingest_audit_id" in keys else None,
        rationale=(row["rationale"] if "rationale" in keys else "") or "",
        created_by=row["created_by"] if "created_by" in keys else None,
        snippet_start_sec=snippet_start_sec,
        ingest_kind=ingest_kind,
        audio_sha=audio_sha,
        verification=(row["verification"] if "verification" in keys else "unverified") or "unverified",
        verification_note=(row["verification_note"] if "verification_note" in keys else "") or "",
        entity=(row["entity"] if "entity" in keys else "") or "",
        state=(row["state"] if "state" in keys else "active") or "active",
        n_sources=1 + (row["extra_sources"] if "extra_sources" in keys and row["extra_sources"] else 0),
    )


def _row_to_client(row) -> ClientOut:
    d = dict(row)
    if isinstance(d.get("aliases"), str):
        try:
            import json as _json
            d["aliases"] = _json.loads(d["aliases"])
        except Exception:
            d["aliases"] = []
    return ClientOut(**d)


@app.get("/api/clients", response_model=List[ClientOut])
def list_clients(conn=Depends(get_conn)):
    return [_row_to_client(r) for r in matrix.list_clients(conn)]


class PortfolioRow(BaseModel):
    id: str
    name: str
    sector: Optional[str] = None
    covered: int
    total: int
    mine: bool = False


def current_user(request: Request) -> Optional[dict]:
    """Session {tid, name} of the logged-in user, or None when auth is disabled."""
    if not auth.enabled():
        return None
    return auth.verify_session(request.cookies.get(auth.COOKIE, ""))


def current_tid(request: Request) -> Optional[int]:
    """Telegram id of the logged-in user, or None when auth is disabled."""
    u = current_user(request)
    return u.get("tid") if u else None


# NB: must precede /api/clients/{client_id} so "portfolio" isn't read as an id.
@app.get("/api/clients/portfolio", response_model=List[PortfolioRow])
def clients_portfolio(conn=Depends(get_conn), tid: Optional[int] = Depends(current_tid)):
    mine = matrix.my_client_ids(conn, tid) if tid is not None else set()
    return [PortfolioRow(**r, mine=(r["id"] in mine)) for r in matrix.portfolio_summary(conn)]


class MineIn(BaseModel):
    on: bool


@app.put("/api/clients/{client_id}/mine")
def set_client_mine(client_id: str, body: MineIn, conn=Depends(get_conn),
                    tid: Optional[int] = Depends(current_tid)):
    if tid is None:
        raise HTTPException(400, "personal lists require Telegram login")
    matrix.set_client_member(conn, client_id, tid, body.on)
    return {"ok": True, "mine": body.on}


# ---------- brief composer: factology + analyst prompt -> MD/JSON for external LLM ----------

class BriefTemplateOut(BaseModel):
    id: int
    name: str
    material_type: str = ""
    body: str = ""
    created_by: Optional[str] = None
    updated_at: Optional[str] = None


class BriefTemplateIn(BaseModel):
    name: str
    material_type: str = ""
    body: str = ""


class BriefTemplatePatch(BaseModel):
    name: Optional[str] = None
    material_type: Optional[str] = None
    body: Optional[str] = None


class BriefComposeIn(BaseModel):
    template_id: int
    analyst_prompt: str = ""
    flags: Optional[List[str]] = None       # subset of green/red/grey; None = all
    layer_ids: Optional[List[int]] = None   # subset of 1..8; None = all


class BriefComposeOut(BaseModel):
    md: str
    json_bundle: dict
    fact_count: int


@app.get("/api/brief-templates", response_model=List[BriefTemplateOut])
def list_brief_templates(conn=Depends(get_conn)):
    return [BriefTemplateOut(**t) for t in brief.list_templates(conn)]


@app.post("/api/brief-templates", response_model=BriefTemplateOut)
def create_brief_template(body: BriefTemplateIn, conn=Depends(get_conn),
                          user: Optional[dict] = Depends(current_user)):
    t = brief.create_template(conn, body.name, body.material_type, body.body,
                              created_by=(user.get("name") if user else None))
    return BriefTemplateOut(**t)


@app.put("/api/brief-templates/{tid}", response_model=BriefTemplateOut)
def update_brief_template(tid: int, body: BriefTemplatePatch, conn=Depends(get_conn)):
    t = brief.update_template(conn, tid, name=body.name,
                              material_type=body.material_type, body=body.body)
    if not t:
        raise HTTPException(404, "template not found")
    return BriefTemplateOut(**t)


@app.delete("/api/brief-templates/{tid}")
def delete_brief_template(tid: int, conn=Depends(get_conn)):
    brief.delete_template(conn, tid)
    return {"ok": True}


@app.post("/api/clients/{client_id}/brief", response_model=BriefComposeOut)
def compose_brief(client_id: str, body: BriefComposeIn, conn=Depends(get_conn)):
    client_row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    if not client_row:
        raise HTTPException(404, "client not found")
    template = brief.get_template(conn, body.template_id)
    if not template:
        raise HTTPException(404, "template not found")

    client = {"id": client_row["id"], "name": client_row["name"],
              "sector": client_row["sector"] if "sector" in client_row.keys() else None}
    factology = brief.collect_factology(conn, client_id, flags=body.flags, layer_ids=body.layer_ids)
    fact_count = sum(len(s["facts"]) for L in factology for s in L["subsections"])
    return BriefComposeOut(
        md=brief.render_md(client, template, body.analyst_prompt, factology),
        json_bundle=brief.render_json(client, template, body.analyst_prompt, factology),
        fact_count=fact_count,
    )


@app.get("/api/clients/{client_id}", response_model=ClientOut)
def get_client(client_id: str, conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    if not row:
        raise HTTPException(404, "client not found")
    return _row_to_client(row)


class MethodologyCellOut(BaseModel):
    subsection_id: str
    subsection_name: str
    layer_id: int
    layer_name: str
    sort_order: int
    description: str


class MethodologyUpdateIn(BaseModel):
    description: str


class TonePresetOut(BaseModel):
    id: str
    label: str
    description: str
    sample: str


@app.get("/api/methodology", response_model=List[MethodologyCellOut])
def list_methodology(conn=Depends(get_conn)):
    rows = conn.execute(
        """SELECT s.id AS subsection_id, s.name AS subsection_name,
                  s.sort_order, COALESCE(s.description, '') AS description,
                  l.id AS layer_id, l.name AS layer_name
             FROM subsections s
             JOIN layers l ON l.id = s.layer_id
             ORDER BY l.id, s.sort_order, s.id"""
    ).fetchall()
    return [MethodologyCellOut(**dict(r)) for r in rows]


@app.patch("/api/methodology/{subsection_id}", response_model=MethodologyCellOut)
def update_methodology(subsection_id: str, body: MethodologyUpdateIn,
                        conn=Depends(get_conn)):
    try:
        matrix.update_subsection_description(conn, subsection_id, body.description)
    except ValueError as e:
        raise HTTPException(404, str(e))
    row = conn.execute(
        """SELECT s.id AS subsection_id, s.name AS subsection_name,
                  s.sort_order, COALESCE(s.description, '') AS description,
                  l.id AS layer_id, l.name AS layer_name
             FROM subsections s JOIN layers l ON l.id = s.layer_id
             WHERE s.id = ?""",
        (subsection_id,),
    ).fetchone()
    return MethodologyCellOut(**dict(row))


@app.get("/api/tone-presets", response_model=List[TonePresetOut])
def list_tone_presets():
    from ir_storyboard.prompts import TONE_PRESETS
    return [
        TonePresetOut(id=p.id, label=p.label, description=p.description, sample=p.sample)
        for p in TONE_PRESETS
    ]


class ClientMethodologyCellOut(BaseModel):
    subsection_id: str
    subsection_name: str
    layer_id: int
    layer_name: str
    sort_order: int
    description: str          # global description (read-only here; edit in /methodology)
    client_note: str          # per-client additive note


class ClientMethodologyUpdateIn(BaseModel):
    note: str


@app.get("/api/clients/{client_id}/methodology",
         response_model=List[ClientMethodologyCellOut])
def list_client_methodology(client_id: str, conn=Depends(get_conn)):
    _check_client(client_id, conn)
    notes = matrix.get_client_subsection_notes(conn, client_id)
    rows = conn.execute(
        """SELECT s.id AS subsection_id, s.name AS subsection_name,
                  s.sort_order, COALESCE(s.description, '') AS description,
                  l.id AS layer_id, l.name AS layer_name
             FROM subsections s JOIN layers l ON l.id = s.layer_id
             ORDER BY l.id, s.sort_order, s.id"""
    ).fetchall()
    return [
        ClientMethodologyCellOut(
            **dict(r),
            client_note=notes.get(r["subsection_id"], ""),
        )
        for r in rows
    ]


@app.patch("/api/clients/{client_id}/methodology/{subsection_id}",
           response_model=ClientMethodologyCellOut)
def update_client_methodology(client_id: str, subsection_id: str,
                                body: ClientMethodologyUpdateIn,
                                conn=Depends(get_conn)):
    _check_client(client_id, conn)
    matrix.set_client_subsection_note(conn, client_id, subsection_id, body.note)
    row = conn.execute(
        """SELECT s.id AS subsection_id, s.name AS subsection_name,
                  s.sort_order, COALESCE(s.description, '') AS description,
                  l.id AS layer_id, l.name AS layer_name
             FROM subsections s JOIN layers l ON l.id = s.layer_id
             WHERE s.id = ?""",
        (subsection_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Unknown subsection_id: {subsection_id}")
    return ClientMethodologyCellOut(**dict(row), client_note=body.note.strip())


@app.post("/api/clients", response_model=ClientOut)
def upsert_client(c: ClientOut, conn=Depends(get_conn)):
    matrix.upsert_client(
        conn, c.id, c.name,
        sector=c.sector or "", one_liner=c.one_liner or "",
        founder_name=c.founder_name or "", founder_handle=c.founder_handle or "",
        aliases=c.aliases or [], notes=c.notes or "",
        tone_preset=c.tone_preset,
    )
    matrix.ensure_full_grid(conn, c.id)
    row = conn.execute("SELECT * FROM clients WHERE id=?", (c.id,)).fetchone()
    return _row_to_client(row) if row else c


class ClientPatch(BaseModel):
    name: Optional[str] = None
    sector: Optional[str] = None
    one_liner: Optional[str] = None
    founder_name: Optional[str] = None
    founder_handle: Optional[str] = None
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None
    tone_preset: Optional[str] = None


@app.patch("/api/clients/{client_id}", response_model=ClientOut)
def patch_client(client_id: str, u: ClientPatch, conn=Depends(get_conn)):
    row = conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "client not found")

    updates = u.model_dump(exclude_unset=True)
    if not updates:
        full = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
        return _row_to_client(full)

    sets: List[str] = []
    params: List[Any] = []
    for field, value in updates.items():
        if field == "aliases":
            sets.append("aliases=?")
            params.append(json.dumps(value or []))
        else:
            sets.append(f"{field}=?")
            params.append(value)

    params.append(client_id)
    conn.execute(f"UPDATE clients SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()

    full = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    return _row_to_client(full)


class ClearClientDataOut(BaseModel):
    deleted: dict
    backup: Optional[dict] = None
    full_db_backup: Optional[str] = None


def _backups_dir() -> Path:
    """Backups root, overridable via IR_BACKUPS_DIR (defaults to data/backups)."""
    import os
    override = os.environ.get("IR_BACKUPS_DIR")
    return Path(override) if override else backup.default_backups_dir()


@app.delete(
    "/api/clients/{client_id}/data",
    response_model=ClearClientDataOut,
    summary="Wipe all client-scoped data (facts, sources, ingest, work, plans, "
            "artifacts, notes) and reset the matrix to empty cells. Keeps the "
            "client row and the shared (sha/video-keyed) transcript caches. "
            "Takes an automatic per-client JSON backup AND a full-DB gzip "
            "snapshot before deleting — the backup is mandatory, the wipe is "
            "aborted if it fails.",
)
def clear_client_data(client_id: str, conn=Depends(get_conn)):
    _check_client(client_id, conn)

    backups_dir = _backups_dir()

    # ── Mandatory backup BEFORE any destructive work ──────────────────────────
    # If either the per-client JSON snapshot or the full-DB snapshot fails, abort
    # the whole operation — never delete without a recovery path.
    try:
        snapshot = backup.snapshot_client(conn, client_id)
        backup_meta = backup.write_backup(client_id, snapshot, backups_dir)
        full_db_path = backup.backup_full_db(
            db.DEFAULT_DB_PATH, backups_dir, client_id=client_id
        )
    except Exception as e:
        raise HTTPException(
            500, f"Backup failed — clear aborted (no data was deleted): {e}"
        )

    # ── Purge in one transaction (commit only at the very end) ─────────────────
    try:
        deleted = backup._purge_client(conn, client_id)
        conn.commit()
    except Exception as e:  # pragma: no cover - defensive rollback
        conn.rollback()
        raise HTTPException(500, f"Failed to clear client data: {e}")

    return ClearClientDataOut(
        deleted=deleted,
        backup=backup_meta,
        full_db_backup=str(full_db_path),
    )


class BackupMeta(BaseModel):
    id: str
    created_at: Optional[str] = None
    path: str
    counts: dict
    size_bytes: int


@app.get("/api/clients/{client_id}/backups", response_model=List[BackupMeta])
def list_client_backups(client_id: str, conn=Depends(get_conn)):
    _check_client(client_id, conn)
    return backup.list_backups(client_id, _backups_dir())


class RestoreIn(BaseModel):
    backup_id: str


class RestoreOut(BaseModel):
    restored: dict


@app.post("/api/clients/{client_id}/restore", response_model=RestoreOut)
def restore_client_data(client_id: str, body: RestoreIn, conn=Depends(get_conn)):
    _check_client(client_id, conn)
    snapshot = backup.read_backup(client_id, body.backup_id, _backups_dir())
    if snapshot is None:
        raise HTTPException(404, f"Backup '{body.backup_id}' not found")
    try:
        restored = backup.restore_client(conn, client_id, snapshot)
    except Exception as e:  # pragma: no cover - defensive rollback inside restore
        raise HTTPException(500, f"Restore failed (rolled back): {e}")
    return RestoreOut(restored=restored)


def _do_import_seed(conn, client_id: str, seed: ClientSeedIn) -> SeedImportResult:
    """Core import logic shared by JSON and YAML endpoints."""
    c = seed.client
    matrix.upsert_client(
        conn, client_id, c.name,
        sector=c.sector or "", one_liner=c.one_liner or "",
        founder_name=seed.founder_name or c.founder_name or "",
        founder_handle=seed.founder_handle or c.founder_handle or "",
        aliases=seed.aliases or c.aliases or [],
        notes=seed.notes or c.notes or "",
    )
    matrix.ensure_full_grid(conn, client_id)

    fact_count = 0
    source_count = 0
    for sf in seed.seed_facts:
        src_id = matrix.add_source(conn, channel=sf.channel,
                                   title=sf.source_title, url=sf.source_url)
        matrix.add_fact(conn, client_id=client_id, subsection_id=sf.subsection_id,
                        text=sf.text, flag=sf.flag, source_id=src_id)
        fact_count += 1
        source_count += 1

    track_count = 0
    if seed.initial_quarter and seed.seed_tracks:
        plan_id = matrix.upsert_plan(conn, client_id, seed.initial_quarter)
        for st in seed.seed_tracks:
            matrix.add_track(conn, plan_id=plan_id, name=st.name, angle=st.angle,
                             target_layer_ids=st.target_layer_ids,
                             target_subsection_ids=st.target_subsection_ids,
                             priority=st.priority)
            track_count += 1

    synthesize_work_items(conn, client_id, quarter=seed.initial_quarter)
    return SeedImportResult(client_id=client_id, fact_count=fact_count,
                            source_count=source_count, track_count=track_count)


@app.post("/api/clients/{client_id}/import-seed", response_model=SeedImportResult)
def import_seed(client_id: str, body: ClientSeedIn,
                force: bool = Query(default=False),
                conn=Depends(get_conn)):
    if body.client.id != client_id:
        raise HTTPException(400, "client.id in body must match URL client_id")
    existing_facts = matrix.count_client_facts(conn, client_id)
    if existing_facts > 0 and not force:
        raise HTTPException(409, f"Client already seeded ({existing_facts} facts). Use ?force=true to add more.")
    return _do_import_seed(conn, client_id, body)


@app.post("/api/clients/{client_id}/import-seed-yaml", response_model=SeedImportResult)
def import_seed_yaml(client_id: str, body: ClientSeedYamlIn,
                     force: bool = Query(default=False),
                     conn=Depends(get_conn)):
    try:
        data = yaml.safe_load(body.yaml_content)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"Invalid YAML: {e}")
    try:
        seed = ClientSeedIn(**data)
    except Exception as e:
        raise HTTPException(422, f"YAML structure error: {e}")
    if seed.client.id != client_id:
        raise HTTPException(400, "client.id in YAML must match URL client_id")
    existing_facts = matrix.count_client_facts(conn, client_id)
    if existing_facts > 0 and not force:
        raise HTTPException(409, f"Client already seeded ({existing_facts} facts). Use ?force=true to add more.")
    return _do_import_seed(conn, client_id, seed)


@app.post("/api/clients/{client_id}/seed-accumulator")
def seed_accumulator(client_id: str, conn=Depends(get_conn)):
    """Convenience: load the Accumulator pilot data."""
    if client_id != seed.CLIENT_ID:
        raise HTTPException(400, f"this endpoint seeds {seed.CLIENT_ID} only")
    seed.load_accumulator(conn)
    synthesize_work_items(conn, client_id)
    return {"ok": True, "client_id": seed.CLIENT_ID}


# ---------- matrix view ----------

@app.get("/api/clients/{client_id}/matrix", response_model=List[CellSummaryOut])
def matrix_view(client_id: str, conn=Depends(get_conn)):
    rows = matrix.cell_summary(conn, client_id)
    return [CellSummaryOut(**{k: v for k, v in r.items() if v is not None or k == "last_update"})
            for r in rows]


# ---------- cell facts ----------

@app.get("/api/clients/{client_id}/cells/{subsection_id}/facts",
         response_model=List[FactOut])
def get_cell_facts(client_id: str, subsection_id: str, conn=Depends(get_conn)):
    # the cell drawer is the analyst's triage surface — show rejected facts too
    # (struck-through, restorable); generators read active-only via facts_for_cell default.
    return [_row_to_fact(r)
            for r in matrix.facts_for_cell(conn, client_id, subsection_id, include_rejected=True)]


@app.post("/api/clients/{client_id}/cells/{subsection_id}/facts",
          response_model=FactOut)
def add_cell_fact(client_id: str, subsection_id: str, f: FactCreate,
                  conn=Depends(get_conn), user: Optional[dict] = Depends(current_user)):
    # sync Wayback lookup for online channels
    archive_url = None
    if f.source_url and f.channel in ("online_research", "online_interview", "archival"):
        archive_url = lookup_snapshot(f.source_url)

    src_id = matrix.add_source(conn, channel=f.channel,
                               title=f.source_title or "",
                               url=f.source_url or "",
                               archive_url=archive_url or "")
    try:
        fid = matrix.add_fact(
            conn, client_id=client_id, subsection_id=subsection_id,
            text=f.text, flag=f.flag, source_id=src_id, confidence=f.confidence,
            evidence_snippet=f.evidence_snippet,
            rationale=f.rationale,
            created_by=(user.get("name") if user else None),
        )
    except ValueError as e:
        raise HTTPException(422, str(e))

    # async save if no snapshot found
    if f.source_url and not archive_url and f.channel in ("online_research", "online_interview", "archival"):
        enqueue_save(f.source_url, src_id, db.connect)

    row = matrix.get_fact(conn, fid)
    return _row_to_fact(row)


@app.patch("/api/facts/{fact_id}", response_model=FactOut)
def update_fact(fact_id: int, u: FactUpdate, conn=Depends(get_conn)):
    if matrix.get_fact(conn, fact_id) is None:
        raise HTTPException(404, "fact not found")
    try:
        matrix.update_fact(conn, fact_id, text=u.text, flag=u.flag,
                           confidence=u.confidence, rationale=u.rationale)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _row_to_fact(matrix.get_fact(conn, fact_id))


@app.delete("/api/facts/{fact_id}")
def delete_fact(fact_id: int, conn=Depends(get_conn)):
    if matrix.get_fact(conn, fact_id) is None:
        raise HTTPException(404, "fact not found")
    matrix.delete_fact(conn, fact_id)
    return {"ok": True}


# ---------- fact verification / trust (phase 1) ----------

class AuditFactOut(BaseModel):
    id: int
    verdict: str
    entity: str = ""
    reason: str = ""
    subsection_id: str = ""
    text: str = ""


class AuditOut(BaseModel):
    available: bool
    canonical: dict = {}
    summary: str = ""
    facts: List[AuditFactOut] = []
    n_facts: int = 0
    applied: int = 0


class VerificationIn(BaseModel):
    verification: Literal["unverified", "verified", "suspect", "refuted"]
    note: str = ""
    entity: str = ""


class ClaimIn(BaseModel):
    id: str
    claim: str
    query: str = ""


@app.post("/api/clients/{client_id}/audit", response_model=AuditOut)
def run_audit(client_id: str, conn=Depends(get_conn)):
    """Skeptical entity-conflation audit over the client's research/document facts.
    Applies the verdict (suspect/refuted) onto each flagged fact so the matrix and
    triage screen show it. Does NOT reject anything — that's a human step."""
    res = verification.audit_client(conn, client_id)
    applied = 0
    out_facts: List[AuditFactOut] = []
    for f in res.get("facts", []):
        row = matrix.get_fact(conn, f["id"])
        if row is None:
            continue
        matrix.set_fact_verification(
            conn, f["id"], verification=f["verdict"], note=f["reason"], entity=f["entity"])
        applied += 1
        out_facts.append(AuditFactOut(
            id=f["id"], verdict=f["verdict"], entity=f["entity"], reason=f["reason"],
            subsection_id=row["subsection_id"], text=row["text"]))
    # bootstrap a draft identity anchor (company/founders/decoys) for analyst review
    if res.get("canonical"):
        matrix.bootstrap_entities(conn, client_id, res["canonical"])
    return AuditOut(available=res.get("available", False), canonical=res.get("canonical", {}),
                    summary=res.get("summary", ""), facts=out_facts,
                    n_facts=res.get("n_facts", 0), applied=applied)


@app.post("/api/clients/{client_id}/verify-claims")
def verify_claims_ep(client_id: str, claims: List[ClaimIn], conn=Depends(get_conn)):
    return verification.verify_claims([c.model_dump() for c in claims])


@app.post("/api/facts/{fact_id}/verification", response_model=FactOut)
def set_verification(fact_id: int, v: VerificationIn, conn=Depends(get_conn)):
    if matrix.get_fact(conn, fact_id) is None:
        raise HTTPException(404, "fact not found")
    matrix.set_fact_verification(conn, fact_id, verification=v.verification,
                                 note=v.note, entity=v.entity)
    return _row_to_fact(matrix.get_fact(conn, fact_id))


@app.post("/api/facts/{fact_id}/reject", response_model=FactOut)
def reject_fact(fact_id: int, conn=Depends(get_conn)):
    if matrix.get_fact(conn, fact_id) is None:
        raise HTTPException(404, "fact not found")
    matrix.set_fact_state(conn, fact_id, "rejected")
    return _row_to_fact(matrix.get_fact(conn, fact_id))


@app.post("/api/facts/{fact_id}/restore", response_model=FactOut)
def restore_fact(fact_id: int, conn=Depends(get_conn)):
    if matrix.get_fact(conn, fact_id) is None:
        raise HTTPException(404, "fact not found")
    matrix.set_fact_state(conn, fact_id, "active")
    return _row_to_fact(matrix.get_fact(conn, fact_id))


class ReviewFactOut(BaseModel):
    id: int
    subsection_id: str = ""
    text: str = ""
    flag: str = ""
    verification: str = ""
    verification_note: str = ""
    entity: str = ""


@app.get("/api/clients/{client_id}/review-queue", response_model=List[ReviewFactOut])
def review_queue(client_id: str, conn=Depends(get_conn)):
    """Facts held by the ingest gate (state='review') — awaiting promote/reject."""
    return [ReviewFactOut(**r) for r in matrix.review_facts(conn, client_id)]


@app.post("/api/facts/{fact_id}/promote", response_model=FactOut)
def promote_fact(fact_id: int, conn=Depends(get_conn)):
    """Promote a quarantined fact into the matrix (review → active, verified)."""
    if matrix.get_fact(conn, fact_id) is None:
        raise HTTPException(404, "fact not found")
    matrix.set_fact_verification(conn, fact_id, verification="verified")
    matrix.set_fact_state(conn, fact_id, "active")
    return _row_to_fact(matrix.get_fact(conn, fact_id))


# ---------- dedup / merge (fact-trust phase 3) ----------

class DupFactOut(BaseModel):
    id: int
    text: str = ""


class DupGroupOut(BaseModel):
    subsection_id: str = ""
    keep: int
    ids: List[int] = []
    reason: str = ""
    facts: List[DupFactOut] = []


class DuplicatesOut(BaseModel):
    available: bool
    groups: List[DupGroupOut] = []


class MergeIn(BaseModel):
    keep_id: int
    merge_ids: List[int]


@app.post("/api/clients/{client_id}/find-duplicates", response_model=DuplicatesOut)
def find_duplicates(client_id: str, conn=Depends(get_conn)):
    res = verification.find_duplicate_groups(conn, client_id)
    return DuplicatesOut(available=res.get("available", False),
                         groups=[DupGroupOut(**g) for g in res.get("groups", [])])


@app.post("/api/facts/merge", response_model=FactOut)
def merge_facts_ep(body: MergeIn, conn=Depends(get_conn)):
    """Merge duplicates into keep_id: fold their sources into keep's corroboration,
    soft-reject the rest. Returns the canonical fact with updated n_sources."""
    if matrix.get_fact(conn, body.keep_id) is None:
        raise HTTPException(404, "keep fact not found")
    matrix.merge_facts(conn, body.keep_id, body.merge_ids)
    return _row_to_fact(matrix.get_fact(conn, body.keep_id))


# ---------- identity anchor: company / founder cards (fact-trust phase 1) ----------

class EntityFactOut(BaseModel):
    id: int
    key: str = ""
    value: str = ""
    source_url: str = ""
    source_title: str = ""
    as_of: Optional[str] = None
    verified: bool = False
    sort_order: int = 0


class EntityOut(BaseModel):
    id: int
    kind: str
    name: str
    role: str = ""
    canonical_url: str = ""
    links: dict = {}
    note: str = ""
    confirmed: bool = False
    sort_order: int = 0
    facts: List[EntityFactOut] = []


class EntityIn(BaseModel):
    kind: Literal["company", "founder", "decoy"]
    name: str
    role: str = ""
    canonical_url: str = ""
    links: dict = {}
    note: str = ""
    confirmed: bool = False
    sort_order: int = 0


class EntityPatch(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    canonical_url: Optional[str] = None
    links: Optional[dict] = None
    note: Optional[str] = None
    confirmed: Optional[bool] = None
    sort_order: Optional[int] = None


class EntityFactIn(BaseModel):
    key: str = ""
    value: str = ""
    source_url: str = ""
    source_title: str = ""
    as_of: Optional[str] = None
    verified: bool = False
    sort_order: int = 0


@app.get("/api/clients/{client_id}/entities", response_model=List[EntityOut])
def list_entities(client_id: str, conn=Depends(get_conn)):
    return [EntityOut(**e) for e in matrix.entities_for_client(conn, client_id)]


@app.post("/api/clients/{client_id}/entities", response_model=EntityOut)
def create_entity(client_id: str, e: EntityIn, conn=Depends(get_conn)):
    eid = matrix.add_entity(conn, client_id=client_id, kind=e.kind, name=e.name,
                            role=e.role, canonical_url=e.canonical_url, links=e.links,
                            note=e.note, confirmed=e.confirmed, sort_order=e.sort_order)
    return next(x for x in matrix.entities_for_client(conn, client_id) if x["id"] == eid)


@app.patch("/api/entities/{entity_id}", response_model=dict)
def patch_entity(entity_id: int, p: EntityPatch, conn=Depends(get_conn)):
    matrix.update_entity(conn, entity_id, **p.model_dump(exclude_none=True))
    return {"ok": True}


@app.delete("/api/entities/{entity_id}")
def remove_entity(entity_id: int, conn=Depends(get_conn)):
    matrix.delete_entity(conn, entity_id)
    return {"ok": True}


@app.post("/api/entities/{entity_id}/facts", response_model=EntityFactOut)
def add_entity_fact_ep(entity_id: int, f: EntityFactIn, conn=Depends(get_conn)):
    fid = matrix.add_entity_fact(conn, entity_id=entity_id, key=f.key, value=f.value,
                                 source_url=f.source_url, source_title=f.source_title,
                                 as_of=f.as_of, verified=f.verified, sort_order=f.sort_order)
    row = conn.execute("SELECT id, key, value, source_url, source_title, as_of, verified, sort_order "
                       "FROM entity_facts WHERE id=?", (fid,)).fetchone()
    d = dict(row); d["verified"] = bool(d["verified"])
    return EntityFactOut(**d)


@app.delete("/api/entity-facts/{fact_id}")
def remove_entity_fact(fact_id: int, conn=Depends(get_conn)):
    matrix.delete_entity_fact(conn, fact_id)
    return {"ok": True}


# ---------- plans + tracks ----------

@app.get("/api/clients/{client_id}/plans/{quarter}/tracks",
         response_model=List[TrackOut])
def get_tracks(client_id: str, quarter: str, conn=Depends(get_conn)):
    return [TrackOut(**t) for t in matrix.tracks_for_quarter(conn, client_id, quarter)]


@app.post("/api/clients/{client_id}/plans/{quarter}/tracks",
          response_model=TrackOut)
def add_track(client_id: str, quarter: str, t: TrackCreate,
              conn=Depends(get_conn)):
    plan_id = matrix.upsert_plan(conn, client_id, quarter)
    tid = matrix.add_track(
        conn, plan_id=plan_id, name=t.name, angle=t.angle or "",
        target_layer_ids=t.target_layer_ids,
        target_subsection_ids=t.target_subsection_ids,
        priority=t.priority,
    )
    tracks = matrix.tracks_for_quarter(conn, client_id, quarter)
    track = next(x for x in tracks if x["id"] == tid)
    return TrackOut(**track)


# ---------- cycles ----------

@app.post("/api/clients/{client_id}/cycles/weekly", response_model=ArtifactOut)
def cycle_weekly(client_id: str, body: WeeklyRunIn, conn=Depends(get_conn)):
    try:
        res = run_weekly(conn, client_id=client_id, quarter=body.quarter,
                         week_label=body.week_label, max_facts=body.max_facts)
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    synthesize_work_items(conn, client_id, quarter=body.quarter)
    return _artifact_payload(conn, res["artifact_id"])


@app.post("/api/clients/{client_id}/cycles/event", response_model=ArtifactOut)
def cycle_event(client_id: str, body: EventRunIn, conn=Depends(get_conn)):
    try:
        res = run_event(conn, client_id=client_id, event_text=body.event_text,
                        landed_subsection_id=body.landed_subsection_id,
                        quarter=body.quarter)
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _artifact_payload(conn, res["artifact_id"])


@app.post("/api/clients/{client_id}/cycles/quarterly", response_model=ArtifactOut)
def cycle_quarterly(client_id: str, body: QuarterlyRunIn, conn=Depends(get_conn)):
    try:
        res = run_quarterly(conn, client_id=client_id, quarter=body.quarter,
                            traversal=body.traversal,
                            facts_per_subsection=body.facts_per_subsection)
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _artifact_payload(conn, res["artifact_id"])


# ---------- artifacts ----------

@app.get("/api/clients/{client_id}/artifacts", response_model=List[ArtifactSummary])
def list_artifacts(client_id: str, cycle: Optional[str] = None,
                   conn=Depends(get_conn)):
    return [ArtifactSummary(**dict(r))
            for r in matrix.list_artifacts(conn, client_id=client_id, cycle=cycle)]


@app.get("/api/artifacts/{artifact_id}", response_model=ArtifactOut)
def get_artifact(artifact_id: int, conn=Depends(get_conn)):
    return _artifact_payload(conn, artifact_id)


def _artifact_payload(conn, artifact_id: int) -> ArtifactOut:
    row = matrix.get_artifact(conn, artifact_id)
    if not row:
        raise HTTPException(404, "artifact not found")
    return ArtifactOut(
        id=row["id"], client_id=row["client_id"], cycle=row["cycle"],
        title=row["title"], body=row["body"],
        meta=json.loads(row["meta"] or "{}"),
        created_at=row["created_at"],
    )


# ---------- analyst outputs ----------

def _row_to_work_item(row) -> WorkItemOut:
    d = dict(row)
    return WorkItemOut(
        id=d["id"], client_id=d["client_id"], type=d["type"],
        subsection_id=d.get("subsection_id"),
        source_signal=d["source_signal"], status=d["status"],
        assignee=d.get("assignee") or "",
        priority=d.get("priority") or 3,
        title=d["title"],
        rationale=d.get("rationale") or "",
        suggested_channel=d.get("suggested_channel"),
        related_track_id=d.get("related_track_id"),
        related_fact_id=d.get("related_fact_id"),
        due_date=d.get("due_date"),
        created_at=d["created_at"],
        updated_at=d["updated_at"],
        completed_at=d.get("completed_at"),
        notes=d.get("notes") or "",
    )


# ---------- work items ----------

@app.get("/api/clients/{client_id}/work-items", response_model=List[WorkItemOut])
def list_work_items(client_id: str,
                    status: Optional[List[str]] = Query(default=None),
                    assignee: Optional[str] = None,
                    type: Optional[List[str]] = Query(default=None),
                    subsection_id: Optional[str] = None,
                    conn=Depends(get_conn)):
    q = "SELECT * FROM work_items WHERE client_id=?"
    params: list = [client_id]
    if status:
        q += f" AND status IN ({','.join('?'*len(status))})"
        params.extend(status)
    if assignee:
        q += " AND assignee=?"
        params.append(assignee)
    if type:
        q += f" AND type IN ({','.join('?'*len(type))})"
        params.extend(type)
    if subsection_id:
        q += " AND subsection_id=?"
        params.append(subsection_id)
    q += " ORDER BY priority ASC, created_at DESC"
    return [_row_to_work_item(r) for r in conn.execute(q, params).fetchall()]


@app.get("/api/work-items/{wid}", response_model=WorkItemOut)
def get_work_item(wid: int, conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM work_items WHERE id=?", (wid,)).fetchone()
    if not row:
        raise HTTPException(404, "work item not found")
    return _row_to_work_item(row)


@app.post("/api/clients/{client_id}/work-items", response_model=WorkItemOut)
def create_work_item(client_id: str, body: WorkItemCreate, conn=Depends(get_conn)):
    cur = conn.execute(
        """INSERT INTO work_items
            (client_id, type, subsection_id, source_signal, title, rationale,
             suggested_channel, related_track_id, priority, assignee, due_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (client_id, body.type, body.subsection_id, body.source_signal,
         body.title, body.rationale, body.suggested_channel, body.related_track_id,
         body.priority, body.assignee, body.due_date, body.notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM work_items WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row_to_work_item(row)


@app.patch("/api/work-items/{wid}", response_model=WorkItemOut)
def update_work_item(wid: int, body: WorkItemUpdate, conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM work_items WHERE id=?", (wid,)).fetchone()
    if not row:
        raise HTTPException(404, "work item not found")
    sets, params = ["updated_at=CURRENT_TIMESTAMP"], []
    if body.status is not None:
        sets.append("status=?"); params.append(body.status)
        if body.status == "done":
            sets.append("completed_at=CURRENT_TIMESTAMP")
    if body.assignee is not None:
        sets.append("assignee=?"); params.append(body.assignee)
    if body.priority is not None:
        sets.append("priority=?"); params.append(body.priority)
    if body.due_date is not None:
        sets.append("due_date=?"); params.append(body.due_date)
    if body.notes is not None:
        sets.append("notes=?"); params.append(body.notes)
    if body.related_fact_id is not None:
        sets.append("related_fact_id=?"); params.append(body.related_fact_id)
    params.append(wid)
    conn.execute(f"UPDATE work_items SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    return _row_to_work_item(conn.execute("SELECT * FROM work_items WHERE id=?", (wid,)).fetchone())


@app.post("/api/clients/{client_id}/work-items/synthesize", response_model=SynthesizeResult)
def synthesize(client_id: str, quarter: Optional[str] = None, conn=Depends(get_conn)):
    before = conn.execute(
        "SELECT COUNT(*) FROM work_items WHERE client_id=?", (client_id,)
    ).fetchone()[0]
    created = synthesize_work_items(conn, client_id, quarter=quarter)
    after = conn.execute(
        "SELECT COUNT(*) FROM work_items WHERE client_id=?", (client_id,)
    ).fetchone()[0]
    return SynthesizeResult(created=created, skipped=(after - before) - len(created))


@app.get("/api/clients/{client_id}/punch-list")
def get_punch_list(client_id: str, conn=Depends(get_conn)):
    """Punch-list as structured JSON (frontend renders the table itself)."""
    return {
        "empty_cells": [dict(r) for r in matrix.empty_cells(conn, client_id)],
        "cells_with_known_gaps": [
            {
                **dict(r),
                "grey_facts": [
                    {"id": g["id"], "text": g["text"]}
                    for g in matrix.grey_facts_for_cell(conn, client_id, r["subsection_id"])
                ],
            }
            for r in matrix.cells_with_known_gaps(conn, client_id)
        ],
        "thinly_covered": [
            dict(r) for r in matrix.thinly_covered_cells(conn, client_id, min_green=2)
            if (r["n_green"] or 0) >= 1 and (r["n_grey"] or 0) == 0
        ],
    }


@app.get("/api/clients/{client_id}/interview-questions")
def get_interview_questions(client_id: str, conn=Depends(get_conn)):
    md = outputs.interview_questions(conn, client_id=client_id)
    return {"markdown": md}


@app.get("/api/clients/{client_id}/scorecard")
def get_scorecard(client_id: str, conn=Depends(get_conn)):
    summary = matrix.cell_summary(conn, client_id)
    return {"rows": summary,
            "totals": {
                "green": sum(r["n_green"] or 0 for r in summary),
                "red": sum(r["n_red"] or 0 for r in summary),
                "grey": sum(r["n_grey"] or 0 for r in summary),
                "empty_cells": sum(
                    1 for r in summary
                    if (r["n_green"] or 0) == 0
                    and (r["n_red"] or 0) == 0
                    and (r["n_grey"] or 0) == 0
                ),
            }}


# ---------- research & ingest ----------

class SearchHitOut(BaseModel):
    title: str
    url: str
    snippet: str
    suggested_channel: str


class ResearchResult(BaseModel):
    hits: List[SearchHitOut]
    queries_used: List[str]


class FactCandidateOut(BaseModel):
    text: str
    suggested_subsection_id: Optional[str]
    suggested_subsection_name: str
    suggested_layer_id: Optional[int]
    suggested_layer_name: str
    suggested_flag: str
    confidence: float
    rationale: str


class IngestPreviewIn(BaseModel):
    channel: str
    source_url: str = ""
    source_title: str = ""
    text: str


class ResearchPreviewOut(BaseModel):
    channel: str
    source_url: str
    source_title: str
    candidates: List[FactCandidateOut]


class ConfirmFactIn(BaseModel):
    text: str
    subsection_id: str
    flag: Literal["green", "red", "grey"]
    channel: Literal["online_research", "online_interview", "archival", "offline_interview"]
    source_url: str = ""
    source_title: str = ""
    evidence_snippet: str = ""
    confidence: float = 1.0
    rationale: Optional[str] = None


class IngestConfirmIn(BaseModel):
    facts: List[ConfirmFactIn]


class IngestConfirmOut(BaseModel):
    written: List[int]
    skipped: int


def _guess_channel(url: str) -> str:
    url_l = url.lower()
    if any(d in url_l for d in ("youtube.com", "youtu.be", "spotify.com",
                                 "podcasts.apple", "anchor.fm", "podbean")):
        return "online_interview"
    if any(d in url_l for d in ("sec.gov", "wikipedia.org", "books.google",
                                 "archive.org", "jstor.org")):
        return "archival"
    return "online_research"


def _build_queries(name: str, founder: str, sector: str) -> List[tuple[str, str]]:
    """Return list of (query, suggested_channel) tuples."""
    # strip company suffixes for cleaner search
    company = name.replace("AI", "").replace("ai", "").strip() or name
    q: List[tuple[str, str]] = []
    if founder:
        # combine founder + company to avoid wrong people with same surname
        q.append((f'"{founder}" "{company}" interview', "online_interview"))
        q.append((f'"{founder}" "{company}"', "online_research"))
    q.append((f'"{name}" product technology', "online_research"))
    q.append((f'"{name}" investors funding', "online_research"))
    if sector:
        q.append((f'"{name}" {sector} market', "online_research"))
    return q


def _enrich_candidate(cand) -> FactCandidateOut:
    sid = cand.suggested_subsection_id
    sub_name, layer_id, layer_name = "", None, ""
    if sid:
        try:
            sub = subsection_by_id(sid)
            sub_name = sub.name
            layer_id = int(sid.split(".")[0])
            layer_name = layer_by_id(layer_id).name
        except KeyError:
            pass
    return FactCandidateOut(
        text=cand.text,
        suggested_subsection_id=sid,
        suggested_subsection_name=sub_name,
        suggested_layer_id=layer_id,
        suggested_layer_name=layer_name,
        suggested_flag=cand.suggested_flag,
        confidence=cand.confidence,
        rationale=cand.rationale,
    )


@app.post("/api/clients/{client_id}/research", response_model=ResearchResult)
def research_client(client_id: str, conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    if not row:
        raise HTTPException(404, "client not found")
    d = dict(row)
    queries = _build_queries(d.get("name", ""), d.get("founder_name", ""),
                             d.get("sector", ""))
    seen_urls: set = set()
    hits: List[SearchHitOut] = []
    for q, default_channel in queries:
        for hit in web_search(q, max_hits=4):
            if hit.url in seen_urls:
                continue
            seen_urls.add(hit.url)
            channel = _guess_channel(hit.url) or default_channel
            hits.append(SearchHitOut(
                title=hit.title, url=hit.url,
                snippet=hit.snippet, suggested_channel=channel,
            ))
    return ResearchResult(hits=hits, queries_used=[q for q, _ in queries])


@app.post("/api/clients/{client_id}/ingest/preview", response_model=ResearchPreviewOut)
def research_ingest_preview(client_id: str, body: IngestPreviewIn, conn=Depends(get_conn)):
    """Atomic-fact extraction from a single Research source (article, transcript, etc).

    Uses the dedicated extract_facts_from_research_text — broader prompt than
    LLM-Report (no [N] citation requirement, generous extraction). Honors
    per-client tone preset and methodology notes. L1 is interview-only and is
    excluded for non-interview channels.
    """
    from ir_storyboard.llm import extract_facts_from_research_text
    from ir_storyboard.prompts import get_tone_instruction

    _check_client(client_id, conn)

    text = (body.text or "").strip()
    if not text:
        return ResearchPreviewOut(
            channel=body.channel, source_url=body.source_url,
            source_title=body.source_title, candidates=[],
        )

    # Subsections this channel may fill: L1 is interview-only.
    available_subsections = [
        sub.id for layer in LAYERS for sub in layer.subsections
        if layer.id >= 2 or body.channel in ("offline_interview", "online_interview")
    ]

    tone_preset_id = matrix.get_client_tone_preset(conn, client_id)
    facts = extract_facts_from_research_text(
        text=text,
        source_title=body.source_title or "",
        available_subsections=available_subsections,
        subsection_descriptions=matrix.get_subsection_descriptions(conn),
        client_subsection_notes=matrix.get_client_subsection_notes(conn, client_id),
        tone_instruction=get_tone_instruction(tone_preset_id),
    )

    # Convert ExtractedFact → FactCandidateOut shape used by ResearchView
    candidates: List[FactCandidateOut] = []
    for f in facts:
        sid = f.subsection_id
        try:
            sub = subsection_by_id(sid)
            sub_name = sub.name
            layer_id = int(sid.split(".")[0])
            layer_name = layer_by_id(layer_id).name
        except KeyError:
            continue
        candidates.append(FactCandidateOut(
            text=f.text,
            suggested_subsection_id=sid,
            suggested_subsection_name=sub_name,
            suggested_layer_id=layer_id,
            suggested_layer_name=layer_name,
            suggested_flag=f.flag,
            confidence=f.confidence,
            rationale=(f.raw_paraphrase or "")[:160],
        ))

    return ResearchPreviewOut(
        channel=body.channel,
        source_url=body.source_url,
        source_title=body.source_title,
        candidates=candidates,
    )


@app.post("/api/clients/{client_id}/ingest/confirm", response_model=IngestConfirmOut)
def research_ingest_confirm(client_id: str, body: IngestConfirmIn, conn=Depends(get_conn)):
    written: List[int] = []
    skipped = 0
    for f in body.facts:
        # for online channels use text as evidence_snippet if not provided
        snippet = f.evidence_snippet or (f.text if f.channel in ("online_research", "online_interview", "archival") else "")
        try:
            matrix.validate_provenance(f.channel, f.source_url, snippet,
                                       f.source_title, f.flag)
        except ValueError:
            skipped += 1
            continue
        archive_url = ""
        if f.source_url and f.channel in ("online_research", "online_interview", "archival"):
            archive_url = lookup_snapshot(f.source_url) or ""
        src_id = matrix.add_source(conn, channel=f.channel,
                                   title=f.source_title, url=f.source_url,
                                   archive_url=archive_url)
        try:
            fid = matrix.add_fact(conn, client_id=client_id, subsection_id=f.subsection_id,
                                  text=f.text, flag=f.flag, source_id=src_id,
                                  confidence=f.confidence, evidence_snippet=snippet,
                                  rationale=f.rationale)
        except ValueError as e:
            raise HTTPException(422, str(e))
        if f.source_url and not archive_url and f.channel in ("online_research", "online_interview", "archival"):
            enqueue_save(f.source_url, src_id, db.connect)
        written.append(fid)
    if written:
        synthesize_work_items(conn, client_id)
    return IngestConfirmOut(written=written, skipped=skipped)


@app.get("/api/clients/{client_id}/notebooklm-bundle")
def download_notebooklm_bundle(client_id: str, artifact_ids: str,
                               conn=Depends(get_conn)):
    """Download a NotebookLM-ready markdown bundle.

    Pass `artifact_ids` as a comma-separated list (e.g. ?artifact_ids=12,13,14).
    """
    try:
        ids = [int(x) for x in artifact_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "artifact_ids must be comma-separated ints")
    md = outputs.notebooklm_package(conn, client_id=client_id, artifact_ids=ids)
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="notebooklm_bundle_{client_id}.md"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# LLM Report Ingest endpoints (Task 6)
# ─────────────────────────────────────────────────────────────────────────────

# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ResolvedCitationOut(BaseModel):
    cite_id: int
    canonical_url: str
    title: str
    publisher: str
    channel: str
    classification_reason: str


class ResolvedFactOut(BaseModel):
    text: str
    subsection_id: str
    flag: str
    cite_ids: List[int]
    confidence: float
    raw_paraphrase: str
    evidence_snippet: str
    needs_review: bool
    snippet_source: str
    rationale: str = ""


class IngestPreviewOut(BaseModel):
    audit_id: str
    source_artifact_path: str
    detected_agent: Optional[str]
    sources: List[ResolvedCitationOut]
    facts: List[ResolvedFactOut]
    notes: List[str]
    stats: Dict[str, Any]


class IngestEditIn(BaseModel):
    fact_idx: int
    action: Literal["keep", "edit", "drop"]
    new_text: Optional[str] = None
    new_subsection_id: Optional[str] = None
    new_flag: Optional[str] = None
    new_rationale: Optional[str] = None


class IngestCommitIn(BaseModel):
    preview: IngestPreviewOut
    edits: List[IngestEditIn] = []
    expert_email: str


class IngestCommitOut(BaseModel):
    audit_id: str
    committed_facts: int
    committed_sources: int
    skipped_facts: int
    ingested_at: str
    held_facts: int = 0   # gated to review against the identity anchor


class IngestAuditOut(BaseModel):
    id: str
    client_id: str
    ingest_kind: str
    source_artifact: str
    agent: Optional[str]
    parsed_at: str
    facts_emitted: int
    facts_committed: int
    greys_emitted: int
    channel_warnings: int
    expert_email: str
    confirmed_at: str


# ── Preview endpoint ──────────────────────────────────────────────────────────

_ALLOWED_EXTENSIONS = {".docx", ".md", ".txt", ".pdf"}
_ARTIFACTS_DIR = ROOT / "data" / "llm_reports"


@app.post(
    "/api/clients/{client_id}/ingest/llm-report/preview",
    response_model=IngestPreviewOut,
    summary="Parse LLM report and return preview (no DB writes)",
    description=(
        "Upload a .docx/.md/.pdf LLM deep-research report. "
        "Returns extracted sources and facts for expert review."
    ),
)
def llm_report_ingest_preview(
    client_id: str,
    file: UploadFile = File(...),
    agent_hint: Optional[str] = Form(None),
    conn=Depends(get_conn),
):
    """Preview runs synchronously in-request, so it uses the request-scoped conn."""
    from ir_storyboard.ingest.pipeline import preview_llm_report
    import tempfile, shutil

    suffix = Path(file.filename or "upload.docx").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: {suffix}. Allowed: {_ALLOWED_EXTENSIONS}")

    client = conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone()
    if not client:
        raise HTTPException(404, f"Client '{client_id}' not found")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        preview = preview_llm_report(tmp_path, client_id, conn, agent_hint=agent_hint)
    except HTTPException:
        raise
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(422, f"Failed to parse document: {exc}")

    return IngestPreviewOut(
        audit_id=preview.audit_id,
        source_artifact_path=str(tmp_path),
        detected_agent=preview.detected_agent,
        sources=[ResolvedCitationOut(**s.__dict__) for s in preview.sources],
        facts=[ResolvedFactOut(**f.__dict__) for f in preview.facts],
        notes=preview.notes,
        stats=preview.stats,
    )


# ── Commit endpoint ───────────────────────────────────────────────────────────

@app.post(
    "/api/clients/{client_id}/ingest/llm-report/commit",
    response_model=IngestCommitOut,
    summary="Commit previewed LLM report into the matrix",
    description=(
        "Takes an IngestPreviewOut (from preview endpoint) + expert edits, "
        "writes sources and facts to the matrix. Idempotent — safe to call twice."
    ),
)
def llm_report_ingest_commit(
    client_id: str,
    body: IngestCommitIn,
    conn=Depends(get_conn),
):
    from ir_storyboard.ingest.pipeline import (
        commit_llm_report, IngestPreview,
    )
    from ir_storyboard.ingest.citations import ResolvedCitation
    from ir_storyboard.ingest.snippet_resolver import ResolvedFact

    client = conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone()
    if not client:
        raise HTTPException(404, f"Client '{client_id}' not found")

    # Reconstruct internal preview from pydantic model
    sources = [
        ResolvedCitation(
            cite_id=s.cite_id,
            canonical_url=s.canonical_url,
            title=s.title,
            publisher=s.publisher,
            channel=s.channel,  # type: ignore[arg-type]
            classification_reason=s.classification_reason,
        )
        for s in body.preview.sources
    ]
    facts = [
        ResolvedFact(
            text=f.text,
            subsection_id=f.subsection_id,
            flag=f.flag,
            cite_ids=f.cite_ids,
            confidence=f.confidence,
            raw_paraphrase=f.raw_paraphrase,
            rationale=f.rationale,
            evidence_snippet=f.evidence_snippet,
            needs_review=f.needs_review,
            snippet_source=f.snippet_source,  # type: ignore[arg-type]
        )
        for f in body.preview.facts
    ]

    preview = IngestPreview(
        audit_id=body.preview.audit_id,
        source_artifact_path=body.preview.source_artifact_path,
        detected_agent=body.preview.detected_agent,
        sources=sources,
        facts=facts,
        notes=body.preview.notes,
        stats=body.preview.stats,
    )

    # Archive source artifact
    artifact_path = _archive_artifact(
        src=Path(body.preview.source_artifact_path),
        client_id=client_id,
        audit_id=body.preview.audit_id,
    )
    if artifact_path:
        preview.source_artifact_path = str(artifact_path)

    edits = [e.model_dump() for e in body.edits]

    try:
        result = commit_llm_report(preview, client_id, conn, body.expert_email, edits)
    except Exception as exc:
        raise HTTPException(422, f"Commit failed: {exc}")

    return IngestCommitOut(
        audit_id=result.audit_id,
        committed_facts=result.committed_facts,
        committed_sources=result.committed_sources,
        skipped_facts=result.skipped_facts,
        ingested_at=result.ingested_at,
        held_facts=result.held_facts,
    )


# ── History endpoint ──────────────────────────────────────────────────────────

@app.get(
    "/api/clients/{client_id}/ingest/llm-report/history",
    response_model=List[IngestAuditOut],
    summary="List past LLM Report Ingest runs for a client",
)
def llm_report_ingest_history(
    client_id: str,
    limit: int = Query(20, ge=1, le=200),
    conn=Depends(get_conn),
):
    rows = conn.execute(
        """SELECT id, client_id, ingest_kind, source_artifact, agent,
                  parsed_at, facts_emitted, facts_committed, greys_emitted,
                  channel_warnings, expert_email, confirmed_at
             FROM ingest_audit
             WHERE client_id = ? AND ingest_kind = 'llm_report'
             ORDER BY confirmed_at DESC
             LIMIT ?""",
        (client_id, limit),
    ).fetchall()
    return [
        IngestAuditOut(
            id=r["id"],
            client_id=r["client_id"],
            ingest_kind=r["ingest_kind"],
            source_artifact=r["source_artifact"],
            agent=r["agent"],
            parsed_at=r["parsed_at"],
            facts_emitted=r["facts_emitted"],
            facts_committed=r["facts_committed"],
            greys_emitted=r["greys_emitted"],
            channel_warnings=r["channel_warnings"],
            expert_email=r["expert_email"],
            confirmed_at=r["confirmed_at"],
        )
        for r in rows
    ]


@app.get(
    "/api/clients/{client_id}/ingest/llm-report/{audit_id}/file",
    summary="Download the original LLM report file for a given audit run",
)
def download_llm_report_file(
    client_id: str,
    audit_id: str,
    conn=Depends(get_conn),
):
    row = conn.execute(
        "SELECT source_artifact FROM ingest_audit WHERE id = ? AND client_id = ?",
        (audit_id, client_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Audit entry not found")

    artifact_path = Path(row["source_artifact"])
    if not artifact_path.exists():
        raise HTTPException(404, f"Report file not found at {artifact_path}")

    suffix = artifact_path.suffix.lower()
    media_types = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".md": "text/markdown; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".pdf": "application/pdf",
    }
    media_type = media_types.get(suffix, "application/octet-stream")
    content = artifact_path.read_bytes()
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact_path.name}"'},
    )


# ── YouTube Ingest — async job store ─────────────────────────────────────────
import threading as _threading

_yt_jobs: dict[str, dict] = {}   # job_id → {status, result, error}
_yt_jobs_lock = _threading.Lock()


def _yt_job_run(job_id: str, client_id: str, url: str, db_path: str) -> None:
    """Background thread: run full preview pipeline and store result."""
    import sqlite3 as _sq
    from ir_storyboard import db as _db
    conn = _db.connect(_db.DEFAULT_DB_PATH if not db_path else _db.Path(db_path))
    _db.init_schema(conn)
    from ir_storyboard.ingest.youtube_pipeline import run_youtube_preview
    try:
        result = run_youtube_preview(client_id, url, conn)
        with _yt_jobs_lock:
            _yt_jobs[job_id] = {"status": "done", "result": result, "error": None}
    except Exception as exc:
        with _yt_jobs_lock:
            _yt_jobs[job_id] = {"status": "error", "result": None, "error": str(exc)}
    finally:
        conn.close()


# ── YouTube Ingest endpoints ──────────────────────────────────────────────────

class YouTubePreviewIn(BaseModel):
    url: str


class YouTubeFactOut(BaseModel):
    text: str
    text_ru: str = ""
    text_en: str = ""
    quote: str = ""
    subsection_id: str
    flag: str
    confidence: float
    evidence_snippet: str
    source_url: str
    snippet_start_sec: float
    snippet_end_sec: float
    needs_review: bool
    layer_warning: bool
    rationale: str = ""


class YouTubeSkippedOut(BaseModel):
    text: str
    text_ru: str = ""
    text_en: str = ""
    quote: str = ""
    subsection_id: str
    flag: str = "green"
    confidence: float = 0.5
    reason: str
    source_url: str
    evidence_snippet: str
    snippet_start_sec: float = 0.0
    snippet_end_sec: float = 0.0
    override_allowed: bool = True
    rationale: str = ""


class YouTubeMetaOut(BaseModel):
    video_id: str
    canonical_url: str
    title: str
    channel_name: str
    duration_sec: int
    upload_date: str
    language: Optional[str]
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    description: str = ""


class YouTubePreviewOut(BaseModel):
    preview_id: str
    meta: YouTubeMetaOut
    facts: List[YouTubeFactOut]
    skipped: List[YouTubeSkippedOut]
    from_cache: bool
    transcribe_cost_usd: Optional[float]
    notes: List[str]
    stats: Dict[str, Any]
    confirmed_at: Optional[str] = None
    video_brief: str = ""
    cell_briefs: Dict[str, str] = {}


class YouTubeCommitIn(BaseModel):
    preview_id: str
    accepted_fact_ids: Optional[List[int]] = None   # None = accept all
    overrides: List[Dict[str, Any]] = []
    expert_email: str = "anonymous@example.com"


class YouTubeCommitOut(BaseModel):
    committed: int
    skipped: int


class YouTubeHistoryOut(BaseModel):
    id: str
    client_id: str
    video_id: Optional[str]
    transcriber: Optional[str]
    transcribe_cost_usd: Optional[float]
    parsed_at: str
    facts_emitted: int
    facts_committed: int
    channel_warnings: int
    expert_email: str
    confirmed_at: Optional[str]


class YouTubeJobOut(BaseModel):
    job_id: str
    status: str   # queued | processing | done | error
    stage: Optional[str] = None   # человекочитаемый этап (для прогресса в UI)
    error: Optional[str] = None
    result: Optional[YouTubePreviewOut] = None


def _preview_out_from_result(result) -> YouTubePreviewOut:
    return YouTubePreviewOut(
        preview_id=result.preview_id,
        meta=YouTubeMetaOut(
            video_id=result.meta.video_id,
            canonical_url=result.meta.canonical_url,
            title=result.meta.title,
            channel_name=result.meta.channel_name,
            duration_sec=result.meta.duration_sec,
            upload_date=result.meta.upload_date,
            language=result.meta.language,
            view_count=getattr(result.meta, "view_count", None),
            like_count=getattr(result.meta, "like_count", None),
            description=getattr(result.meta, "description", "") or "",
        ),
        facts=[
            YouTubeFactOut(
                text=f.text,
                text_ru=f.text_ru,
                text_en=f.text_en,
                quote=f.quote,
                subsection_id=f.subsection_id,
                flag=f.flag,
                confidence=f.confidence,
                evidence_snippet=f.evidence_snippet,
                source_url=f.source_url,
                snippet_start_sec=f.snippet_start_sec,
                snippet_end_sec=f.snippet_end_sec,
                needs_review=f.needs_review,
                layer_warning=f.layer_warning,
                rationale=getattr(f, "rationale", "") or "",
            )
            for f in result.facts
        ],
        skipped=[
            YouTubeSkippedOut(
                text=s.fact.text,
                text_ru=s.fact.text_ru,
                text_en=s.fact.text_en,
                quote=s.fact.quote,
                subsection_id=s.fact.subsection_id,
                flag=s.fact.flag,
                confidence=s.fact.confidence,
                reason=s.reason,
                source_url=s.fact.source_url,
                evidence_snippet=s.fact.evidence_snippet,
                snippet_start_sec=s.fact.snippet_start_sec,
                snippet_end_sec=s.fact.snippet_end_sec,
                override_allowed=s.override_allowed,
                rationale=getattr(s.fact, "rationale", "") or "",
            )
            for s in result.skipped
        ],
        from_cache=result.from_cache,
        transcribe_cost_usd=result.transcribe_cost_usd,
        notes=result.notes,
        stats=result.stats,
        video_brief=getattr(result, "video_brief", "") or "",
        cell_briefs=getattr(result, "cell_briefs", {}) or {},
    )


@app.post(
    "/api/clients/{client_id}/ingest/youtube/preview",
    response_model=YouTubeJobOut,
    summary="Start async YouTube preview job — returns job_id immediately",
)
def youtube_preview(client_id: str, body: YouTubePreviewIn, conn=Depends(get_conn)):
    _check_client(client_id, conn)
    import uuid as _uuid
    from ir_storyboard import db as _db
    job_id = str(_uuid.uuid4())
    with _yt_jobs_lock:
        _yt_jobs[job_id] = {"status": "processing", "result": None, "error": None}
    t = _threading.Thread(
        target=_yt_job_run,
        args=(job_id, client_id, body.url, str(_db.DEFAULT_DB_PATH)),
        daemon=True,
    )
    t.start()
    return YouTubeJobOut(job_id=job_id, status="processing")


def _job_status_out(job_id: str) -> YouTubeJobOut:
    """Shared poll logic for async preview jobs (YouTube + audio uploads)."""
    with _yt_jobs_lock:
        job = _yt_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id} not found")
    if job["status"] == "done" and job["result"] is not None:
        return YouTubeJobOut(
            job_id=job_id,
            status="done",
            result=_preview_out_from_result(job["result"]),
        )
    if job["status"] == "error":
        return YouTubeJobOut(job_id=job_id, status="error", error=job["error"])
    return YouTubeJobOut(
        job_id=job_id, status="processing", stage=job.get("stage"),
    )


@app.get(
    "/api/clients/{client_id}/ingest/youtube/preview/{job_id}",
    response_model=YouTubeJobOut,
    summary="Poll async YouTube preview job status",
)
def youtube_preview_status(client_id: str, job_id: str, conn=Depends(get_conn)):
    return _job_status_out(job_id)


@app.post(
    "/api/clients/{client_id}/ingest/youtube/commit",
    response_model=YouTubeCommitOut,
    summary="Commit previewed YouTube facts into the matrix",
)
def youtube_commit(client_id: str, body: YouTubeCommitIn, conn=Depends(get_conn)):
    _check_client(client_id, conn)
    from ir_storyboard.ingest.youtube_pipeline import run_youtube_commit
    try:
        result = run_youtube_commit(
            preview_id=body.preview_id,
            accepted_fact_ids=body.accepted_fact_ids or [],
            overrides=body.overrides,
            conn=conn,
            expert_email=body.expert_email,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return YouTubeCommitOut(committed=result.committed, skipped=result.skipped)


@app.get(
    "/api/clients/{client_id}/ingest/youtube/preview-by-id/{preview_id}",
    response_model=YouTubePreviewOut,
    summary="Load a previously stored YouTube preview by id (for history reopen)",
)
def youtube_preview_by_id(client_id: str, preview_id: str, conn=Depends(get_conn)):
    _check_client(client_id, conn)
    from ir_storyboard.ingest.youtube_pipeline import _ensure_audit_table_youtube
    import json as _json
    _ensure_audit_table_youtube(conn)
    row = conn.execute(
        """SELECT preview_json, confirmed_at FROM ingest_audit
            WHERE id = ? AND client_id = ? AND ingest_kind = 'youtube'""",
        (preview_id, client_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Preview {preview_id} not found")
    try:
        data = _json.loads(row["preview_json"] or "{}")
    except _json.JSONDecodeError:
        raise HTTPException(500, "Stored preview_json is corrupt")
    meta_dict = data.get("meta") or {}
    return YouTubePreviewOut(
        preview_id=preview_id,
        meta=YouTubeMetaOut(
            video_id=meta_dict.get("video_id") or data.get("video_id") or "",
            canonical_url=meta_dict.get("canonical_url") or data.get("canonical_url") or "",
            title=meta_dict.get("title") or "",
            channel_name=meta_dict.get("channel_name") or "",
            duration_sec=int(meta_dict.get("duration_sec") or 0),
            upload_date=meta_dict.get("upload_date") or "",
            language=meta_dict.get("language"),
            view_count=meta_dict.get("view_count"),
            like_count=meta_dict.get("like_count"),
            description=meta_dict.get("description") or "",
        ),
        facts=[
            YouTubeFactOut(
                text=f.get("text", ""),
                text_ru=f.get("text_ru", ""),
                text_en=f.get("text_en", ""),
                quote=f.get("quote", ""),
                subsection_id=f.get("subsection_id", ""),
                flag=f.get("flag", "green"),
                confidence=float(f.get("confidence", 0.8)),
                evidence_snippet=f.get("evidence_snippet", ""),
                source_url=f.get("source_url", ""),
                snippet_start_sec=float(f.get("snippet_start_sec", 0.0)),
                snippet_end_sec=float(f.get("snippet_end_sec", 0.0)),
                needs_review=bool(f.get("needs_review", False)),
                layer_warning=bool(f.get("layer_warning", False)),
            )
            for f in data.get("facts", [])
        ],
        skipped=[
            YouTubeSkippedOut(
                text=s.get("text", ""),
                text_ru=s.get("text_ru", ""),
                text_en=s.get("text_en", ""),
                quote=s.get("quote", ""),
                subsection_id=s.get("subsection_id", ""),
                flag=s.get("flag", "green"),
                confidence=float(s.get("confidence", 0.5)),
                reason=s.get("reason", ""),
                source_url=s.get("source_url", ""),
                evidence_snippet=s.get("evidence_snippet", ""),
                snippet_start_sec=float(s.get("snippet_start_sec", 0.0)),
                snippet_end_sec=float(s.get("snippet_end_sec", 0.0)),
                override_allowed=bool(s.get("override_allowed", True)),
            )
            for s in data.get("skipped", [])
        ],
        from_cache=bool(data.get("from_cache", True)),
        transcribe_cost_usd=data.get("transcribe_cost_usd"),
        notes=data.get("notes", []) or [],
        stats=data.get("stats", {}) or {},
        confirmed_at=row["confirmed_at"],
        video_brief=data.get("video_brief", "") or "",
        cell_briefs=data.get("cell_briefs", {}) or {},
    )


@app.get(
    "/api/clients/{client_id}/ingest/youtube/history",
    response_model=List[YouTubeHistoryOut],
    summary="List past YouTube Ingest runs for a client",
)
def youtube_history(
    client_id: str,
    limit: int = Query(20, ge=1, le=200),
    conn=Depends(get_conn),
):
    _check_client(client_id, conn)
    from ir_storyboard.ingest.youtube_pipeline import _ensure_audit_table_youtube
    _ensure_audit_table_youtube(conn)
    rows = conn.execute(
        """SELECT id, client_id, video_id, transcriber, transcribe_cost_usd,
                  parsed_at, facts_emitted, facts_committed, channel_warnings,
                  expert_email, confirmed_at
             FROM ingest_audit
             WHERE client_id = ? AND ingest_kind = 'youtube'
             ORDER BY parsed_at DESC
             LIMIT ?""",
        (client_id, limit),
    ).fetchall()
    return [
        YouTubeHistoryOut(
            id=r["id"],
            client_id=r["client_id"],
            video_id=r["video_id"],
            transcriber=r["transcriber"],
            transcribe_cost_usd=r["transcribe_cost_usd"],
            parsed_at=r["parsed_at"],
            facts_emitted=r["facts_emitted"],
            facts_committed=r["facts_committed"],
            channel_warnings=r["channel_warnings"],
            expert_email=r["expert_email"],
            confirmed_at=r["confirmed_at"],
        )
        for r in rows
    ]


def _check_client(client_id: str, conn) -> None:
    row = conn.execute("SELECT id FROM clients WHERE id = ?", (client_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"Client '{client_id}' not found")


# ── Audio file Ingest endpoints (same job store + preview/commit contract) ────

_AUDIO_ALLOWED_EXTENSIONS = {".m4a", ".mp3", ".wav", ".ogg", ".aac"}
_AUDIO_MAX_BYTES = 500 * 1024 * 1024   # 500 MB


def _audio_uploads_dir() -> Path:
    import os
    return Path(os.environ.get("AUDIO_UPLOADS_DIR", str(ROOT / "data" / "audio_uploads")))


def _audio_job_run(job_id: str, client_id: str, file_path: str, title: str,
                   sha256_hex: str, db_path: str) -> None:
    """Background thread: run full audio preview pipeline and store result."""
    from ir_storyboard import db as _db
    conn = _db.connect(_db.DEFAULT_DB_PATH if not db_path else _db.Path(db_path))
    _db.init_schema(conn)
    from ir_storyboard.ingest.audio_pipeline import run_audio_preview

    def _set_stage(stage: str) -> None:
        with _yt_jobs_lock:
            job = _yt_jobs.get(job_id)
            if job is not None and job.get("status") == "processing":
                job["stage"] = stage

    try:
        result = run_audio_preview(
            client_id, Path(file_path), title, conn, sha256_hex=sha256_hex,
            progress_cb=_set_stage,
        )
        with _yt_jobs_lock:
            _yt_jobs[job_id] = {"status": "done", "result": result, "error": None}
    except Exception as exc:
        with _yt_jobs_lock:
            _yt_jobs[job_id] = {"status": "error", "result": None, "error": str(exc)}
    finally:
        conn.close()


@app.post(
    "/api/clients/{client_id}/ingest/audio/preview",
    response_model=YouTubeJobOut,
    status_code=202,
    summary="Upload an audio file and start async preview job — returns job_id",
)
def audio_preview(
    client_id: str,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    conn=Depends(get_conn),
):
    _check_client(client_id, conn)
    import hashlib as _hashlib
    import shutil as _shutil
    import tempfile as _tempfile
    import uuid as _uuid
    from ir_storyboard import db as _db

    suffix = Path(file.filename or "upload.m4a").suffix.lower()
    if suffix not in _AUDIO_ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Unsupported file type: {suffix}. Allowed: {sorted(_AUDIO_ALLOWED_EXTENSIONS)}",
        )

    # Stream to a temp file while hashing + enforcing the size limit
    hasher = _hashlib.sha256()
    total = 0
    with _tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        while True:
            block = file.file.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > _AUDIO_MAX_BYTES:
                tmp.close()
                tmp_path.unlink(missing_ok=True)
                raise HTTPException(413, "Audio file exceeds the 500 MB limit")
            hasher.update(block)
            tmp.write(block)
    if total == 0:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(400, "Empty file")

    sha = hasher.hexdigest()
    uploads_dir = _audio_uploads_dir()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    dest = uploads_dir / f"{sha}{suffix}"
    if dest.exists():
        # Same content already uploaded — dedup by sha, drop the temp copy
        tmp_path.unlink(missing_ok=True)
    else:
        _shutil.move(str(tmp_path), str(dest))

    job_id = str(_uuid.uuid4())
    with _yt_jobs_lock:
        _yt_jobs[job_id] = {"status": "processing", "result": None, "error": None}
    t = _threading.Thread(
        target=_audio_job_run,
        args=(
            job_id, client_id, str(dest),
            (title or "").strip() or (file.filename or dest.name),
            sha, str(_db.DEFAULT_DB_PATH),
        ),
        daemon=True,
    )
    t.start()
    return YouTubeJobOut(job_id=job_id, status="processing")


@app.get(
    "/api/clients/{client_id}/ingest/audio/preview/{job_id}",
    response_model=YouTubeJobOut,
    summary="Poll async audio preview job status",
)
def audio_preview_status(client_id: str, job_id: str, conn=Depends(get_conn)):
    return _job_status_out(job_id)


@app.post(
    "/api/clients/{client_id}/ingest/audio/commit",
    response_model=YouTubeCommitOut,
    summary="Commit previewed audio-file facts into the matrix",
)
def audio_commit(client_id: str, body: YouTubeCommitIn, conn=Depends(get_conn)):
    _check_client(client_id, conn)
    from ir_storyboard.ingest.audio_pipeline import run_audio_commit
    try:
        result = run_audio_commit(
            preview_id=body.preview_id,
            accepted_fact_ids=body.accepted_fact_ids or [],
            overrides=body.overrides,
            conn=conn,
            expert_email=body.expert_email,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return YouTubeCommitOut(committed=result.committed, skipped=result.skipped)


# ── Audio source file + transcript serving (for the preview player) ───────────

_AUDIO_MEDIA_TYPES = {
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".aac": "audio/aac",
}


class TranscriptSegmentOut(BaseModel):
    text: str
    start: float
    end: float


class AudioTranscriptOut(BaseModel):
    title: str
    duration_sec: int
    segments: List[TranscriptSegmentOut]


@app.get(
    "/api/clients/{client_id}/ingest/audio/source/{sha}",
    summary="Stream the original uploaded audio file (supports HTTP Range)",
)
def audio_source(client_id: str, sha: str, conn=Depends(get_conn)):
    _check_client(client_id, conn)
    # canonical_url carries a 16-char sha prefix; accept prefix OR full sha.
    if not sha or not all(c in "0123456789abcdefABCDEF" for c in sha):
        raise HTTPException(400, "Invalid sha")
    uploads_dir = _audio_uploads_dir()
    matches = sorted(uploads_dir.glob(f"{sha}*")) if uploads_dir.exists() else []
    matches = [p for p in matches if p.is_file()]
    if not matches:
        raise HTTPException(404, "Audio source file not found")
    path = matches[0]
    media_type = _AUDIO_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    # FileResponse handles Accept-Ranges / 206 partial content for seeking.
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get(
    "/api/clients/{client_id}/ingest/audio/transcript/{sha}",
    response_model=AudioTranscriptOut,
    summary="Return the cached transcript (segments) for an uploaded audio file",
)
def audio_transcript(client_id: str, sha: str, conn=Depends(get_conn)):
    _check_client(client_id, conn)
    if not sha or not all(c in "0123456789abcdefABCDEF" for c in sha):
        raise HTTPException(400, "Invalid sha")
    from ir_storyboard.ingest.loaders.transcriber import _ensure_audio_transcripts_table
    _ensure_audio_transcripts_table(conn)
    row = conn.execute(
        "SELECT title, duration_sec, segments_json FROM audio_transcripts "
        "WHERE file_sha256 LIKE ? ORDER BY file_sha256 LIMIT 1",
        (f"{sha}%",),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Transcript not found")
    import json as _json
    raw_segments = _json.loads(row["segments_json"]) or []
    segments = [
        TranscriptSegmentOut(
            text=str(s.get("text", "")),
            start=float(s.get("start", 0.0)),
            end=float(s.get("end", 0.0)),
        )
        for s in raw_segments
    ]
    return AudioTranscriptOut(
        title=row["title"],
        duration_sec=int(row["duration_sec"]),
        segments=segments,
    )


# ── helpers ───────────────────────────────────────────────────────────────────

def _archive_artifact(src: Path, client_id: str, audit_id: str) -> Optional[Path]:
    """Move uploaded file to data/llm_reports/<client_id>/<audit_id>.<ext>."""
    if not src.exists():
        return None
    import shutil
    dest_dir = _ARTIFACTS_DIR / client_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{audit_id}{src.suffix}"
    try:
        shutil.move(str(src), dest)
        return dest
    except Exception:
        return src

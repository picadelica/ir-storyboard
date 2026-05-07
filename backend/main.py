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
from typing import List, Literal, Optional

import yaml
from fastapi import FastAPI, HTTPException, Depends, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator

# Make sure the ir_storyboard package is importable when running from repo root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ir_storyboard import db, matrix, outputs, seed
from ir_storyboard.archive import lookup_snapshot, enqueue_save
from ir_storyboard.cycles import run_event, run_quarterly, run_weekly
from ir_storyboard.models import LAYERS, ALL_CHANNELS


app = FastAPI(title="IR Storyboard API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class FactCreate(BaseModel):
    text: str
    flag: Literal["green", "red", "grey"]
    channel: Literal["online_research", "online_interview", "archival", "offline_interview"]
    source_title: str = ""
    source_url: str = ""
    evidence_snippet: str = ""
    confidence: float = 1.0

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
    return FactOut(
        id=row["id"], text=row["text"], flag=row["flag"],
        confidence=row["confidence"] or 1.0,
        captured_at=row["captured_at"],
        evidence_snippet=row["evidence_snippet"] if "evidence_snippet" in row.keys() else None,
        source_channel=row["source_channel"],
        source_title=row["source_title"],
        source_url=row["source_url"],
        source_archive_url=row["source_archive_url"] if "source_archive_url" in row.keys() else None,
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


@app.get("/api/clients/{client_id}", response_model=ClientOut)
def get_client(client_id: str, conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    if not row:
        raise HTTPException(404, "client not found")
    return _row_to_client(row)


@app.post("/api/clients", response_model=ClientOut)
def upsert_client(c: ClientOut, conn=Depends(get_conn)):
    matrix.upsert_client(
        conn, c.id, c.name,
        sector=c.sector or "", one_liner=c.one_liner or "",
        founder_name=c.founder_name or "", founder_handle=c.founder_handle or "",
        aliases=c.aliases or [], notes=c.notes or "",
    )
    matrix.ensure_full_grid(conn, c.id)
    return c


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
    return [_row_to_fact(r) for r in matrix.facts_for_cell(conn, client_id, subsection_id)]


@app.post("/api/clients/{client_id}/cells/{subsection_id}/facts",
          response_model=FactOut)
def add_cell_fact(client_id: str, subsection_id: str, f: FactCreate,
                  conn=Depends(get_conn)):
    # sync Wayback lookup for online channels
    archive_url = None
    if f.source_url and f.channel in ("online_research", "online_interview", "archival"):
        archive_url = lookup_snapshot(f.source_url)

    src_id = matrix.add_source(conn, channel=f.channel,
                               title=f.source_title or "",
                               url=f.source_url or "",
                               archive_url=archive_url or "")
    fid = matrix.add_fact(
        conn, client_id=client_id, subsection_id=subsection_id,
        text=f.text, flag=f.flag, source_id=src_id, confidence=f.confidence,
        evidence_snippet=f.evidence_snippet,
    )

    # async save if no snapshot found
    if f.source_url and not archive_url and f.channel in ("online_research", "online_interview", "archival"):
        enqueue_save(f.source_url, src_id, db.connect)

    row = matrix.get_fact(conn, fid)
    return _row_to_fact(row)


@app.patch("/api/facts/{fact_id}", response_model=FactOut)
def update_fact(fact_id: int, u: FactUpdate, conn=Depends(get_conn)):
    if matrix.get_fact(conn, fact_id) is None:
        raise HTTPException(404, "fact not found")
    matrix.update_fact(conn, fact_id, text=u.text, flag=u.flag,
                       confidence=u.confidence)
    return _row_to_fact(matrix.get_fact(conn, fact_id))


@app.delete("/api/facts/{fact_id}")
def delete_fact(fact_id: int, conn=Depends(get_conn)):
    if matrix.get_fact(conn, fact_id) is None:
        raise HTTPException(404, "fact not found")
    matrix.delete_fact(conn, fact_id)
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
    res = run_weekly(conn, client_id=client_id, quarter=body.quarter,
                     week_label=body.week_label, max_facts=body.max_facts)
    return _artifact_payload(conn, res["artifact_id"])


@app.post("/api/clients/{client_id}/cycles/event", response_model=ArtifactOut)
def cycle_event(client_id: str, body: EventRunIn, conn=Depends(get_conn)):
    res = run_event(conn, client_id=client_id, event_text=body.event_text,
                    landed_subsection_id=body.landed_subsection_id,
                    quarter=body.quarter)
    return _artifact_payload(conn, res["artifact_id"])


@app.post("/api/clients/{client_id}/cycles/quarterly", response_model=ArtifactOut)
def cycle_quarterly(client_id: str, body: QuarterlyRunIn, conn=Depends(get_conn)):
    res = run_quarterly(conn, client_id=client_id, quarter=body.quarter,
                        traversal=body.traversal,
                        facts_per_subsection=body.facts_per_subsection)
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

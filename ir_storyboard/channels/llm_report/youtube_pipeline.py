"""YouTube Ingest pipeline orchestrator.

Two-phase:
  1. run_youtube_preview(client_id, url, conn) → YouTubePreviewResult
  2. run_youtube_commit(preview_id, accepted_ids, overrides, conn, email) → YouTubeCommitResult
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ... import matrix
from ...llm import extract_facts_from_full_document
from .loaders.youtube_url import normalize_url, fetch_metadata, YouTubeVideoMeta
from .loaders.transcriber import get_transcriber, get_or_transcribe
from .transcript_to_ir import transcript_to_ir
from .citations import extract_citations
from .snippet_anchor import anchor_facts, AnchoredFact
from .layer_guard import guard_layers, SkippedFact


@dataclass
class YouTubePreviewResult:
    preview_id: str                      # ingest_audit.id (UUID)
    meta: YouTubeVideoMeta
    facts: list[AnchoredFact]
    skipped: list[SkippedFact]
    notes: list[str]
    stats: dict[str, int]
    from_cache: bool
    transcribe_cost_usd: Optional[float]


@dataclass
class YouTubeCommitResult:
    committed: int
    skipped: int


# Available subsections for YouTube (L1–L8 all allowed in extractor;
# LayerGuard handles the per-channel restriction)
_ALL_SUBSECTIONS = [
    f"{layer}.{sub}"
    for layer in range(1, 9)
    for sub in range(1, 4)
]


def _normalize_fact_text(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _jaccard(a: str, b: str) -> float:
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _is_duplicate_in_matrix(conn: sqlite3.Connection, client_id: str,
                              subsection_id: str, text: str) -> bool:
    """Check if an equivalent fact already exists in the matrix (Jaccard ≥ 0.85)."""
    norm = _normalize_fact_text(text)
    rows = conn.execute(
        """SELECT f.text FROM facts f
           JOIN cells c ON c.id = f.cell_id
           WHERE c.client_id = ? AND c.subsection_id = ?""",
        (client_id, subsection_id),
    ).fetchall()
    for row in rows:
        existing = _normalize_fact_text(row[0])
        if existing == norm:
            return True
        if _jaccard(norm, existing) >= 0.85:
            return True
    return False


# ── Audit table migration ──────────────────────────────────────────────────────

def _ensure_audit_table_youtube(conn: sqlite3.Connection) -> None:
    """Ensure ingest_audit exists and has youtube-specific columns."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingest_audit (
            id              TEXT PRIMARY KEY,
            client_id       TEXT NOT NULL,
            ingest_kind     TEXT NOT NULL,
            source_artifact TEXT NOT NULL,
            agent           TEXT,
            cite_format     TEXT,
            parsed_at       TIMESTAMP NOT NULL,
            facts_emitted   INTEGER NOT NULL DEFAULT 0,
            facts_committed INTEGER NOT NULL DEFAULT 0,
            greys_emitted   INTEGER NOT NULL DEFAULT 0,
            channel_warnings INTEGER NOT NULL DEFAULT 0,
            expert_email    TEXT NOT NULL DEFAULT '',
            confirmed_at    TIMESTAMP,
            preview_json    TEXT NOT NULL DEFAULT '{}'
        )
    """)
    # Idempotent column additions
    for col_def in [
        ("video_id", "TEXT"),
        ("transcriber", "TEXT"),
        ("transcribe_cost_usd", "REAL"),
        ("transcribe_duration_sec", "INTEGER"),
    ]:
        col_name, col_type = col_def
        try:
            conn.execute(f"ALTER TABLE ingest_audit ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass  # column already exists
    conn.commit()


# ── Preview ────────────────────────────────────────────────────────────────────

def run_youtube_preview(
    client_id: str,
    url: str,
    conn: sqlite3.Connection,
    cache_dir=None,
) -> YouTubePreviewResult:
    """Full pipeline: URL → metadata → transcript → extract → anchor → guard → preview."""
    import uuid
    from pathlib import Path

    _ensure_audit_table_youtube(conn)

    preview_id = str(uuid.uuid4())
    notes: list[str] = []
    stats: dict[str, int] = {
        "facts_emitted": 0,
        "greys": 0,
        "channel_warnings": 0,
        "skipped_layer_guard": 0,
        "duplicates_skipped": 0,
    }

    # Step 1: normalize + metadata
    canonical_url = normalize_url(url)
    meta = fetch_metadata(canonical_url)

    # Step 2: transcribe (or cache hit)
    transcriber = get_transcriber()
    cache_path = Path(cache_dir) if cache_dir else Path("/tmp/ir_youtube_audio")

    row_before = conn.execute(
        "SELECT transcriber FROM youtube_transcripts WHERE video_id = ?",
        (meta.video_id,),
    ).fetchone()
    from_cache = (
        row_before is not None
        and row_before["transcriber"] == transcriber.name
    )

    transcript = get_or_transcribe(meta.video_id, meta, transcriber, conn, cache_dir=cache_path)
    if from_cache:
        notes.append(f"Transcript loaded from cache (transcriber={transcriber.name})")

    # Estimate cost (OpenAI Whisper API = $0.006/min)
    transcribe_cost_usd: Optional[float] = None
    if transcriber.name == "openai-whisper-1":
        transcribe_cost_usd = round((meta.duration_sec / 60.0) * 0.006, 4)

    # Step 3: transcript → IR
    ir = transcript_to_ir(transcript, meta)

    # Step 4: citations
    resolved_citations = extract_citations(ir)
    citation_index = {c.cite_id: c for c in resolved_citations}

    # Step 5: extract facts (transcript-mode)
    content_sections = [(s.heading, s.paragraphs) for s in ir.sections]
    raw_facts = extract_facts_from_full_document(
        sections=content_sections,
        available_subsections=_ALL_SUBSECTIONS,
        citation_index=citation_index,
    )

    # Step 6: anchor
    anchored = anchor_facts(raw_facts, transcript, canonical_url)

    # Step 7: LayerGuard
    allowed, skipped = guard_layers(anchored, "online_interview")
    stats["channel_warnings"] = len(skipped)
    stats["skipped_layer_guard"] = len(skipped)

    # Step 8: dedup vs existing matrix
    deduped: list[AnchoredFact] = []
    for af in allowed:
        if _is_duplicate_in_matrix(conn, client_id, af.subsection_id, af.text):
            stats["duplicates_skipped"] += 1
            notes.append(f"Dedup: '{af.text[:60]}…' already in matrix")
        else:
            deduped.append(af)

    stats["facts_emitted"] = len(deduped) + len(skipped)
    stats["greys"] = sum(1 for f in deduped if f.flag == "grey")

    # Write preview to audit (status=preview, no confirmed_at yet)
    preview_json = json.dumps({
        "preview_id": preview_id,
        "video_id": meta.video_id,
        "canonical_url": canonical_url,
        "facts": [_anchored_to_dict(f) for f in deduped],
        "skipped": [{"text": s.fact.text, "reason": s.reason,
                     "subsection_id": s.fact.subsection_id,
                     "source_url": s.fact.source_url,
                     "evidence_snippet": s.fact.evidence_snippet}
                    for s in skipped],
        "stats": stats,
        "notes": notes,
    })

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO ingest_audit
            (id, client_id, ingest_kind, source_artifact, agent,
             parsed_at, facts_emitted, facts_committed, greys_emitted,
             channel_warnings, expert_email, confirmed_at, preview_json,
             video_id, transcriber, transcribe_cost_usd)
           VALUES (?, ?, 'youtube', ?, ?,
                   ?, ?, 0, ?,
                   ?, '', ?, ?,
                   ?, ?, ?)""",
        (
            preview_id, client_id, canonical_url, transcriber.name,
            now,
            stats["facts_emitted"],
            stats["greys"],
            stats["channel_warnings"],
            now,
            preview_json,
            meta.video_id, transcriber.name, transcribe_cost_usd,
        ),
    )
    conn.commit()

    return YouTubePreviewResult(
        preview_id=preview_id,
        meta=meta,
        facts=deduped,
        skipped=skipped,
        notes=notes,
        stats=stats,
        from_cache=from_cache,
        transcribe_cost_usd=transcribe_cost_usd,
    )


def _anchored_to_dict(af: AnchoredFact) -> dict:
    return {
        "text": af.text,
        "subsection_id": af.subsection_id,
        "flag": af.flag,
        "cite_ids": af.cite_ids,
        "confidence": af.confidence,
        "evidence_snippet": af.evidence_snippet,
        "source_url": af.source_url,
        "snippet_start_sec": af.snippet_start_sec,
        "snippet_end_sec": af.snippet_end_sec,
        "needs_review": af.needs_review,
        "layer_warning": af.layer_warning,
        "segment_idx_start": af.segment_idx_start,
        "segment_idx_end": af.segment_idx_end,
    }


# ── Commit ─────────────────────────────────────────────────────────────────────

def run_youtube_commit(
    preview_id: str,
    accepted_fact_ids: list[int],   # indices into preview.facts list
    overrides: list[dict],          # [{"fact_idx": int, "force_keep": True}]
    conn: sqlite3.Connection,
    expert_email: str = "anonymous@example.com",
) -> YouTubeCommitResult:
    """Write accepted facts to matrix. override forces skipped layer-guard facts in."""
    row = conn.execute(
        "SELECT * FROM ingest_audit WHERE id = ?", (preview_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"No preview found for id={preview_id}")

    preview_data = json.loads(row["preview_json"])
    client_id = row["client_id"]
    canonical_url = preview_data["canonical_url"]
    video_id = preview_data["video_id"]
    all_facts = preview_data["facts"]
    all_skipped = preview_data.get("skipped", [])

    committed = 0
    skipped_count = 0

    # Get or create source row for this video
    existing_src = conn.execute(
        "SELECT id FROM sources WHERE url = ?", (canonical_url,)
    ).fetchone()
    if existing_src:
        source_id = existing_src["id"]
    else:
        source_id = matrix.add_source(
            conn,
            channel="online_interview",
            title=preview_data.get("meta", {}).get("title", "") or "",
            url=canonical_url,
            publisher=preview_data.get("meta", {}).get("channel_name", "") or "",
        )

    # Accepted facts by index
    accepted_set = set(accepted_fact_ids) if accepted_fact_ids else set(range(len(all_facts)))

    for idx, fdict in enumerate(all_facts):
        if idx not in accepted_set:
            skipped_count += 1
            continue

        if _is_duplicate_in_matrix(conn, client_id, fdict["subsection_id"], fdict["text"]):
            skipped_count += 1
            continue

        try:
            fact_id = matrix.add_fact(
                conn,
                client_id=client_id,
                subsection_id=fdict["subsection_id"],
                text=fdict["text"],
                flag=fdict["flag"],
                source_id=source_id,
                confidence=fdict.get("confidence", 0.8),
                evidence_snippet=fdict.get("evidence_snippet", ""),
            )
            conn.execute(
                "UPDATE facts SET ingest_audit_id = ?, source_url = ? WHERE id = ?",
                (preview_id, fdict.get("source_url", ""), fact_id),
            )
            committed += 1
        except Exception:
            skipped_count += 1

    # Handle overrides (force-keep layer-guarded facts)
    override_indices = {o["fact_idx"] for o in overrides if o.get("force_keep")}
    for idx in override_indices:
        if idx < len(all_skipped):
            sdict = all_skipped[idx]
            if _is_duplicate_in_matrix(conn, client_id, sdict["subsection_id"], sdict["text"]):
                skipped_count += 1
                continue
            try:
                fact_id = matrix.add_fact(
                    conn,
                    client_id=client_id,
                    subsection_id=sdict["subsection_id"],
                    text=sdict["text"],
                    flag="green",
                    source_id=source_id,
                    confidence=0.7,
                    evidence_snippet=sdict.get("evidence_snippet", ""),
                )
                conn.execute(
                    "UPDATE facts SET ingest_audit_id = ?, source_url = ? WHERE id = ?",
                    (preview_id, sdict.get("source_url", ""), fact_id),
                )
                committed += 1
            except Exception:
                skipped_count += 1

    # Update audit
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE ingest_audit
           SET facts_committed = ?, expert_email = ?, confirmed_at = ?
           WHERE id = ?""",
        (committed, expert_email, now, preview_id),
    )
    conn.commit()

    return YouTubeCommitResult(committed=committed, skipped=skipped_count)

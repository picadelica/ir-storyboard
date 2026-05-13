"""LLM Report Ingest pipeline — orchestrator.

Two-phase flow:
  1. preview_llm_report(path, client_id, conn) → IngestPreview  (no DB writes)
  2. commit_llm_report(preview, client_id, conn, expert_email) → CommitResult

Commit is idempotent: same file ingested twice produces 0 new rows.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from ... import matrix, db as _db
from ...llm import ExtractedFact, extract_facts_from_llm_report
from ...models import LAYERS
from .citations import ResolvedCitation, extract_citations
from .classifiers.section_to_layer import suggest_subsection, SKIP_SECTION_HINTS
from .snippet_resolver import ResolvedFact, resolve_snippets

# Layers blocked for online_research facts (L1 = 1, L2 = 2, L3 = 3)
_BLOCKED_LAYERS_FOR_WEB = frozenset([1])
# L2/L3 partially allowed (archival + online_interview can fill them)
_WEB_ALLOWED_FOR = frozenset(["archival", "online_interview"])

# Tracking params stripped from URLs for dedup
_TRACKING_PARAMS = frozenset([
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "fbclid", "gclid", "msclkid",
])

# Available subsections (outer layers only — L4-L8 are always available)
_AVAILABLE_SUBSECTIONS = [
    sub.id for layer in LAYERS for sub in layer.subsections
    if layer.id >= 2  # L2-L8 reachable via LLM report
]


@dataclass
class IngestPreview:
    audit_id: str
    source_artifact_path: str
    detected_agent: Optional[str]
    sources: list[ResolvedCitation]
    facts: list[ResolvedFact]
    notes: list[str]
    stats: dict[str, int]


@dataclass
class CommitResult:
    audit_id: str
    committed_facts: int
    committed_sources: int
    skipped_facts: int
    ingested_at: str


# ── URL normalisation (same as citations.py, duplicated to avoid circular import) ─

def _normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
        host = p.netloc.lower().lstrip("www.")
        qs = parse_qs(p.query, keep_blank_values=True)
        clean_qs = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
        new_query = urlencode(clean_qs, doseq=True)
        return urlunparse((p.scheme.lower(), host, p.path.rstrip("/"), p.params, new_query, ""))
    except Exception:
        return url.lower().rstrip("/")


def _normalize_fact_text(text: str) -> str:
    """Normalise fact text for dedup: lower, strip, collapse whitespace, remove numbers in parens."""
    t = text.lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\(\d[\d\s,–-]*\)", "", t)  # remove (6000) / (10K) etc.
    return t.strip()


# ── Preview ───────────────────────────────────────────────────────────────────

def preview_llm_report(
    path: Path,
    client_id: str,
    conn: sqlite3.Connection,
    agent_hint: str | None = None,
) -> IngestPreview:
    """Parse the document and build a preview — no DB writes."""
    from .loaders import load as load_doc

    audit_id = str(uuid.uuid4())
    notes: list[str] = []
    stats: dict[str, int] = {
        "facts_emitted": 0,
        "greys": 0,
        "channel_warnings": 0,
        "sections_processed": 0,
        "sections_skipped": 0,
        "sources_extracted": 0,
    }

    # Step 1: load document
    ir = load_doc(path)
    if agent_hint:
        ir.detected_agent = agent_hint
    notes.extend(ir.parser_notes)

    # Step 2: extract + classify citations
    resolved_citations = extract_citations(ir)
    citation_index: dict[int, ResolvedCitation] = {c.cite_id: c for c in resolved_citations}
    stats["sources_extracted"] = len(resolved_citations)

    # Step 3: extract facts per section
    all_extracted: list[tuple[ResolvedFact, ResolvedCitation | None]] = []

    for section in ir.sections:
        heading_low = section.heading.lower()

        # Skip meta sections
        if any(skip in heading_low for skip in SKIP_SECTION_HINTS):
            stats["sections_skipped"] += 1
            notes.append(f"Skipped section '{section.heading}' (meta/conclusions)")
            continue

        sid = suggest_subsection(section.heading)
        if sid is None:
            stats["sections_skipped"] += 1
            notes.append(f"Section '{section.heading}' not mapped to any subsection — skipped")
            continue

        stats["sections_processed"] += 1
        paragraphs = section.paragraphs
        if section.table_rows:
            for row in section.table_rows:
                paragraphs = paragraphs + [" | ".join(cell for cell in row if cell)]

        extracted: list[ExtractedFact] = extract_facts_from_llm_report(
            section_heading=section.heading,
            section_paragraphs=paragraphs,
            available_subsections=_AVAILABLE_SUBSECTIONS,
            citation_index=citation_index,
        )

        # Resolve snippets (paraphrase MVP)
        resolved = resolve_snippets(extracted, citation_index, mode="paraphrase")

        for rf in resolved:
            layer_id = int(rf.subsection_id.split(".")[0])

            # Find citation for this fact (first cite_id)
            cit: ResolvedCitation | None = None
            for cid in rf.cite_ids:
                cit = citation_index.get(cid)
                if cit:
                    break

            # Check methodological restrictions
            if layer_id in _BLOCKED_LAYERS_FOR_WEB:
                channel = cit.channel if cit else "online_research"
                if channel not in _WEB_ALLOWED_FOR:
                    stats["channel_warnings"] += 1
                    notes.append(
                        f"Skipped fact for L{layer_id} subsection {rf.subsection_id} "
                        f"via {channel} (methodology: L1 blocked for web sources)"
                    )
                    continue

            if layer_id in (2, 3) and cit and cit.channel == "online_research":
                stats["channel_warnings"] += 1
                notes.append(
                    f"Soft warning: L{layer_id} fact via online_research "
                    f"(subsection {rf.subsection_id}) — consider interview confirmation"
                )

            all_extracted.append((rf, cit))
            stats["facts_emitted"] += 1
            if rf.flag == "grey":
                stats["greys"] += 1

    # Collect unique sources actually used
    used_cite_ids: set[int] = set()
    for rf, _ in all_extracted:
        used_cite_ids.update(rf.cite_ids)
    used_sources = [c for c in resolved_citations if c.cite_id in used_cite_ids]

    return IngestPreview(
        audit_id=audit_id,
        source_artifact_path=str(path),
        detected_agent=ir.detected_agent,
        sources=used_sources,
        facts=[rf for rf, _ in all_extracted],
        notes=notes,
        stats=stats,
    )


# ── Commit ────────────────────────────────────────────────────────────────────

def commit_llm_report(
    preview: IngestPreview,
    client_id: str,
    conn: sqlite3.Connection,
    expert_email: str,
    edits: list[dict] | None = None,
) -> CommitResult:
    """Write sources + facts to DB. Idempotent by canonical URL and normalized text."""
    # Apply expert edits to preview facts
    facts_to_commit = _apply_edits(preview.facts, edits or [])

    # Rebuild citation index from preview
    citation_index: dict[int, ResolvedCitation] = {c.cite_id: c for c in preview.sources}

    committed_sources = 0
    committed_facts = 0
    skipped_facts = 0

    # Cache: canonical_url → source_id (to avoid duplicate sources in same commit)
    url_to_source_id: dict[str, int] = {}

    # Pre-load existing sources by canonical URL
    existing_sources = conn.execute("SELECT id, url FROM sources").fetchall()
    for row in existing_sources:
        canon = _normalize_url(row["url"] or "")
        if canon:
            url_to_source_id[canon] = row["id"]

    for rf in facts_to_commit:
        # Find citation for this fact
        cit: ResolvedCitation | None = None
        for cid in rf.cite_ids:
            cit = citation_index.get(cid)
            if cit and cit.canonical_url:
                break

        # Get or create source
        source_id: int | None = None
        if cit and cit.canonical_url:
            canon = cit.canonical_url
            if canon in url_to_source_id:
                source_id = url_to_source_id[canon]
            else:
                source_id = matrix.add_source(
                    conn,
                    channel=cit.channel,
                    title=cit.title,
                    url=cit.canonical_url,
                    publisher=cit.publisher,
                )
                url_to_source_id[canon] = source_id
                committed_sources += 1

        # Check for duplicate fact
        norm_text = _normalize_fact_text(rf.text)
        existing_fact = conn.execute(
            """SELECT f.id FROM facts f
                JOIN cells c ON c.id = f.cell_id
                WHERE c.client_id = ?
                  AND c.subsection_id = ?
                  AND lower(trim(f.text)) = ?
                LIMIT 1""",
            (client_id, rf.subsection_id, norm_text),
        ).fetchone()

        if existing_fact:
            skipped_facts += 1
            continue

        try:
            matrix.add_fact(
                conn,
                client_id=client_id,
                subsection_id=rf.subsection_id,
                text=rf.text,
                flag=rf.flag,
                source_id=source_id,
                confidence=rf.confidence,
                evidence_snippet=rf.evidence_snippet,
            )
            committed_facts += 1
        except ValueError:
            skipped_facts += 1

    # Write audit row
    now = datetime.now(timezone.utc).isoformat()
    _ensure_audit_table(conn)
    conn.execute(
        """INSERT INTO ingest_audit
            (id, client_id, ingest_kind, source_artifact, agent, cite_format,
             parsed_at, facts_emitted, facts_committed, greys_emitted,
             channel_warnings, expert_email, confirmed_at, preview_json)
            VALUES (?, ?, 'llm_report', ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?)""",
        (
            preview.audit_id, client_id,
            preview.source_artifact_path, preview.detected_agent, None,
            now,
            preview.stats.get("facts_emitted", 0),
            committed_facts,
            preview.stats.get("greys", 0),
            preview.stats.get("channel_warnings", 0),
            expert_email, now,
            json.dumps({
                "audit_id": preview.audit_id,
                "stats": preview.stats,
                "notes": preview.notes,
            }),
        ),
    )
    conn.commit()

    return CommitResult(
        audit_id=preview.audit_id,
        committed_facts=committed_facts,
        committed_sources=committed_sources,
        skipped_facts=skipped_facts,
        ingested_at=now,
    )


# ── helpers ───────────────────────────────────────────────────────────────────

def _apply_edits(facts: list[ResolvedFact], edits: list[dict]) -> list[ResolvedFact]:
    """Apply expert keep/edit/drop actions from the confirmation screen."""
    if not edits:
        return facts
    edit_map: dict[int, dict] = {e["fact_idx"]: e for e in edits if "fact_idx" in e}
    result = []
    for i, rf in enumerate(facts):
        edit = edit_map.get(i)
        if edit is None or edit.get("action") == "keep":
            result.append(rf)
        elif edit["action"] == "drop":
            continue
        elif edit["action"] == "edit":
            from dataclasses import replace
            updated = replace(
                rf,
                text=edit.get("new_text", rf.text),
                subsection_id=edit.get("new_subsection_id", rf.subsection_id),
                flag=edit.get("new_flag", rf.flag),
            )
            result.append(updated)
    return result


def _ensure_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingest_audit (
            id              TEXT PRIMARY KEY,
            client_id       TEXT NOT NULL,
            ingest_kind     TEXT NOT NULL CHECK(ingest_kind IN ('llm_report', 'manual_seed')),
            source_artifact TEXT NOT NULL,
            agent           TEXT,
            cite_format     TEXT,
            parsed_at       TIMESTAMP NOT NULL,
            facts_emitted   INTEGER NOT NULL,
            facts_committed INTEGER NOT NULL,
            greys_emitted   INTEGER NOT NULL,
            channel_warnings INTEGER NOT NULL,
            expert_email    TEXT NOT NULL,
            confirmed_at    TIMESTAMP NOT NULL,
            preview_json    TEXT NOT NULL
        )
    """)
    conn.commit()

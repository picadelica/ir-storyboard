#!/usr/bin/env python3
"""Diff the current pipeline output against the golden expected YAML.

Usage:
    python scripts/diff_with_golden.py [--update] [--client libermans-gonka]

--check  (default) Compare and print diffs. Exit 1 if divergence above threshold.
--update           Re-run pipeline and overwrite libermans_gonka.expected.yaml.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures" / "llm_report"
GONKA_DOCX = FIXTURES / "gonka_chatgpt_deep_research.docx"
EXPECTED_YAML = FIXTURES / "libermans_gonka.expected.yaml"
CLIENT_ID = "libermans-gonka"


def run_pipeline(tmp_db_path: Path):
    from ir_storyboard import db as _db, matrix
    from ir_storyboard.channels.llm_report.pipeline import (
        preview_llm_report, commit_llm_report,
    )

    conn = _db.connect(tmp_db_path)
    _db.init_schema(conn)
    matrix.seed_layers(conn)
    matrix.upsert_client(conn, CLIENT_ID, "Libermans (Gonka AI)", sector="DePIN")

    preview = preview_llm_report(GONKA_DOCX, CLIENT_ID, conn)
    result = commit_llm_report(preview, CLIENT_ID, conn, "script@example.com")

    # Collect output
    facts = conn.execute(
        """SELECT f.text, f.flag, f.evidence_snippet, c.subsection_id,
                  s.channel, s.url AS source_url, s.title AS source_title
             FROM facts f
             JOIN cells c ON c.id = f.cell_id
             LEFT JOIN sources s ON s.id = f.source_id
             WHERE c.client_id = ?
             ORDER BY c.subsection_id, f.id""",
        (CLIENT_ID,),
    ).fetchall()

    return {
        "audit": {
            "audit_id": preview.audit_id,
            "agent": preview.detected_agent,
            "facts_emitted": preview.stats.get("facts_emitted", 0),
            "facts_committed": result.committed_facts,
            "greys": preview.stats.get("greys", 0),
            "channel_warnings": preview.stats.get("channel_warnings", 0),
            "notes": preview.notes,
        },
        "facts": [
            {
                "subsection_id": r["subsection_id"],
                "text": r["text"],
                "flag": r["flag"],
                "channel": r["channel"],
                "source_url": r["source_url"],
                "evidence_snippet": (r["evidence_snippet"] or "")[:200],
            }
            for r in facts
        ],
    }


def update_golden(output: dict) -> None:
    import yaml

    existing = {}
    if EXPECTED_YAML.exists():
        with EXPECTED_YAML.open() as f:
            existing = yaml.safe_load(f) or {}

    # Preserve client / track metadata from existing file
    merged = {
        "client": existing.get("client", {}),
        "founder_name": existing.get("founder_name", ""),
        "seed_tracks": existing.get("seed_tracks", []),
        "ingestion_audit": output["audit"],
        "seed_facts": [
            {
                "subsection_id": f["subsection_id"],
                "text": f["text"],
                "flag": f["flag"],
                "channel": f["channel"],
                "source_url": f["source_url"] or "",
                "source_title": "",
                "evidence_snippet": f["evidence_snippet"],
            }
            for f in output["facts"]
        ],
    }

    with EXPECTED_YAML.open("w", encoding="utf-8") as f:
        yaml.dump(merged, f, allow_unicode=True, default_flow_style=False, width=100)

    print(f"Updated {EXPECTED_YAML} with {len(output['facts'])} facts")


def check_golden(output: dict) -> bool:
    import yaml

    if not EXPECTED_YAML.exists():
        print(f"Golden file not found: {EXPECTED_YAML}")
        print("Run with --update to create it.")
        return False

    with EXPECTED_YAML.open() as f:
        expected = yaml.safe_load(f) or {}

    expected_facts = expected.get("seed_facts", [])
    actual_facts = output["facts"]

    expected_sids = {f["subsection_id"] for f in expected_facts}
    actual_sids = {f["subsection_id"] for f in actual_facts}
    missing = expected_sids - actual_sids
    extra = actual_sids - expected_sids

    print(f"Expected {len(expected_facts)} facts in {len(expected_sids)} subsections")
    print(f"Actual   {len(actual_facts)} facts in {len(actual_sids)} subsections")

    if missing:
        print(f"MISSING subsections: {sorted(missing)}")
    if extra:
        print(f"EXTRA subsections: {sorted(extra)}")

    coverage = len(expected_sids & actual_sids) / len(expected_sids) if expected_sids else 1.0
    print(f"Coverage: {coverage:.0%}")

    ok = coverage >= 0.6 and len(actual_facts) >= max(1, len(expected_facts) * 0.5)
    print("PASS" if ok else "FAIL")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Diff pipeline output vs golden YAML")
    parser.add_argument("--update", action="store_true", help="Overwrite golden YAML")
    parser.add_argument("--client", default=CLIENT_ID)
    args = parser.parse_args()

    if not GONKA_DOCX.exists():
        print(f"Fixture not found: {GONKA_DOCX}")
        sys.exit(1)

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp_db = Path(td) / "diff.db"
        print(f"Running pipeline on {GONKA_DOCX.name}…")
        output = run_pipeline(tmp_db)

    if args.update:
        update_golden(output)
    else:
        ok = check_golden(output)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

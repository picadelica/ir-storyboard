"""YouTube Ingest E2E tests.

Two variants:
1. Cached E2E (runs in normal pytest -q): pre-seeds youtube_transcripts with
   a mock transcript for a known video_id, then exercises the full pipeline
   from transcript → IR → extract → anchor → guard → dedup → audit.

2. Network E2E (pytest -m network): uses a real short public YouTube video.
   Run: pytest -m network tests/test_youtube_e2e.py -v
   Requires: local-faster-whisper installed, or TRANSCRIBER=openai-whisper-1
   with OPENAI_API_KEY set.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── fixture ───────────────────────────────────────────────────────────────────

KNOWN_VIDEO_ID = "dQw4w9WgXcQ"           # short public video (used only by network test)
KNOWN_CANONICAL = f"https://www.youtube.com/watch?v={KNOWN_VIDEO_ID}"

# Minimal but representative transcript for the cached E2E test
MOCK_TRANSCRIPT_SEGMENTS = [
    {"text": "Hi, I'm the founder and today I want to share my story.", "start": 0.0, "end": 3.5},
    {"text": "I grew up in Kazakhstan and moved to the US when I was twenty.", "start": 3.6, "end": 7.2},
    {"text": "My father was an engineer who taught me to code from the age of six.", "start": 7.3, "end": 11.0},
    {"text": "We started our company in 2016 with just the two of us.", "start": 15.0, "end": 18.5},
    {"text": "I was the CTO and my brother was the CEO.", "start": 18.6, "end": 21.0},
    {"text": "Our mission is to make AI accessible to everyone on the planet.", "start": 30.0, "end": 34.5},
    {"text": "We raised our seed round from a16z in 2017.", "start": 40.0, "end": 43.5},
    {"text": "The team grew from 2 to 50 engineers over the next three years.", "start": 44.0, "end": 48.0},
    {"text": "We believe strongly in open source and community-driven development.", "start": 50.0, "end": 54.5},
    {"text": "Looking back, joining Bitfury in 2014 was the turning point for me.", "start": 60.0, "end": 64.5},
]


def _make_mock_transcriber():
    t = MagicMock()
    t.name = "local-faster-whisper:large-v3-turbo"
    return t


def _make_conn(tmp_path):
    from ir_storyboard import db, matrix
    db_path = tmp_path / "e2e.db"
    conn = db.connect(db_path)
    db.init_schema(conn)
    matrix.seed_layers(conn)
    matrix.upsert_client(conn, "test_founder", "Test Founder Co", sector="deeptech")
    return conn


def _seed_transcript_cache(conn, video_id=KNOWN_VIDEO_ID):
    """Pre-seed youtube_transcripts so get_or_transcribe returns cached data."""
    from ir_storyboard.ingest.loaders.transcriber import _ensure_transcripts_table
    _ensure_transcripts_table(conn)
    conn.execute(
        """INSERT OR REPLACE INTO youtube_transcripts
            (video_id, canonical_url, title, channel_name, duration_sec,
             language, transcriber, segments_json, transcribed_at, transcribe_duration_sec)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 5)""",
        (
            video_id,
            f"https://www.youtube.com/watch?v={video_id}",
            "Founder Interview (Mock)",
            "Tech Talks Channel",
            65,
            "en",
            "local-faster-whisper:large-v3-turbo",
            json.dumps(MOCK_TRANSCRIPT_SEGMENTS),
        ),
    )
    conn.commit()


# ── cached E2E (no network, no whisper) ───────────────────────────────────────

def test_e2e_cached_pipeline(tmp_path):
    """Full pipeline from cached transcript → facts in matrix. No network calls."""
    from ir_storyboard.ingest.loaders.transcriber import (
        TranscriptSegment, Transcript,
    )
    from ir_storyboard.ingest.loaders.youtube_url import YouTubeVideoMeta

    conn = _make_conn(tmp_path)
    _seed_transcript_cache(conn)

    # Mock fetch_metadata (no network)
    mock_meta = YouTubeVideoMeta(
        video_id=KNOWN_VIDEO_ID,
        canonical_url=KNOWN_CANONICAL,
        title="Founder Interview (Mock)",
        channel_name="Tech Talks Channel",
        channel_url="https://youtube.com/@techtalks",
        duration_sec=65,
        upload_date="2026-01-15",
        description="",
        language="en",
    )

    # Mock LLM extraction
    mock_facts_json = json.dumps({
        "facts": [
            {
                "text": "Founder grew up in Kazakhstan and moved to the US at age 20.",
                "subsection_id": "1.1",
                "flag": "green",
                "cite_ids": [1],
                "confidence": 0.9,
                "raw_paraphrase": "I grew up in Kazakhstan and moved to the US when I was twenty.",
                "segment_idx_start": 1,
                "segment_idx_end": 1,
                "layer_warning": False,
            },
            {
                "text": "Father taught founder to code from age 6.",
                "subsection_id": "1.2",
                "flag": "green",
                "cite_ids": [1],
                "confidence": 0.88,
                "raw_paraphrase": "My father was an engineer who taught me to code from the age of six.",
                "segment_idx_start": 2,
                "segment_idx_end": 2,
                "layer_warning": False,
            },
            {
                "text": "Company started in 2016 with two co-founders.",
                "subsection_id": "2.3",
                "flag": "green",
                "cite_ids": [1],
                "confidence": 0.92,
                "raw_paraphrase": "We started our company in 2016 with just the two of us.",
                "segment_idx_start": 3,
                "segment_idx_end": 4,
                "layer_warning": False,
            },
            {
                "text": "Mission: make AI accessible to everyone on the planet.",
                "subsection_id": "7.1",
                "flag": "green",
                "cite_ids": [1],
                "confidence": 0.95,
                "raw_paraphrase": "Our mission is to make AI accessible to everyone on the planet.",
                "segment_idx_start": 5,
                "segment_idx_end": 5,
                "layer_warning": False,
            },
            {
                "text": "Joined Bitfury in 2014 as a turning point in career.",
                "subsection_id": "2.1",
                "flag": "green",
                "cite_ids": [1],
                "confidence": 0.9,
                "raw_paraphrase": "joining Bitfury in 2014 was the turning point for me.",
                "segment_idx_start": 9,
                "segment_idx_end": 9,
                "layer_warning": False,
            },
            {
                "text": "DePIN market revenue projections — L8 content.",
                "subsection_id": "8.2",
                "flag": "green",
                "cite_ids": [1],
                "confidence": 0.6,
                "raw_paraphrase": "The DePIN market is growing rapidly.",
                "segment_idx_start": 7,
                "segment_idx_end": 7,
                "layer_warning": True,  # LayerGuard will catch this
            },
        ]
    })

    from ir_storyboard.ingest.youtube_pipeline import (
        run_youtube_preview, run_youtube_commit,
    )

    with patch(
        "ir_storyboard.ingest.youtube_pipeline.normalize_url",
        return_value=KNOWN_CANONICAL,
    ), patch(
        "ir_storyboard.ingest.youtube_pipeline.fetch_metadata",
        return_value=mock_meta,
    ), patch(
        "ir_storyboard.ingest.youtube_pipeline.get_transcriber",
        return_value=_make_mock_transcriber(),
    ), patch(
        "ir_storyboard.ingest.youtube_pipeline.get_or_transcribe",
        return_value=Transcript(
            segments=[TranscriptSegment(**s) for s in MOCK_TRANSCRIPT_SEGMENTS],
            language="en",
            transcriber="local-faster-whisper:large-v3-turbo",
            duration_sec=65,
        ),
    ), patch(
        "ir_storyboard.llm.generate",
        return_value=mock_facts_json,
    ):
        preview = run_youtube_preview("test_founder", KNOWN_CANONICAL, conn)

    # ── Invariant checks ──────────────────────────────────────────────────────

    # ≥5 facts in allowed
    assert len(preview.facts) >= 5, f"Expected ≥5 facts, got {len(preview.facts)}"

    # L8.2 fact ended up in skipped
    assert len(preview.skipped) >= 1
    skipped_sids = {s.fact.subsection_id for s in preview.skipped}
    assert "8.2" in skipped_sids, "L8.2 fact must be skipped by LayerGuard"

    # All non-grey facts have evidence_snippet ≥ 20 chars
    for fact in preview.facts:
        if fact.flag != "grey":
            assert len(fact.evidence_snippet.strip()) >= 20, (
                f"evidence_snippet too short for {fact.subsection_id}: '{fact.evidence_snippet}'"
            )

    # All facts have timestamp URL
    for fact in preview.facts:
        assert "&t=" in fact.source_url, f"Missing &t= in source_url: {fact.source_url}"

    # All facts are in allowed subsections
    allowed_layers = {"1", "2", "3", "4", "7"}
    for fact in preview.facts:
        layer = fact.subsection_id.split(".")[0]
        assert layer in allowed_layers, f"Unexpected layer {fact.subsection_id} in allowed facts"

    # ── Commit and check matrix ───────────────────────────────────────────────
    commit = run_youtube_commit(
        preview_id=preview.preview_id,
        accepted_fact_ids=list(range(len(preview.facts))),
        overrides=[],
        conn=conn,
        expert_email="test@example.com",
    )

    assert commit.committed >= 5

    # Check facts appear in matrix
    from ir_storyboard import matrix
    facts_21 = matrix.facts_for_cell(conn, "test_founder", "2.1")
    assert len(facts_21) >= 1
    assert any("Bitfury" in f["text"] for f in facts_21)


def test_e2e_idempotent_replay(tmp_path):
    """Second ingest of same video → 0 new facts committed."""
    from ir_storyboard.ingest.loaders.transcriber import (
        TranscriptSegment, Transcript,
    )
    from ir_storyboard.ingest.loaders.youtube_url import YouTubeVideoMeta
    from ir_storyboard.ingest.youtube_pipeline import (
        run_youtube_preview, run_youtube_commit,
    )

    conn = _make_conn(tmp_path)
    _seed_transcript_cache(conn)

    mock_meta = YouTubeVideoMeta(
        video_id=KNOWN_VIDEO_ID,
        canonical_url=KNOWN_CANONICAL,
        title="Mock",
        channel_name="Channel",
        channel_url="",
        duration_sec=65,
        upload_date="2026-01-15",
        description="",
        language="en",
    )
    simple_fact = json.dumps({
        "facts": [{
            "text": "Founder joined Bitfury in 2014 and left in 2019 after Series B.",
            "subsection_id": "2.1",
            "flag": "green",
            "cite_ids": [1],
            "confidence": 0.9,
            "raw_paraphrase": "joining Bitfury in 2014 was the turning point for me.",
            "segment_idx_start": 9,
            "segment_idx_end": 9,
            "layer_warning": False,
        }]
    })

    transcript = Transcript(
        segments=[TranscriptSegment(**s) for s in MOCK_TRANSCRIPT_SEGMENTS],
        language="en",
        transcriber="local-faster-whisper:large-v3-turbo",
        duration_sec=65,
    )

    mocks = [
        patch("ir_storyboard.ingest.youtube_pipeline.normalize_url",
              return_value=KNOWN_CANONICAL),
        patch("ir_storyboard.ingest.youtube_pipeline.fetch_metadata",
              return_value=mock_meta),
        patch("ir_storyboard.ingest.youtube_pipeline.get_transcriber",
              return_value=_make_mock_transcriber()),
        patch("ir_storyboard.ingest.youtube_pipeline.get_or_transcribe",
              return_value=transcript),
        patch("ir_storyboard.llm.generate", return_value=simple_fact),
    ]

    # First ingest
    with mocks[0], mocks[1], mocks[2], mocks[3], mocks[4]:
        preview1 = run_youtube_preview("test_founder", KNOWN_CANONICAL, conn)
        run_youtube_commit(
            preview_id=preview1.preview_id,
            accepted_fact_ids=[0],
            overrides=[],
            conn=conn,
        )

    # Second ingest — same data
    with mocks[0], mocks[1], mocks[2], mocks[3], mocks[4]:
        preview2 = run_youtube_preview("test_founder", KNOWN_CANONICAL, conn)

    # Should be deduplicated in preview
    assert len(preview2.facts) == 0, (
        f"Expected 0 new facts on second ingest, got {len(preview2.facts)}"
    )


# ── network E2E (real YouTube, real Whisper) ──────────────────────────────────

@pytest.mark.network
def test_e2e_real_youtube_video(tmp_path):
    """Real YouTube video → real transcript → facts in matrix.

    Run with: pytest -m network tests/test_youtube_e2e.py -v
    Requires: TRANSCRIBER=local-faster-whisper (default) with faster-whisper
    installed, or TRANSCRIBER=openai-whisper-1 with OPENAI_API_KEY set.

    Video: a short, freely available YouTube video (~3 min).
    """
    import os
    # Pick a short, reliably available YouTube video for testing
    # Ted-Ed: "How does the stock market work?" (4m 41s, English, public)
    TEST_URL = "https://www.youtube.com/watch?v=p7HKvqRI_Bo"

    conn = _make_conn(tmp_path)

    from ir_storyboard.ingest.youtube_pipeline import (
        run_youtube_preview, run_youtube_commit,
    )

    preview = run_youtube_preview("test_founder", TEST_URL, conn)

    assert len(preview.facts) >= 5, f"Expected ≥5 facts from real video, got {len(preview.facts)}"

    for fact in preview.facts:
        if fact.flag != "grey":
            assert len(fact.evidence_snippet.strip()) >= 20
        assert "&t=" in fact.source_url

    # All allowed facts stay within online_interview layers
    allowed_layers = {"1", "2", "3", "4", "7"}
    for fact in preview.facts:
        layer = fact.subsection_id.split(".")[0]
        assert layer in allowed_layers

    commit = run_youtube_commit(
        preview_id=preview.preview_id,
        accepted_fact_ids=list(range(len(preview.facts))),
        overrides=[],
        conn=conn,
    )
    assert commit.committed >= 5

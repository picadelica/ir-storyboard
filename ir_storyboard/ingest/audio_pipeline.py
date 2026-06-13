"""Audio file Ingest pipeline orchestrator (uploaded .m4a/.mp3/.wav/.ogg/.aac).

Two-phase, mirroring the YouTube ingest:
  1. run_audio_preview(client_id, file_path, title, conn) → YouTubePreviewResult
  2. run_audio_commit(preview_id, accepted_ids, overrides, conn, email)
     → YouTubeCommitResult (delegates to the shared commit core)

Not a new Channel: facts are written through `online_interview` (same as
YouTube — a recorded interview with the founder), restricted by LayerGuard.
Transcript cache is keyed by the file's sha256 (table `audio_transcripts`),
so re-uploading the same recording never re-transcribes.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .loaders.audio_chunker import _probe_duration
from .loaders.transcriber import (
    get_transcriber,
    get_or_transcribe_audio_file,
    _ensure_audio_transcripts_table,
)
from .youtube_pipeline import (
    YouTubePreviewResult,
    YouTubeCommitResult,
    run_transcript_preview,
    run_youtube_commit,
    _ensure_audit_table_youtube,
)


@dataclass
class AudioFileMeta:
    """Duck-typed counterpart of YouTubeVideoMeta for uploaded audio files.

    `video_id` carries the sha256[:16] of the file — it doubles as the audit
    identifier shown in history rows.
    """
    video_id: str                  # sha256[:16]
    canonical_url: str             # file://<sha256[:16]>
    title: str
    channel_name: str = "audio upload"
    duration_sec: int = 0
    upload_date: str = ""
    language: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    description: str = ""


def file_sha256(file_path: Path) -> str:
    """Stream-hash a file (sha256 hex)."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run_audio_preview(
    client_id: str,
    file_path: Path,
    title: str,
    conn: sqlite3.Connection,
    sha256_hex: Optional[str] = None,
    progress_cb=None,
) -> YouTubePreviewResult:
    """Full pipeline for an uploaded audio file:
    sha256 → ffprobe duration → transcript (sha-keyed cache) → shared
    transcript core (extract → anchor → guard → dedup → brief → audit).

    Audit row: ingest_kind='audio_file'. Per-fact source_url is blank
    (no clickable timestamp URL for local files) — provenance lives in the
    source row (title + file:// canonical url) and snippet timestamps.
    """
    file_path = Path(file_path)
    _ensure_audit_table_youtube(conn)
    _ensure_audio_transcripts_table(conn)

    if progress_cb:
        progress_cb("анализ файла (ffprobe)")
    sha = sha256_hex or file_sha256(file_path)
    canonical_url = f"file://{sha[:16]}"
    duration_sec = int(_probe_duration(file_path))

    meta = AudioFileMeta(
        video_id=sha[:16],
        canonical_url=canonical_url,
        title=(title or "").strip() or file_path.name,
        duration_sec=duration_sec,
    )

    notes: list[str] = []
    transcriber = get_transcriber()

    row_before = conn.execute(
        "SELECT transcriber FROM audio_transcripts WHERE file_sha256 = ?",
        (sha,),
    ).fetchone()
    from_cache = (
        row_before is not None
        and row_before["transcriber"] == transcriber.name
    )

    if from_cache and progress_cb:
        progress_cb("транскрипт найден в кэше")
    transcript = get_or_transcribe_audio_file(
        sha, file_path, meta, transcriber, conn, progress_cb=progress_cb,
    )
    if from_cache:
        notes.append(f"Transcript loaded from cache (transcriber={transcriber.name})")

    # Estimate cost (OpenAI Whisper API = $0.006/min)
    transcribe_cost_usd: Optional[float] = None
    if transcriber.name == "openai-whisper-1":
        transcribe_cost_usd = round((duration_sec / 60.0) * 0.006, 4)

    if progress_cb:
        progress_cb("извлечение фактов и якорение (LLM)")
    return run_transcript_preview(
        client_id=client_id,
        canonical_url=canonical_url,
        meta=meta,
        transcript=transcript,
        conn=conn,
        channel="online_interview",
        ingest_kind="audio_file",
        transcriber_name=transcriber.name,
        from_cache=from_cache,
        transcribe_cost_usd=transcribe_cost_usd,
        notes=notes,
        fact_source_urls=False,
    )


def run_audio_commit(
    preview_id: str,
    accepted_fact_ids: list[int],
    overrides: list[dict],
    conn: sqlite3.Connection,
    expert_email: str = "anonymous@example.com",
) -> YouTubeCommitResult:
    """Write accepted audio-file facts to the matrix.

    Same semantics as run_youtube_commit (the preview row stores everything
    needed, including the channel) — thin alias kept for call-site clarity.
    """
    return run_youtube_commit(
        preview_id=preview_id,
        accepted_fact_ids=accepted_fact_ids,
        overrides=overrides,
        conn=conn,
        expert_email=expert_email,
    )

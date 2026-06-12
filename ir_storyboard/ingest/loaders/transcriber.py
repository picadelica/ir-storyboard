"""Transcriber interface + concrete implementations (faster-whisper, OpenAI, Deepgram).

Default: LocalFasterWhisperTranscriber (no external API, no data leaves VPS).
OpenAI Whisper API and Deepgram selectable via env TRANSCRIBER.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from .youtube_audio import fetch_audio
from .audio_chunker import split_audio


@dataclass
class TranscriptSegment:
    text: str
    start: float   # seconds, relative to the WHOLE video (after chunk offset applied)
    end: float


@dataclass
class Transcript:
    segments: list[TranscriptSegment]
    language: str
    transcriber: str    # e.g. 'local-faster-whisper:large-v3-turbo'
    duration_sec: int


class Transcriber(Protocol):
    """Protocol: transcribe one audio chunk, return segments in chunk-local time."""

    name: str

    def transcribe(
        self,
        audio_path: Path,
        language_hint: Optional[str] = None,
    ) -> list[TranscriptSegment]:
        """Return segments with start/end relative to the beginning of audio_path."""
        ...


# ── Local faster-whisper ─────────────────────────────────────────────────────

_fw_model_singleton = None   # one model instance per process


class LocalFasterWhisperTranscriber:
    """Transcriber using faster-whisper (CTranslate2 backend).

    Singleton model: loaded once on first call, cached for the process lifetime.
    """

    @property
    def name(self) -> str:
        model = os.environ.get("FASTER_WHISPER_MODEL", "large-v3-turbo")
        return f"local-faster-whisper:{model}"

    def _get_model(self):
        global _fw_model_singleton
        if _fw_model_singleton is not None:
            return _fw_model_singleton

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError(
                "faster-whisper is not installed. "
                "Run: pip install faster-whisper  (and apt-get install -y ffmpeg)"
            )

        model_name = os.environ.get("FASTER_WHISPER_MODEL", "large-v3-turbo")
        device = os.environ.get("FASTER_WHISPER_DEVICE", "auto")
        compute_type = os.environ.get("FASTER_WHISPER_COMPUTE_TYPE", "int8")
        model_dir = os.environ.get("FASTER_WHISPER_MODEL_DIR", "/data/whisper")

        _fw_model_singleton = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=model_dir,
        )
        return _fw_model_singleton

    def transcribe(
        self,
        audio_path: Path,
        language_hint: Optional[str] = None,
    ) -> list[TranscriptSegment]:
        model = self._get_model()
        kwargs = {"beam_size": 5}
        if language_hint:
            kwargs["language"] = language_hint

        segments_iter, _ = model.transcribe(str(audio_path), **kwargs)
        return [
            TranscriptSegment(text=seg.text.strip(), start=seg.start, end=seg.end)
            for seg in segments_iter
        ]


# ── OpenAI Whisper API ───────────────────────────────────────────────────────

class OpenAIWhisperTranscriber:
    name = "openai-whisper-1"

    def transcribe(
        self,
        audio_path: Path,
        language_hint: Optional[str] = None,
    ) -> list[TranscriptSegment]:
        try:
            import openai
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai>=1.0")

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        client = openai.OpenAI(api_key=api_key)
        kwargs: dict = {
            "model": "whisper-1",
            "response_format": "verbose_json",
            "timestamp_granularities": ["segment"],
        }
        if language_hint:
            kwargs["language"] = language_hint

        # OpenAI requires a supported extension; .opus files are ogg containers
        upload_name = audio_path.name
        if audio_path.suffix.lower() == ".opus":
            upload_name = audio_path.stem + ".ogg"

        with open(audio_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                file=(upload_name, f, "audio/ogg"),
                **kwargs,
            )

        segments = []
        for seg in (resp.segments or []):
            segments.append(TranscriptSegment(
                text=seg.text.strip(),
                start=float(seg.start),
                end=float(seg.end),
            ))
        return segments


# ── Deepgram ─────────────────────────────────────────────────────────────────

class DeepgramTranscriber:
    name = "deepgram-nova-3"

    def transcribe(
        self,
        audio_path: Path,
        language_hint: Optional[str] = None,
    ) -> list[TranscriptSegment]:
        try:
            from deepgram import DeepgramClient, PrerecordedOptions
        except ImportError:
            raise RuntimeError("deepgram-sdk not installed. Run: pip install deepgram-sdk")

        api_key = os.environ.get("DEEPGRAM_API_KEY")
        if not api_key:
            raise RuntimeError("DEEPGRAM_API_KEY not set")

        client = DeepgramClient(api_key)
        opts = PrerecordedOptions(
            model="nova-3",
            smart_format=True,
            utterances=True,
            punctuate=True,
        )
        if language_hint:
            opts.language = language_hint

        with open(audio_path, "rb") as f:
            audio_data = {"buffer": f.read()}
        resp = client.listen.prerecorded.v("1").transcribe_file(audio_data, opts)

        segments = []
        words = resp.results.channels[0].alternatives[0].words or []
        # Deepgram gives word-level; we reconstruct utterance-level segments
        if hasattr(resp.results, "utterances") and resp.results.utterances:
            for utt in resp.results.utterances:
                segments.append(TranscriptSegment(
                    text=utt.transcript.strip(),
                    start=float(utt.start),
                    end=float(utt.end),
                ))
        else:
            # Fallback: one big segment per alternative
            alt = resp.results.channels[0].alternatives[0]
            segments.append(TranscriptSegment(
                text=alt.transcript.strip(),
                start=0.0,
                end=float(words[-1].end) if words else 0.0,
            ))
        return segments


# ── Factory ───────────────────────────────────────────────────────────────────

def get_transcriber() -> Transcriber:
    """Return the configured Transcriber based on env TRANSCRIBER."""
    provider = os.environ.get("TRANSCRIBER", "local-faster-whisper").lower()
    if provider == "openai-whisper-1":
        return OpenAIWhisperTranscriber()
    if provider == "deepgram-nova-3":
        return DeepgramTranscriber()
    return LocalFasterWhisperTranscriber()


# ── Dedup overlap segments ────────────────────────────────────────────────────

def _jaccard_words(a: str, b: str) -> float:
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _similar(a: str, b: str) -> bool:
    return _jaccard_words(a, b) >= 0.8


def dedup_overlap_segments(
    chunks_segments: list[list[TranscriptSegment]],
    chunk_boundaries: list[float],
    overlap_sec: int = 5,
) -> list[TranscriptSegment]:
    """Merge per-chunk segments into a single timeline, removing overlap duplicates.

    chunk_boundaries[i] = chunk_start_sec for chunks_segments[i].
    Segments must already have global timestamps (chunk offset added).
    """
    if not chunks_segments:
        return []

    merged: list[TranscriptSegment] = list(chunks_segments[0])

    for i in range(1, len(chunks_segments)):
        boundary = chunk_boundaries[i]
        left = merged
        right = chunks_segments[i]

        kept_right: list[TranscriptSegment] = []
        for sr in right:
            # Only check for duplicates in the overlap zone (sr starts before boundary)
            if sr.start < boundary:
                # Look for a matching segment in left that is temporally close
                is_dup = any(
                    _similar(sl.text, sr.text) and abs(sl.start - sr.start) <= overlap_sec
                    for sl in left
                    if abs(sl.start - sr.start) <= overlap_sec
                )
                if not is_dup:
                    kept_right.append(sr)
            else:
                kept_right.append(sr)

        merged = merged + kept_right

    return merged


# ── Orchestrator ──────────────────────────────────────────────────────────────

def transcribe_audio_chunks(
    audio_path: Path,
    transcriber: Transcriber,
    language_hint: Optional[str] = None,
) -> list[TranscriptSegment]:
    """Transcribe one audio file: split → per-chunk transcribe → shift → dedup.

    Shared core for both YouTube ingest (after fetch_audio) and direct audio
    file uploads. Returns segments with global (whole-file) timestamps.
    """
    chunks = split_audio(audio_path)
    overlap_sec = int(os.environ.get("CHUNK_OVERLAP_SEC", "5"))

    chunk_segments: list[list[TranscriptSegment]] = []
    chunk_boundaries: list[float] = []

    for chunk in chunks:
        raw = transcriber.transcribe(audio_path=chunk.path, language_hint=language_hint)
        # Shift to global time
        shifted = [
            TranscriptSegment(
                text=s.text,
                start=s.start + chunk.chunk_start_sec,
                end=s.end + chunk.chunk_start_sec,
            )
            for s in raw
        ]
        chunk_segments.append(shifted)
        chunk_boundaries.append(chunk.chunk_start_sec)

    return dedup_overlap_segments(chunk_segments, chunk_boundaries, overlap_sec)


def get_or_transcribe(
    video_id: str,
    meta,                          # YouTubeVideoMeta
    transcriber: Transcriber,
    conn: sqlite3.Connection,
    cache_dir: Path | None = None,
) -> Transcript:
    """Return Transcript, using cached youtube_transcripts row if available.

    If the cached row was produced by a different transcriber, re-transcribes
    and overwrites the cache row.
    """

    _ensure_transcripts_table(conn)

    # Check cache
    row = conn.execute(
        "SELECT * FROM youtube_transcripts WHERE video_id = ?", (video_id,)
    ).fetchone()

    if row and row["transcriber"] == transcriber.name:
        segs = [
            TranscriptSegment(**s)
            for s in json.loads(row["segments_json"])
        ]
        return Transcript(
            segments=segs,
            language=row["language"],
            transcriber=row["transcriber"],
            duration_sec=row["duration_sec"],
        )

    if row and row["transcriber"] != transcriber.name:
        # Cache invalidation: different transcriber — warn on source rows if table exists
        try:
            conn.execute(
                "UPDATE sources SET notes = COALESCE(notes,'') || ? "
                "WHERE url LIKE ?",
                (
                    f"\n[warn] transcript re-done with {transcriber.name}; "
                    "evidence_snippets from prior ingest may be stale",
                    f"%{video_id}%",
                ),
            )
        except Exception:
            pass

    # Fetch + transcribe
    if cache_dir is None:
        cache_dir = Path("/tmp/ir_youtube_audio")

    t_start = time.time()
    audio_path = fetch_audio(video_id, cache_dir)
    all_segments = transcribe_audio_chunks(audio_path, transcriber, language_hint=meta.language)
    detected_language = meta.language or "en"
    wall_clock = int(time.time() - t_start)

    segments_json = json.dumps([
        {"text": s.text, "start": s.start, "end": s.end}
        for s in all_segments
    ])

    conn.execute(
        """INSERT OR REPLACE INTO youtube_transcripts
            (video_id, canonical_url, title, channel_name, duration_sec,
             language, transcriber, segments_json, transcribed_at, transcribe_duration_sec)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)""",
        (
            video_id, meta.canonical_url, meta.title, meta.channel_name,
            meta.duration_sec, detected_language, transcriber.name,
            segments_json, wall_clock,
        ),
    )
    conn.commit()

    return Transcript(
        segments=all_segments,
        language=detected_language,
        transcriber=transcriber.name,
        duration_sec=meta.duration_sec,
    )


def _ensure_transcripts_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS youtube_transcripts (
            video_id        TEXT PRIMARY KEY,
            canonical_url   TEXT NOT NULL,
            title           TEXT NOT NULL,
            channel_name    TEXT NOT NULL,
            duration_sec    INTEGER NOT NULL,
            language        TEXT NOT NULL,
            transcriber     TEXT NOT NULL,
            segments_json   TEXT NOT NULL,
            transcribed_at  TIMESTAMP NOT NULL,
            transcribe_duration_sec INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()


# ── Audio file uploads (cache keyed by file sha256) ──────────────────────────

def _ensure_audio_transcripts_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audio_transcripts (
            file_sha256     TEXT PRIMARY KEY,
            canonical_url   TEXT NOT NULL,
            title           TEXT NOT NULL,
            channel_name    TEXT NOT NULL,
            duration_sec    INTEGER NOT NULL,
            language        TEXT NOT NULL,
            transcriber     TEXT NOT NULL,
            segments_json   TEXT NOT NULL,
            transcribed_at  TIMESTAMP NOT NULL,
            transcribe_duration_sec INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()


def get_or_transcribe_audio_file(
    file_sha256: str,
    audio_path: Path,
    meta,                          # AudioFileMeta (duck-typed: title/channel_name/duration_sec/language/canonical_url)
    transcriber: Transcriber,
    conn: sqlite3.Connection,
) -> Transcript:
    """Return Transcript for an uploaded audio file, using the sha256-keyed
    audio_transcripts cache. Same semantics as get_or_transcribe: a cache row
    produced by a different transcriber is re-transcribed and overwritten.
    """
    _ensure_audio_transcripts_table(conn)

    row = conn.execute(
        "SELECT * FROM audio_transcripts WHERE file_sha256 = ?", (file_sha256,)
    ).fetchone()

    if row and row["transcriber"] == transcriber.name:
        segs = [
            TranscriptSegment(**s)
            for s in json.loads(row["segments_json"])
        ]
        return Transcript(
            segments=segs,
            language=row["language"],
            transcriber=row["transcriber"],
            duration_sec=row["duration_sec"],
        )

    t_start = time.time()
    all_segments = transcribe_audio_chunks(audio_path, transcriber, language_hint=meta.language)
    detected_language = meta.language or "en"
    wall_clock = int(time.time() - t_start)

    segments_json = json.dumps([
        {"text": s.text, "start": s.start, "end": s.end}
        for s in all_segments
    ])

    conn.execute(
        """INSERT OR REPLACE INTO audio_transcripts
            (file_sha256, canonical_url, title, channel_name, duration_sec,
             language, transcriber, segments_json, transcribed_at, transcribe_duration_sec)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)""",
        (
            file_sha256, meta.canonical_url, meta.title, meta.channel_name,
            meta.duration_sec, detected_language, transcriber.name,
            segments_json, wall_clock,
        ),
    )
    conn.commit()

    return Transcript(
        segments=all_segments,
        language=detected_language,
        transcriber=transcriber.name,
        duration_sec=meta.duration_sec,
    )

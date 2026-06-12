# NEXT — где мы остановились

> Снимок оперативного состояния. Обновлять в конце каждой сессии (overwrite,
> не append). Цель — за 30 секунд понять, где находимся.
>
> Стабильная архитектура и инварианты — в `CLAUDE.md`. Сюда — только
> «здесь и сейчас».

---

**Последнее обновление:** 2026-06-12
**Ветка:** `feat/v2`
**Working tree:** НЕ закоммичена серия Audio Ingest (см. ниже) — коммитить после
зелёного `pytest tests/` + `npm run build`.
**HEAD:** `2e45f39 feat: collapsible sidebar — clients only, controls moved to tabs row`

## Что сделано за сессию 2026-06-12 — Audio file Ingest (uncommitted)

Ingest аудиофайлов (.m4a/.mp3/.wav/.ogg/.aac) по образцу YouTube Ingest.
Начато одной сессией (рефакторинг общего ядра), достроено другой:

1. **Рефакторинг общего ядра** (начат предыдущей сессией, дофиксен):
   - `loaders/transcriber.py`: `transcribe_audio_chunks()` (split → transcribe
     → shift → dedup, общий для YouTube и файлов), таблица `audio_transcripts`
     (кэш по sha256 файла) + `get_or_transcribe_audio_file()`.
   - `youtube_pipeline.py`: `run_transcript_preview()` — общий preview-кор
     (extract → anchor → guard → dedup → brief → ingest_audit). Дофиксено:
     INSERT использовал несуществующий `transcriber.name` и хардкод
     `'youtube'` → теперь параметры `transcriber_name` / `ingest_kind`;
     `run_youtube_commit` берёт channel из `preview_json["channel"]`
     (fallback `online_interview`).

2. **`ingest/audio_pipeline.py`** — `AudioFileMeta` (duck-typed под
   YouTubeVideoMeta, `video_id`=sha256[:16], `canonical_url`=file://sha16,
   `channel_name`='audio upload'), `run_audio_preview()` (ffprobe-длительность,
   sha-кэш транскрипта, `ingest_kind='audio_file'`, факты без per-fact URL —
   `fact_source_urls=False`), `run_audio_commit()` (делегат общего commit).
   Канал — `online_interview` (как YouTube), LayerGuard блокирует L5/L6/L8.

3. **`backend/main.py`** — POST `/api/clients/{id}/ingest/audio/preview`
   (multipart, лимит 500MB, дедуп файла по sha256 в `data/audio_uploads/`
   (env `AUDIO_UPLOADS_DIR`), form-поле `title` опц.) → 202 `{job_id}`;
   GET `.../audio/preview/{job_id}` (общий `_job_status_out` с YouTube);
   POST `.../audio/commit`. Job store общий (`_yt_jobs`).

4. **Frontend** — `IngestAudio.tsx` (file input + title → джоб-поллинг →
   preview с edit/drop/override → commit), переиспользует экспортированные
   `FactCard`/`SkippedCard`/`FactEditForm`-логику из `IngestYouTube.tsx`.
   Таб "Audio" в `App.tsx`, `api.audioPreviewStart/Status/Commit`.

5. **`tests/test_audio_ingest.py`** — 8 тестов, всё внешнее замокано
   (ffprobe/ffmpeg/whisper): sha-кэш (повтор → from_cache, transcribe один
   раз), audit kind `audio_file`, commit пишет факты + идемпотентный replay,
   API job-flow (202 → poll → done), отказ по расширению/пустому файлу,
   sha-дедуп файлов на диске, commit endpoint.

## Open / следующие шаги

1. **Прогнать `python -m pytest tests/ -q` и `npm run build`** — в сессии
   2026-06-12 pytest был заблокирован permission-настройками агентского
   окружения (запуск из cwd вне проекта); код не прогонялся локально.
   `tsc -b` (часть build) прошёл.
2. Закоммитить серию (`audio-1: ...`) после зелёных тестов.
3. Baseline 9 failed тестов (LLM Report + 2 youtube_api) — предсуществующие,
   ортогональны (см. сессию 2026-06-09).
4. Audio history endpoint/таб не делали (preview-by-id и history покрывают
   только youtube kind) — добавить при необходимости.
5. Диаризация — см. `DIARIZATION_PLAN.md` (untracked, план).

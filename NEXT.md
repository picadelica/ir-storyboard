# NEXT — где мы остановились

> Снимок оперативного состояния. Обновлять в конце каждой сессии (overwrite,
> не append). Цель — за 30 секунд понять, где находимся.
>
> Стабильная архитектура и инварианты — в `CLAUDE.md`. Сюда — только
> «здесь и сейчас».

---

**Последнее обновление:** 2026-05-21
**Ветка:** `feat/v2`
**Working tree:** clean
**HEAD:** `youtube-8: e2e test + DEPLOY + docs update`

## Что в фокусе

**YouTube Ingest — реализован (youtube-1..8).** Серия коммитов полностью закрыта:

* **Task 1** `youtube-1`: URL normalization + yt-dlp metadata (12 тестов)
* **Task 2** `youtube-2`: Audio fetch + ffmpeg chunking + faster-whisper transcriber + cache (11 тестов)
* **Task 3** `youtube-3`: Transcript → ReportIR adapter + forced_channel (5 тестов)
* **Task 4** `youtube-4`: FactExtractor transcript-mode (segment_idx_*, layer_warning) (3 теста)
* **Task 5** `youtube-5`: SnippetAnchor + LayerGuard (10 тестов)
* **Task 6** `youtube-6`: Backend endpoints (preview/commit/history) + youtube_pipeline (6 тестов)
* **Task 7** `youtube-7`: Frontend IngestYouTube component + tab
* **Task 8** `youtube-8`: E2E test + DEPLOY + docs update (2 cached тестов)

**LLM Report Ingest** — закрыт (серия `llm-1 … llm-8` + ~14 пост-фиксов).

## Открытые вопросы (известные хвосты)

- **Embedding-dedup** — используется string similarity (Jaccard ≥ 0.85). Embeddings — v2,
  когда станет ясно где string similarity не справляется.
- **Speaker diarization** — не реализовано. Whisper не различает спикеров.
  Deepgram nova-3 умеет — за feature-flag, v2.
- **Параллелизация chunks** — `TRANSCRIBE_PARALLEL_CHUNKS=1` (последовательно).
  Замерить на реальном сервере перед включением > 1.
- **Private/age-restricted видео** — не поддерживаются (требуют cookies yt-dlp).
- **Видео без аудио / только музыка** — Whisper вернёт пустой транскрипт, ingest пропустится.

## Следующие разумные шаги (если пользователь скажет «продолжаем»)

1. **Деплой youtube-1..8 на сервер** (git push + docker-compose rebuild).
   Проверить `GET /api/clients/gonkaai/ingest/youtube/history`.
2. **Протестировать на реальном YouTube URL** (gonkaai / accumulator интервью).
3. **Hygiene refactor** (отдельная сессия):
   - Переименовать `channels/llm_report/` → `ingest/`
   - Вынести shared компоненты `<IngestPreview>` из IngestLLMReport + IngestYouTube

## Как обновлять этот файл

В конце сессии, когда что-то значимое сделано:

```
1. Обновить "Последнее обновление" — сегодняшняя дата.
2. Обновить "HEAD" — `git log -1 --oneline`.
3. Перезаписать раздел "Что в фокусе" — что только что закрыли.
4. Если открыты вопросы — в "Открытые вопросы".
5. Скорректировать "Следующий разумный шаг".
6. git add NEXT.md && git commit -m "chore: update NEXT.md"
```

# NEXT — где мы остановились

> Снимок оперативного состояния. Обновлять в конце каждой сессии (overwrite,
> не append). Цель — за 30 секунд понять, где находимся.
>
> Стабильная архитектура и инварианты — в `CLAUDE.md`. Сюда — только
> «здесь и сейчас».

---

**Последнее обновление:** 2026-05-23
**Ветка:** `feat/v2`
**Working tree:** clean (untracked: `12.jpeg` — не относится к проекту)
**HEAD:** `c8aace3 feat: YouTube Ingest history tab + reopen flow`

## Что в фокусе

Сессия 2026-05-23: добавлен **History tab + Reopen flow** для YouTube Ingest
(пункт #4 из открытых вопросов прошлой сессии).

1. **Backend — preview_json теперь хранит полный meta**
   (`youtube_pipeline.py`). Раньше там был только `video_id`+`canonical_url`,
   чего не хватало для отрисовки preview-экрана при reopen. Теперь меta
   полный (title/channel_name/duration_sec/upload_date/language) + `from_cache`
   + `transcribe_cost_usd`. Старые previews без `meta` reopen-ятся graceful'но —
   fallback к минимальному набору полей.
2. **Backend — новый endpoint** `GET /api/clients/{cid}/ingest/youtube/
   preview-by-id/{pid}` (`main.py:1481`) — реконструирует `YouTubePreviewOut`
   из `ingest_audit.preview_json` + возвращает `confirmed_at` для индикации
   readonly-режима. `YouTubePreviewOut.confirmed_at` сделан опциональным.
3. **Frontend — History screen + Reopen** (`IngestYouTube.tsx`):
   - Новый screen `"history"` — полная таблица прошлых previews
     (date / video / transcriber / cost / emitted / committed / warnings /
     expert) с per-row `reopen`.
   - На input-экране заголовок справа → кнопка `History (N) →`. Inline-таблица
     превращена в "Recent ingests" (top 5) с прямым `reopen` + ссылка
     `View all → history` если строк больше 5.
   - При reopen — preview screen в **read-only review mode**: банер вверху
     (`Committed on …` / `Uncommitted preview`), скрыт commit bar, скрыты
     `edit`/`drop`/`keep`/`undo` кнопки. "← Back" → возврат в history.
   - `readOnly` сбрасывается на новых previews (success polling / "Ingest
     another"), чтобы reopen не «протекал» в активную сессию.

## Открытые вопросы

- **Bulk-actions в preview** — multi-select чекбоксы и групповые
  drop/change-flag для скоростного разбора 100+ фактов. Не сделано.
- **filter/sort в preview** (по layer / по flag / по timestamp) — 173 факта
  в одном списке — много.
- **chunks_failed retry** — если max_tokens cutoff повторится несмотря на
  16k, fallback на `LLM_GENERATE_MODEL=claude-sonnet-4-6` через env var.
- **Embedding-dedup / speaker diarization / параллелизация chunks** — v2.
- **Hygiene refactor** — переименовать `channels/llm_report/` → `ingest/`,
  развести два `def ingest_preview` в `main.py` (Research + LLM-Report).

## Следующие разумные шаги (если пользователь скажет «продолжаем»)

1. **Bulk-actions**: multi-select + bulk drop / bulk change-flag /
   bulk move-to-subsection. Особенно полезно когда LLM путает layer
   у целой группы фактов.
2. **filter/sort** в preview (по layer / по flag / по timestamp).
3. **chunks_failed retry / sonnet fallback**.
4. **Hygiene refactor** (отдельная сессия).

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

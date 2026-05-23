# NEXT — где мы остановились

> Снимок оперативного состояния. Обновлять в конце каждой сессии (overwrite,
> не append). Цель — за 30 секунд понять, где находимся.
>
> Стабильная архитектура и инварианты — в `CLAUDE.md`. Сюда — только
> «здесь и сейчас».

---

**Последнее обновление:** 2026-05-23 (вторая часть сессии)
**Ветка:** `feat/v2`
**Working tree:** clean (untracked: `12.jpeg` — не относится к проекту)
**HEAD:** `82670a1 feat: bulk-actions in YouTube preview`

## Что в фокусе

Сессия 2026-05-23 закрыла 4 пункта (#4 history tab + три из открытых
вопросов: bulk-actions, sonnet fallback, hygiene refactor).

1. **History tab + Reopen flow** (`c8aace3`). Backend: `preview_json` теперь
   хранит полный meta + новый endpoint `GET .../ingest/youtube/preview-by-id/{pid}`
   реконструирует `YouTubePreviewOut` + `confirmed_at` для readonly-режима.
   Frontend: отдельный screen `"history"` с расширенной таблицей
   (date / video / transcriber / cost / emitted / committed / warnings /
   expert) и per-row Reopen. Старые previews без `meta` reopen-ятся graceful'но.
   При reopen — preview screen в **read-only review mode**: банер, скрыт
   commit bar, скрыты edit/drop/keep кнопки.
2. **Refactor** (`80af49d`). `ir_storyboard/channels/llm_report/` →
   `ir_storyboard/ingest/`. Папка содержит оркестраторы (LLM Report + YouTube)
   поверх 4 канонических каналов, а не «канал» — название теперь честное.
   `git mv` сохранил историю. В `backend/main.py` четыре `ingest_preview` /
   `ingest_confirm` / `ingest_commit` / `ingest_history` функции были
   shadow-конфликтные → переименованы в `research_*` / `llm_report_*`. URL
   paths не менялись.
3. **Sonnet fallback** (`622500b`). Если chunk extract_facts_from_transcript
   возвращает empty или unparseable JSON, ретраимся 1 раз на
   `LLM_GENERATE_MODEL_FALLBACK` (default `claude-sonnet-4-6`). Тегируется в
   `chunk_errors[].reason = "fallback_used"`. Защищает от потери целых 10-мин
   окон на overload/cutoff Haiku.
4. **Bulk-actions в preview** (`82670a1`). Чекбоксы на FactCard +
   sticky-тулбар (drop / restore / set flag / move to subsection) для
   быстрого разбора больших previews (100+ фактов). Selection чистится на
   screen transitions.

## Открытые вопросы

- **Filter/sort в preview** (по layer / по flag / по timestamp / по edited/
  dropped) — 173 факта в одном списке — много. Остался единственный
  невыполненный пункт из исходного backlog.
- **Embedding-dedup / speaker diarization / параллелизация chunks** — v2.

## Следующие разумные шаги (если пользователь скажет «продолжаем»)

1. **Filter/sort + поиск** в preview — последний пункт из исходного списка.
2. **Backfill тестов**: добавить unit-тесты для sonnet fallback /
   preview-by-id endpoint — сейчас на этих фичах нет тестов.
3. **Embedding-dedup** — v2.

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

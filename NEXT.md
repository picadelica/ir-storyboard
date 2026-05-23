# NEXT — где мы остановились

> Снимок оперативного состояния. Обновлять в конце каждой сессии (overwrite,
> не append). Цель — за 30 секунд понять, где находимся.
>
> Стабильная архитектура и инварианты — в `CLAUDE.md`. Сюда — только
> «здесь и сейчас».

---

**Последнее обновление:** 2026-05-23 (третья часть)
**Ветка:** `feat/v2`
**Working tree:** clean (untracked: `12.jpeg` — не относится к проекту)
**HEAD:** `34d69a8 feat(frontend): Methodology tab`

## Что в фокусе

Сессия 2026-05-23 закрыла 5 пунктов: history tab + reopen, refactor,
sonnet fallback, bulk-actions, **Methodology layer** (новое).

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
5. **Methodology layer** (`d83431d` + `34d69a8`). LLM раньше видел только
   название ячейки ("1.1 Origin & Childhood") — мог промахиваться, путать
   слои. Добавили две expert-редактируемые ручки:
   - **Per-subsection description** (глобально, одна на всех клиентов) —
     editable в новой вкладке Methodology, инжектится в prompt как
     "Methodology note:" под каждой ячейкой в списке.
   - **Per-client tone preset** (4 пресета: academic / business / narrative /
     punchy в `prompts.py`) — выбирается на той же вкладке, инжектится в
     prompt как "TONE INSTRUCTION" перед основным system prompt.
   Передаются во все 3 экстрактора (transcript / per-section / full-doc)
   из обоих оркестраторов (YouTube + LLM Report). Эндпоинты:
   `GET/PATCH /api/methodology`, `GET /api/tone-presets`, `tone_preset`
   в `ClientOut`. Schema: `clients.tone_preset` (idempotent ALTER),
   `subsections.description` (уже существовал).

## Открытые вопросы

- **Filter/sort в preview** (по layer / по flag / по timestamp / по edited/
  dropped) — 173 факта в одном списке — много.
- **Cycles + Methodology** — `cycles/weekly|event|quarterly` пока не
  читают `tone_preset` / `descriptions` (только extractor'ы). Нужно?
- **Per-ingest override тона** — сейчас только per-client. Может
  пригодиться когда один клиент делает разные интервью с разным регистром.
- **Embedding-dedup / speaker diarization / параллелизация chunks** — v2.

## Следующие разумные шаги (если пользователь скажет «продолжаем»)

1. **Filter/sort + поиск** в preview.
2. **Tone в cycles** — пропихнуть `tone_preset` в `cycles/*.py` `generate(...)`
   вызовы, чтобы weekly/event/quarterly артефакты тоже звучали единообразно.
3. **Backfill тестов**: sonnet fallback / preview-by-id / methodology
   endpoints / `_build_subsection_list` — на новых фичах тестов нет.

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

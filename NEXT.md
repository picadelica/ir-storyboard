# NEXT — где мы остановились

> Снимок оперативного состояния. Обновлять в конце каждой сессии (overwrite,
> не append). Цель — за 30 секунд понять, где находимся.
>
> Стабильная архитектура и инварианты — в `CLAUDE.md`. Сюда — только
> «здесь и сейчас».

---

**Последнее обновление:** 2026-05-22
**Ветка:** `feat/v2`
**Working tree:** clean (untracked: `12.jpeg` — не относится к проекту)
**HEAD:** `3e3aa08 fix: rename Research IngestPreviewOut to ResearchPreviewOut`

## Что в фокусе

Сессия 2026-05-22 закрыла четыре бага, обнаруженных при первом реальном
прогоне YouTube ingest на двухчасовом интервью `HdDNw-VxCvA`:

1. **Silent LLM chunk failures** (`7ed859e`). Из 9 chunks 8 молча отваливались,
   результат варьировался 20/28/7 фактов на одном и том же кэшированном
   транскрипте. Причина: `_generate_real` возвращал `""` на любую
   `anthropic.APIError`, `extract_facts_from_transcript` глотал пустой ответ
   без retry/лога. Добавлен retry 3× (backoff 2/5/10s), функция возвращает
   `(facts, chunk_errors)`, UI рисует оранжевый баннер "X of Y chunks failed".
   Skipped-карточки потеряли таймкод/quote — выровнял сериализацию с facts.
2. **Max-tokens cutoff + JSON repair** (`c2cd7c6`). После retry-фикса всё ещё
   падали 8/9 chunks — `chunk_errors.detail` показал `JSONDecodeError:
   Unterminated string at char ~13000`: Anthropic обрезал ответ на
   `max_tokens=4096`. Поднял до 16k + добавил `_repair_truncated_facts_json`
   (находит последний `},` в `facts[]`, закрывает массив, спасает N-1
   фактов). Chunk reduced 15→10 мин. Прогон дал 173 факта — ✅.
3. **Per-card edit before commit** (`af03dfa`). 173 факта в матрицу одним
   разом — без экспертного разбора. На FactCard / SkippedCard добавлена
   кнопка `edit` → форма с textarea (text_ru), dropdown (24 subsections),
   flag picker. Edits хранятся в localStorage; при commit отправляются как
   `overrides[]` с `kind`/`idx`/`text_ru`/`subsection_id`/`flag`. Backend
   `run_youtube_commit` применяет patch через `_apply_edit`. Legacy формат
   `{fact_idx, force_keep}` ещё поддерживается.
4. **Research /ingest/preview 500** (`4c3138f` + `3e3aa08`). Два бага в
   одной фиче. (a) `FactCandidate` dataclass без поля `rationale`, а
   `stub_classify` / `_classify_batch_real` передавали `rationale=...`
   → `TypeError`. (b) Два `class IngestPreviewOut` в `main.py` (старый
   Research + новый LLM-Report) — Python оставлял в namespace второй,
   Research-функция при runtime попадала в LLM-Report-модель и валилась
   с `ValidationError: 7 fields missing`. Старый переименован в
   `ResearchPreviewOut`.

**YouTube Ingest** — основная серия (`youtube-1..8` + post-фиксы) закрыта.

**LLM Report Ingest** — закрыт.

## Открытые вопросы

- **#4 history tab в UI** — endpoint
  `/api/clients/{id}/ingest/youtube/history` уже есть (`youtube-6`),
  но фронтенд-таба, который показывает список прошлых previews, нет.
- **Bulk-actions в preview** — multi-select чекбоксы и групповые
  drop/change-flag для скоростного разбора 100+ фактов. Не сделано.
- **chunks_failed retry** — если max_tokens cutoff повторится несмотря на
  16k, fallback на `LLM_GENERATE_MODEL=claude-sonnet-4-6` через env var.
- **Embedding-dedup / speaker diarization / параллелизация chunks** — v2.

## Следующие разумные шаги (если пользователь скажет «продолжаем»)

1. **#4 history tab**: отдельный экран со списком прошлых previews
   (id / video / parsed_at / facts_emitted / committed) + кнопка
   "reopen" → подгрузить preview_json и открыть в режиме разбора.
2. **Bulk-actions**: multi-select + bulk drop / bulk change-flag /
   bulk move-to-subsection. Особенно полезно когда LLM путает layer
   у целой группы фактов.
3. **filter/sort** в preview (по layer / по flag / по timestamp) —
   173 факта в одном списке — много.
4. **Hygiene refactor** (отдельная сессия):
   - Переименовать `channels/llm_report/` → `ingest/` (включает
     YouTube ingest, не только LLM-Report).
   - Развести два `def ingest_preview` в `main.py` (Research + LLM-Report)
     — имена функций сейчас shadow-ят друг друга (FastAPI работает, но
     это smell, и однажды приведёт к ещё одному 500 как у нас).

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

# NEXT — где мы остановились

> Снимок оперативного состояния. Обновлять в конце каждой сессии (overwrite,
> не append). Цель — за 30 секунд понять, где находимся.
>
> Стабильная архитектура и инварианты — в `CLAUDE.md`. Сюда — только
> «здесь и сейчас».

---

**Последнее обновление:** 2026-05-24
**Ветка:** `feat/v2`
**Working tree:** clean (untracked: `12.jpeg`, `DIARIZATION_PLAN.md`)
**HEAD = origin/feat/v2:** `7d48fb0 fix: stop persisting preview/factEdits/skippedEdits to localStorage`
**Прод:** в синке с HEAD, фронт и бэк пересобраны.

## Что сделано за сессию 2026-05-24

1. **cycles → 422** (`3f1eaa2`). `run_weekly/event/quarterly` поднимали
   `RuntimeError` при отсутствии narrative track — FastAPI отдавал голый
   500. Завернули три endpoint-а в `try/except RuntimeError →
   HTTPException(422)`. Фронт уже рендерит `detail` в CycleRunner.

2. **Plan tab** (`3ad5a45`). Новая вкладка между Matrix и Ingest.
   Список треков на квартал + форма «+ New track» (name / angle /
   target layers или subsections / priority). В CycleRunner при ошибке
   про tracks — amber-карточка с кнопкой «Открыть Plan →».

3. **USER_GUIDE.md** (`55b0993`). Руководство пользователя: 8
   task-oriented сценариев (новый клиент → план → 3 типа ingest →
   weekly → work → анализ дыр), глоссарий, справочник по 11 вкладкам,
   таблица ошибок, FAQ, known limitations. 517 строк.

4. **localStorage cleanup** (`7d48fb0`). YouTube ingest больше не
   сохраняет `preview` (200-500 KB JSON) и `factEdits`/`skippedEdits`
   в localStorage. Хранятся только `url`, `jobId`, `jobStatus`, `screen`
   (~200 байт). Если вернулся после того как preview уже готов —
   попадаешь на input с сохранённым URL, Preview берётся из History.

## Следующие разумные шаги

1. **Завести track для gonkaai на 2026Q2** → Plan-вкладка → + New track
   → повторить Weekly бриф.
2. **Filter/sort в YouTube preview** — 173 факта в одном списке тяжело
   читать. По layer / flag / timestamp / dropped.
3. **Tone в cycles** — пропихнуть `tone_preset` в `cycles/*.py`
   `generate(...)`, чтобы weekly/event/quarterly артефакты звучали
   единообразно с экстракторами.
4. **Backfill тестов** — cycles 422-wrap, Plan endpoints, localStorage
   cleanup.

## Открытые вопросы

- Edit/delete треков через UI — пока нет (backend только POST/GET).
- Per-ingest override тона — сейчас только per-client.
- Embedding-dedup / speaker diarization / параллелизация chunks — v2.

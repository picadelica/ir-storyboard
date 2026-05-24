# NEXT — где мы остановились

> Снимок оперативного состояния. Обновлять в конце каждой сессии (overwrite,
> не append). Цель — за 30 секунд понять, где находимся.
>
> Стабильная архитектура и инварианты — в `CLAUDE.md`. Сюда — только
> «здесь и сейчас».

---

**Последнее обновление:** 2026-05-24
**Ветка:** `feat/v2`
**Working tree:** clean (untracked: `12.jpeg` — не относится к проекту)
**HEAD = origin/feat/v2:** `3f1eaa2 fix: cycles — return 422 instead of 500 when plan is missing`

## Что только что сделано (сессия 2026-05-24)

**Cycles → 422 вместо 500 при отсутствии плана.** Пользователь нажал
Weekly бриф для `gonkaai` на 2026Q2 и получил безликий «500 Internal
Server Error». Причина — `run_weekly` поднимает `RuntimeError("No
narrative tracks for gonkaai in 2026Q2. Define a plan first.")`, и
FastAPI отдавал его как пустой 500. Завернул три cycle-endpoint'а
(`cycle_weekly` / `cycle_event` / `cycle_quarterly`) в `try/except
RuntimeError` → `HTTPException(422, detail=str(e))`. Фронт в
`CycleRunner.tsx:130` уже рендерит `(run.error as Error).message`, и
`api.ts:21` пакует detail в текст ошибки, так что пользователь теперь
видит реальное сообщение про отсутствие плана.

## ⚠ Что висит

1. **Прод не показывает новый фронтенд** (с прошлой сессии).
   `b563f8a`+`d5187ff` (Research extractor + YouTube redirect) на проде
   не видны: старая кнопка «Classify →», нет pink-баннера. Нужна
   пересборка frontend-контейнера:
   ```bash
   ssh root@216.57.108.107 'cd /opt/ir-storyboard && git pull && \
     docker compose build --no-cache frontend && \
     docker compose up -d frontend && \
     docker compose up -d --build backend'
   ```
   Бэк тоже пересобрать ради `3f1eaa2`. После — Cmd+Shift+R в браузере.
   Проверить: `docker exec ir-storyboard-frontend-1 grep -c "Process via YouTube" /usr/share/nginx/html/assets/*.js`.

2. **У gonkaai нет narrative track на 2026Q2.** Weekly cycle by design
   track-ориентирован. После деплоя `3f1eaa2` пользователь увидит
   422-ошибку с текстом про план — но чтобы реально получить бриф,
   нужно сначала завести track во вкладке Plan (name / target
   layers|subsections / angle), затем повторить Weekly.

## Открытые вопросы (с прошлой сессии, не решены)

- **Filter/sort в preview** (по layer / flag / timestamp / edited /
  dropped) — 173 факта в одном списке.
- **Cycles + Methodology** — `cycles/weekly|event|quarterly` пока не
  читают `tone_preset` / `descriptions` (только extractor'ы). Нужно?
- **Per-ingest override тона** — сейчас только per-client.
- **Backfill тестов** — sonnet fallback / preview-by-id / methodology
  endpoints / `_build_subsection_list` / новый 422-wrap на cycles.
- **Embedding-dedup / speaker diarization / параллелизация chunks** — v2.

## Следующие разумные шаги

1. **Frontend rebuild на проде** (см. блок «Что висит»).
2. **Завести track для gonkaai на 2026Q2** и прогнать Weekly заново.
3. Filter/sort в preview.
4. Tone в cycles — пропихнуть `tone_preset` в `cycles/*.py` `generate(...)`.

## Как обновлять этот файл

В конце сессии, когда что-то значимое сделано:

```
1. Обновить "Последнее обновление" — сегодняшняя дата.
2. Обновить "HEAD" — `git log -1 --oneline`.
3. Перезаписать раздел "Что только что сделано" — что закрыли в этой сессии.
4. Если открыты вопросы — в "Открытые вопросы".
5. Скорректировать "Следующий разумный шаг".
6. git add NEXT.md && git commit -m "chore: update NEXT.md"
```

# CLAUDE.md — гайд для будущего себя

> Это файл-контекст для Claude-сессий в этом репозитории. Аудитория — я в новой
> сессии без памяти о прошлой работе.
>
> **Boot sequence (читать в этом порядке, прежде чем отвечать пользователю):**
>
> 1. `NEXT.md` в корне репозитория — оперативное состояние (что только что
>    сделано, что открыто, что следующее). Если его нет — сказать пользователю.
> 2. `git log --oneline -15` — последние коммиты. Это правда о том, что
>    было сделано на самом деле.
> 3. `git diff --stat HEAD` + `git ls-files --others --exclude-standard` —
>    реальные изменения и реально untracked-файлы.
>    NB: `git status` в Cowork-sandbox через FUSE-mount периодически
>    выдаёт "Resource deadlock avoided" и ложно помечает кучу файлов как
>    " M". Не верить ему — верить `git diff --stat HEAD` (если пусто,
>    working tree чистый).
> 4. Этот файл (CLAUDE.md) — стабильная архитектура и конвенции.
>
> После шагов 1–4 коротко сказать пользователю: «Где остановились: …,
> следующий шаг: …». Без длинной портянки.
>
> **В конце сессии — обновить `NEXT.md`**, если что-то значимое сделано или
> остался open question. Лучше overwrite, не append: это снимок состояния,
> не журнал.

---

## Что это за проект (одним абзацем)

Внутренний инструмент IR-агентства. Ведёт **персистентную нарративную матрицу**
по каждому клиенту: 8 концентрических слоёв (от личной истории фаундера до
PEST-контекста) × 3 подсекции = 24 ячейки. Факты тегируются `green` / `red` /
`grey` (явный gap). Четыре канала сбора (offline_interview, online_interview,
archival, online_research) — каждый методологически ограничен по слоям. Три
производственных цикла (weekly / event / quarterly) рендерят артефакты для
NotebookLM. Аналитические вью (punch-list / interview questions / scorecard)
показывают пробелы как процесс, а не как отчёт.

## Стек

- **Backend:** Python 3.11+, FastAPI поверх ядра `ir_storyboard/` (чистый Python
  пакет), SQLite (single-file, без Alembic — миграции через идемпотентные
  `ALTER TABLE` в `db.init_schema`).
- **Frontend:** React + TypeScript + Vite + Tailwind, react-query как
  единственный стейт-менеджер. nginx-Dockerfile раздаёт build + проксирует
  `/api`.
- **Deploy:** `docker-compose up -d --build` на сервере агентства. SQLite-volume
  переживает рестарты.
- **Внешние сервисы:** Anthropic (Claude Haiku — batch-классификация и контент
  циклов), Tavily (веб-поиск для `online_research`). Без ключей — детерминистский
  keyword stub.

## Ключевые директории

```
ir_storyboard/          ← ядро (чистый Python пакет, без FastAPI/UI)
├── models.py           ← 8 канонических слоёв + dataclasses
├── matrix.py           ← CRUD над матрицей
├── llm.py              ← LLM-слой (Anthropic) + stub-фоллбек
├── db.py               ← SQLite + идемпотентные миграции
├── seed.py             ← пилотные данные Accumulator
├── channels/           ← 4 канонических канала (offline_interview /
│   ├── base.py             online_interview / archival / online_research)
│   ├── offline_interview.py
│   ├── online_interview.py
│   ├── online_research.py
│   └── archival.py
├── ingest/             ← оркестраторы поверх каналов (LLM Report + YouTube)
│   ├── ir.py              ← LLMReportIR, RawCitation (+ forced_channel)
│   ├── citations.py       ← extract_citations (respects forced_channel)
│   ├── transcript_to_ir.py ← Transcript → LLMReportIR adapter
│   ├── youtube_pipeline.py ← run_youtube_preview / run_youtube_commit
│   ├── snippet_anchor.py  ← AnchoredFact + timestamp URL + literal snippet
│   ├── layer_guard.py     ← LayerGuard: blocks L5/L6/L8 for online_interview
│   └── loaders/
│       ├── youtube_url.py    ← URL normalization + yt-dlp metadata
│       ├── youtube_audio.py  ← fetch_audio (yt-dlp → opus 16kHz mono)
│       ├── audio_chunker.py  ← split_audio (ffmpeg, ≤3600s + overlap)
│       └── transcriber.py    ← Transcriber protocol + faster-whisper / OpenAI / Deepgram
├── cycles/             ← weekly / event / quarterly
├── outputs.py          ← punch-list, interview qs, scorecard, NotebookLM bundle
├── workitems.py        ← Process Layer (fill_gap / interview / adjacent / cross_ref)
└── cli.py

backend/main.py         ← FastAPI приложение
frontend/src/
├── App.tsx             ← роутинг + табы
├── api.ts              ← typed API клиент
├── types.ts
└── components/
    ├── MatrixGrid.tsx        CellDrawer.tsx
    ├── Sidebar.tsx           CycleRunner.tsx
    ├── ArtifactsView.tsx     PunchListView.tsx
    ├── InterviewView.tsx     ScorecardView.tsx
    ├── ResearchView.tsx      WorkView.tsx
    └── IngestLLMReport.tsx   ← последний таб, LLM Report Ingest UI

tests/                  ← pytest, test_llm_report_*.py покрывают новый пайплайн
tests/fixtures/llm_report/
├── gonka_chatgpt_deep_research.docx   ← реальный вход (golden test)
└── libermans_gonka.expected.yaml      ← golden output (23 факта, 7 URL, 3 grey)
```

## Архитектурные инварианты (не нарушать)

1. **Provenance enforced.** Факт из online-канала без `http(s)://` URL ИЛИ без
   `evidence_snippet` ≥ 20 chars → `422`. Для `grey` (явный gap) snippet
   опционален. Для `offline_interview` обязателен `source_title` (например
   `"Interview with X 2026-05-12"`), snippet опционален.

2. **Каналы методологически ограничены по слоям.** L1–L3 могут заполняться
   только из `offline_interview`. `online_interview` может питать L1–L3 как
   исключение, если LLM-отчёт цитирует подкаст/интервью с фаундером. Веб-факт в
   L1/L2/L3 → `skipped` с warning, не в БД.

3. **LLM Report Ingest и YouTube Ingest — оркестраторы, не новые каналы.**
   Источники пишутся через один из четырёх существующих каналов (`online_interview`
   для YouTube — детерминистично, без URL-классификатора). Никаких новых
   `Channel` подклассов.

4a. **LayerGuard (YouTube Ingest).** `layer_guard.guard_layers()` вызывается
    до `MatrixMerger`. Факты в L5/L6/L8 → `skipped` с warning; аналитик
    может override на confirm-экране явным кликом. Никаких новых каналов.

4b. **forced_channel в RawCitation.** YouTube ingest выставляет
    `forced_channel='online_interview'` — `extract_citations` пропускает
    URL-классификатор и использует значение напрямую.

4. **Идемпотентность.** `add-client` с тем же id → fail (или `--force`).
   Повторный ингест того же LLM-отчёта → 0 new sources / 0 new facts (по
   нормализованному URL и нормализованному тексту факта). `synthesize_work_items`
   не дублирует open work-items.

5. **Иммутабельные факты.** Устаревший факт → новый факт с новым `captured_at`,
   старый остаётся. Никакого UPDATE на текст или snippet.

6. **Никаких `DELETE CASCADE` на work_items при удалении facts.** Закрытый
   факт должен оставлять след в work-item-е, который он закрыл.

7. **Миграции SQLite — только идемпотентные `ALTER TABLE`** в `db.init_schema`
   (детектить колонку → добавлять). Alembic не нужен.

8. **Frontend — react-query + Tailwind.** Без новых стейт-менеджеров и
   UI-китов. Эталон стиля — `PunchListView.tsx`.

9. **LLM-JSON — только через `llm.generate_json` / `llm.extract_json`.** Любой
   новый вызов модели за структурой идёт через единый примитив (терпимый парсер:
   проза-преамбула, ```-ограждение где угодно, широкий `{...}`/`[...]` спан,
   опц. ремонт обрезанного по max_tokens; + ретрай на пустой/битый ответ). НЕ
   писать локальный `json.loads(raw.strip("\`"))` — мы уже выгребли этот баг из
   6 мест. Долгие одиночные вызовы (>~45с: аудит/гайд/дедуп) — фоновым job-ом
   (`_start_llm_job` + `GET /jobs/{id}`, фронт `api.runJob`), не синхронно:
   NAT/файрвол рвёт простаивающее соединение на ~60с.

## Конвенции рабочего процесса

- **Коммиты:** `<series-N>: <subject>` для крупных серий
  (`task-3:`, `llm-5:`), `fix:` / `feat:` / `perf:` для одиночных. После
  каждой завершённой задачи серии — отдельный коммит.
- **Тесты:** `pytest tests/` локально перед коммитом. e2e-тест LLM-ingest —
  `tests/test_llm_report_e2e.py`, сходится к golden YAML инвариантами
  (количество фактов / URL / grey), не дословным diff'ом.
- **Branch:** работаем на `feat/v2`.
- **Уточняющие вопросы:** если задача неоднозначна — ОДИН вопрос
  пользователю и подождать. Не плодить варианты.

## Что осознанно НЕ сделано (документировано в README)

- Real-time collab editing (last-write-wins).
- Мобильный layout (desktop-only).
- Автогенерация `adjacent` / `cross_ref` work-items (требует LLM-судьи —
  создаются вручную через UI/API).

Что здесь стояло раньше и уже СДЕЛАНО (не переписывать заново):

- **Авторизация и роли** — гейт `_auth_gate` в `backend/main.py` закрывает
  `/api/*` (кроме `/api/health` и `/api/auth/*`) сессионной кукой `ir_session` от
  центрального Telegram-шлюза; `backend/auth.py` проверяет подпись локально,
  супер-админы — `IR_ADMIN_TIDS`, есть режим «Админ ↔ Эксперт». Без `AUTHGW_URL` +
  `SESSION_SECRET` гейт выключен (локальная разработка и тесты). **Basic Auth в
  Caddy нигде нет** — `401` от прод-`/api` даёт приложение, а не прокси.
- **История изменений факта** — сквозной журнал `fact_activity` (кто, что, когда,
  на какой версии методологии), а не только `captured_at`.

## Существующие task-spec'ы (исторический контекст)

- `CLAUDE_TASKS.md` — Process Layer (Tasks 1–5, закрыты): добавление клиентов,
  enforced provenance, work-items.
- `CLAUDE_TASKS_llm_report_ingest.md` — LLM Report Ingest (Tasks 1–8, закрыты,
  плюс ~14 post-fix коммитов).
- `LLM_REPORT_INGEST_SPEC.md` — контракт LLM Report Ingest.
- `LLM_REPORT_PROMPT_TEMPLATES.md` — промпты для эксперта (ChatGPT / Claude /
  Perplexity / Gemini).
- `DEPLOY.md` — деплой в production.
- `docs/restore.md` — runbook восстановления из бэкапа (три сценария аварии,
  где какие копии лежат, что проверено и что нет). Живой документ, в отличие от
  списка выше: правится по мере проверок.

Эти файлы — заархивированный контекст. Не редактировать без явной причины.
Новый объём работы — новый task-spec или серия коммитов с понятным префиксом.

## Оркестратор

Проект зарегистрирован в оркестраторе (UI: http://216.57.108.107:5000/ui/projects/ir-storyboard),
слаг: `ir-storyboard`. Правила и API: ~/Projects/conductor-orchestrator/docs/claudecode-onboarding.md;
реквизиты: `source ~/.config/conductor-orchestrator/credentials`; управление — скилл /conductor.
Деплой: workflow `deploy_ir_storyboard` (pull feat/v2 → compose build (оба файла) → up → health),
сервер otto 216.57.108.107, /opt/ir-storyboard. Руками по SSH не деплоить, на сервере не коммитить.
Паспорт (стадия/вехи/доки): `PATCH $REGISTRY/projects/ir-storyboard/state` (X-Api-Key).
В `input.projectId` запусков — `ir-storyboard`.

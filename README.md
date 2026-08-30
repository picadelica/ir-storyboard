# IR Storyboard

Внутренний инструмент IR-агентства. Ведёт **персистентную нарративную матрицу** по
каждому клиенту: 8 концентрических слоёв × 3 подсекции = 24 ячейки, каждая наполняется
атомарными фактами с обязательным происхождением (источник + дословная цитата).
Матрица — не отчёт, а рабочая поверхность: она показывает, что мы знаем, чего не знаем
и откуда это взялось, и из неё же собираются материалы для производства контента.

- **Backend** — Python 3.11+, FastAPI поверх чистого ядра `ir_storyboard/`, SQLite
  (single-file, миграции — идемпотентные `ALTER TABLE` в `db.init_schema`, без Alembic)
- **Frontend** — React + TypeScript + Vite + Tailwind, react-query как единственный
  стейт-менеджер; nginx раздаёт build и проксирует `/api`
- **Деплой** — `docker compose up -d --build` на сервере агентства, Caddy с HTTPS сверху
- **Внешние сервисы** — Anthropic (классификация, генерация, аудит), Tavily (веб-поиск),
  yt-dlp + Whisper/Deepgram (расшифровка). Без ключей — детерминистские стабы

## Карта документации

| Файл | Для кого |
|---|---|
| `README.md` | обзор системы — этот файл |
| `USER_GUIDE.md`, `docs/analyst-guide.md` | аналитик: как работать в интерфейсе |
| `CLAUDE.md` | разработчик/агент: архитектурные инварианты и конвенции |
| `NEXT.md` | оперативное состояние: что сделано только что, что открыто |
| `DEPLOY.md` | деплой в production, доступы, бэкапы |
| `docs/restore.md` | авария: восстановление из бэкапа (три сценария, где лежат копии) |
| `docs/onboarding-dev.md` | подключение нового разработчика: доступы, ключи, деплой, правила |
| `LLM_REPORT_INGEST_SPEC.md`, `YOUTUBE_INGEST_SPEC.md`, `POLISH_SPEC.md`, `CLAUDE_TASKS*.md` | заархивированные task-spec'ы (исторический контекст) |
| `LLM_REPORT_PROMPT_TEMPLATES.md` | промпты для эксперта (ChatGPT / Claude / Perplexity / Gemini) |

## Модель данных

### Матрица: 8 слоёв × 3 подсекции

Слои концентрические — от личной истории фаундера (интимность 1) к макро-контексту
(интимность 8):

```
L1 Founder Personal Story         1.1 Origin & Childhood · 1.2 Values & Beliefs · 1.3 Fears, Dreams & Identity
L2 Founder Professional Story     2.1 Path of expertise · 2.2 Founders & Core team relations · 2.3 Investors relations
L3 Community Culture, Values      3.1 Attraction & Selection · 3.2 Shared life · 3.3 Investors & Partners
L4 Community Prof. Experience     4.1 Expertise & Diversity · 4.2 Growth & Transformation · 4.3 Collective Failure Memory
L5 Clients — Stories              5.1 Client's challenge · 5.2 Moment of choice & trust · 5.3 Conflict & Honesty
L6 Product & Business             6.1 Architecture of solution · 6.2 Market context · 6.3 Product & company evolution
L7 Social Impact Vision           7.1 Vision of change · 7.2 Contradictions & Cost · 7.3 Legacy
L8 PEST Context                   8.1 Social · 8.2 Technology · 8.3 Political & Economical
```

Тексты подсекций (методология) редактируются в UI: глобальное описание + заметка
конкретного клиента. У методологии есть **версия** (`app_meta`) — она проставляется в
журнале действий, чтобы было видно, по каким правилам факт клали в ячейку.

### Факт

Атомарное утверждение в одной ячейке. Ключевые оси, которые важно не путать:

- **Флаг** — `green` (позитивный сигнал) / `red` (концерн) / `grey` (явный gap: «мы
  знаем, что не знаем»). Ячейка в сетке красится по доминирующему флагу.
- **Состояние** — `active` (в матрице и во всех генераторах), `review` (черновик на
  гейте ингеста: в матрице ещё нет, ждёт promote/reject), `rejected` (скрыт, но остаётся
  для аудита; восстановим).
- **Верификация** — отдельная ось: подтверждение факта ≠ одобрение факта.
  `approve ≠ verified`.
- **must-have** — звезда: синяя (обязательное со стороны клиента), фиолетовая (важное со
  стороны эксперта). Такие факты обязаны попасть в бриф.
- **Спикер** и **про какую компанию** — факт привязывается к сущности (`entities`:
  фаундеры, компании) и помечается, о чьей компании он. Тег «текущая компания» —
  двусторонний гард: факт про ДРУГУЮ компанию уезжает в L1/L2, про текущую — держится в
  L3–L8.

**Иммутабельность.** Текст факта никогда не UPDATE-ится. Любое «изменение» — новый факт
с новым `captured_at`, старый остаётся. Отсюда же механика «собранных» карточек: скрытый
факт = `state='rejected'` + `merged_into=<id активной>`, а `verification_note` различает
переименование спикера и настоящий мерж дублей.

**Журнал.** `fact_activity` — единственная точка правды по истории карточки (кто, что,
когда, при какой версии методологии). Экраны «Проверка фактов» и админка читают его.

## Каналы сбора и происхождение

Четыре канонических канала. Ограничение по слоям — методологическая защита: веб-поиск не
должен «домысливать» личные слои фаундера.

| Канал | Питает слои | Назначение |
|---|---|---|
| `offline_interview` | 1, 2, 3, 5 | интервью аналитика с фаундером — основной путь к L1–L3 |
| `online_interview` | 1, 2, 3, 4, 7 | подкасты, выступления, длинные интервью |
| `archival` | 2–8 | книги, filings, исторические материалы |
| `online_research` | 4, 5, 6, 7, 8 | веб-поиск, новости, аналитика |

**Provenance enforced.** Факт из online-канала без `http(s)://` URL или без
`evidence_snippet` ≥ 20 символов → `422`. Для `grey` snippet опционален, URL — нет. Для
`offline_interview` обязателен `source_title` (например `"Interview with X 2026-05-12"`),
snippet опционален.

**LayerGuard.** Факты, попадающие в чужой для канала слой, помечаются `skipped` с
предупреждением на экране превью; аналитик может явно настоять кликом.

## Наполнение матрицы

Все пути наполнения — **оркестраторы поверх тех же четырёх каналов**, а не новые каналы.
Каждый двухфазный: сначала превью (в БД ничего не пишется), потом коммит принятых фактов.

- **LLM report** (`ingest/pipeline.py`) — отчёт внешней модели (DOCX / PDF / MD / текст):
  извлечение цитат, классификация URL по каналам, разбор на атомарные факты, резолв
  сниппетов. Промпты для эксперта отдаёт `GET …/ingest/llm-report/prompt`.
- **YouTube** (`ingest/youtube_pipeline.py`) — ссылка → нормализация URL и метаданные
  (yt-dlp) → аудио → чанки ≤ 3600 с с нахлёстом (ffmpeg) → расшифровка → факты с
  таймкод-ссылками и дословными сниппетами. Канал всегда `online_interview`
  (детерминистично, через `forced_channel`, без URL-классификатора).
- **Audio** (`ingest/audio_pipeline.py`) — то же для загруженного файла (.m4a/.mp3/.wav/
  .ogg/.aac).
- **От клиента** — факты, присланные самим клиентом, с синей must-have-звездой.
- **Research** — веб-поиск (Tavily) по сгенерированным запросам, превью и коммит.
- **Мониторинг** — см. ниже.

**Идемпотентность.** Повторный ингест того же материала даёт 0 новых источников и 0 новых
фактов (дедуп по нормализованному URL и нормализованному тексту). Механический чип
«возможный дубль» на карточке превью подсвечивает похожий активный факт той же ячейки
(нормализация + Jaccard ≥ 0.55; при ≥ 0.85 факт до превью вообще не доходит).

**Гейт черновиков.** Если факт добавляет не владелец данных клиента, он создаётся в
состоянии `review` и ждёт promote/reject на экране очереди.

## Мониторинг выступлений

Вкладка «Мониторинг» в зоне Build. Автоматически **ничего не разбирается** — система
только приносит кандидатов.

- **Watchlist**: `youtube_channel` (обход через yt-dlp `--flat-playlist`, без скачивания),
  `rss` (любой фид, на stdlib), `search_query` (периодический веб-поиск по имени спикера).
  Практика показала: канал стоит заводить только если это личный канал спикера или
  подкаст с его постоянным участием; в остальных случаях — `search_query`.
- **Окно поиска** (`config.window`): `auto` — первый обход за год, дальше «с прошлой
  проверки минус неделя» (нахлёст на отставание поисковых индексов); либо явные
  `all` / `year` / `quarter` / `month`.
- **Фильтр до дорогой транскрипции**: дешёвый LLM-вызов только по метаданным судит
  независимо о двух вещах — тот ли это человек И запись ли это речи (профили LinkedIn,
  карточки спикеров конференций, пресс-релизы отсеиваются). Результат:
  `likely | unclear | unlikely` + одно предложение причины.
- **Кандидаты** уникальны по `client_id × norm_url` — повторная проверка не плодит
  находок и не тратит LLM-вызовы.
- «Разобрать» → переход на обычный экран YouTube-ингеста с предзаполненной ссылкой;
  `ingested` проставляется сам, когда после коммита появляется источник с этим URL.
- **Планировщик** — свой поток внутри приложения, `MONITORING_INTERVAL_MIN`
  (0/пусто = выключен, это дефолт).

**Обзор эпизода** (`digest.py`) — read-only материал поверх уже сделанной расшифровки:
мотив выступления, блоки с кликабельными таймкодами, ключевые цитаты, «между строк» и
сравнение с прошлыми выступлениями того же спикера. Собирается отдельным job-ом из кэша
расшифровок, поэтому путь фактов не трогает вообще. Цитата, которой нет в расшифровке
дословно, помечается `unverified` — это сигнал о качестве обзора, а не повод её выбросить.

## Здоровье матрицы

- **Scorecard** — 24 строки: green/red/grey и дата последнего апдейта. Измеримая метрика
  для клиента: «за квартал перевели 4 серых в зелёные, сняли 2 красных».
- **Punch-list** — untouched cells (фактов нет вообще), explicit gaps (есть grey),
  thinly covered (< 2 green). Каждая строка кликабельна — прямо в редактор ячейки.
- **Проверка фактов** — LLM-инструменты аудита, все длинные вызовы фоновыми job-ами:
  аудит утверждений, поиск дублей, поиск неатрибутированных фактов, генерация заголовков,
  переклассификация под текущую методологию (чанками, чтобы не свалиться в стаб на
  больших клиентах).
- **Interview questions** — серые ячейки L1–L3, переформулированные в вопросы для
  аналитика; LLM-гайд к интервью — отдельным job-ом.
- **Work-items** (`workitems.py`) — процессный слой: `fill_gap` / `interview` /
  `adjacent` / `cross_ref`, синтезируются из пробелов и не дублируются.

## Выдача

- **Brief** (`brief.py`) — обратная ингесту операция: фактология клиента + промпт
  аналитика → MD/JSON-пакет для вставки во внешнюю большую модель. Шаблоны брифов
  хранятся в БД; must-have-факты обязаны попасть в пакет.
- **Выгрузка** (`deliver.py`) — JSON матрицы: только тексты, без ссылок и цитат, плюс
  карточка компании.
- **Досье** (`dossier.py`) — консолидированная картина осведомлённости: exec-summary,
  синтез по каждому слою, метрики «сколько знаем» по слою.
- **Циклы** (`cycles/`) — **Weekly** (свежие факты в таргет-ячейках активного narrative
  track), **Event** (событие приземляется в ячейку, подтягиваются соседние слои ±1),
  **Quarterly** (вся матрица как нарративная арка inside-out или outside-in, с
  honesty-секцией). Результат — артефакт в markdown.
- **NotebookLM bundle** — куратированный пакет из выбранных артефактов.
- **Plan** — квартальный план и narrative tracks.

## Интерфейс

Зоны и вкладки (`frontend/src/App.tsx`):

```
Компания   Досье · Профиль
Map        Matrix
Build      LLM report · YouTube · Audio · От клиента · Research · Мониторинг · Work
Health     Scorecard · Punch-list · Проверка фактов · Interview Qs
Deliver    Brief · Выгрузка · Artifacts · Plan
```

Плюс методология, поиск по фактам, админка (журнал действий по всем компаниям,
пользователи).

## Доступ и роли

Логин делегирован центральному шлюзу `tg-authgw` (общий Telegram-бот, группы под
продукты); проверка сессии — локально, HMAC-SHA256 секретом продукта, cookie `ir_session`,
TTL 21 день. Без `AUTHGW_URL` + `SESSION_SECRET` гейт выключен — локальная разработка и
тесты идут без него.

- **Владелец данных клиента** — правит матрицу клиента напрямую.
- **Эксперт** — правит; факты в чужих клиентах уезжают в очередь `review`.
- **Супер-админ** (`IR_ADMIN_TIDS`, Telegram id через запятую) — переназначает владельцев,
  видит журнал по всем компаниям. Тумблер «работаю как эксперт» (cookie `ir_act_as`)
  отключает админ-привилегию, чтобы проверить систему глазами обычного пользователя.

## Запуск

### Production

```bash
git clone <repo> ir-storyboard && cd ir-storyboard
cp .env.example .env      # ключи, домен, роли — см. DEPLOY.md
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env up -d --build
```

Базовый `docker-compose.yml` биндит фронт на `127.0.0.1:${HOST_PORT:-8000}`;
prod-override добавляет Caddy с автоматическим Let's Encrypt для `${DOMAIN}`. SQLite живёт
в volume `storyboard-data` и переживает рестарты.

Схема мигрирует **на каждом запросе** (`get_conn` в `backend/deps.py`), поэтому новые
колонки доезжают при первом обращении к `/api`. Если читаешь прод-БД «голым»
`db.connect()` без `init_schema` — увидишь старую схему; это не поломка.

На сервере агентства деплой идёт **только** через workflow оркестратора
`deploy_ir_storyboard` — подробности и доступы в `DEPLOY.md`.

### Локальная разработка

```bash
# backend (порт 8080, БД data/matrix.db — gitignored, это НЕ прод)
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn backend.main:app --reload --port 8080

# frontend (прокси /api → :8080)
npm --prefix frontend install
npm --prefix frontend run dev -- --port 5180
```

В пустой БД — «+ Загрузить пилот (Accumulator)» в сайдбаре: демо-данные и квартальный план
с narrative tracks.

### Переменные окружения

| | |
|---|---|
| `ANTHROPIC_API_KEY` | без него весь LLM-слой — детерминистский keyword-стаб |
| `TAVILY_API_KEY` | веб-поиск (`online_research`, мониторинг, автозаполнение профиля) |
| `LLM_CLASSIFY_MODEL` / `LLM_GENERATE_MODEL` / `LLM_SUMMARIZE_MODEL` / `LLM_RECLASSIFY_MODEL` / `LLM_AUDIT_MODEL` / `LLM_GUIDE_MODEL` / `LLM_DIGEST_MODEL` / `LLM_MONITORING_MODEL` / `PDF_VISION_MODEL` | переопределение моделей (дефолты — Haiku на дешёвых операциях, Sonnet на разборе и аудите) |
| `TRANSCRIBER` | `local-faster-whisper` (дефолт) / `openai-whisper-1` / `deepgram-nova-3` |
| `OPENAI_API_KEY`, `DEEPGRAM_API_KEY` | ключи соответствующих провайдеров расшифровки |
| `MAX_CHUNK_SEC`, `CHUNK_OVERLAP_SEC` | нарезка аудио |
| `MONITORING_INTERVAL_MIN` | интервал автообхода watchlist; `0`/пусто = выключен (дефолт) |
| `AUTHGW_URL`, `AUTHGW_PRODUCT`, `SESSION_SECRET`, `IR_ADMIN_TIDS` | авторизация и роли |
| `AUDIO_UPLOADS_DIR`, `IR_BACKUPS_DIR` | пути хранения загрузок и бэкапов |
| `DOMAIN`, `ADMIN_EMAIL` | только для prod-override (Caddy) |

## Тесты

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -m "not network" -q     # сетевые (Whisper, реальный YouTube) отсеиваются
npm --prefix frontend run build                    # проверка типов фронта
```

56 файлов тестов. Опорные:
- `tests/test_llm_report_e2e.py` — golden-тест LLM-ингеста: реальный DOCX
  (`tests/fixtures/llm_report/`) сходится к ожидаемому YAML по инвариантам (число фактов,
  URL, grey), а не дословным diff'ом.
- `tests/test_provenance.py`, `test_layer_guard.py`, `test_placement_lock.py` —
  архитектурные инварианты.
- `tests/test_monitoring_watchlist.py`, `test_monitoring_digest.py` — мониторинг и обзоры.
- `tests/test_roles_api.py`, `test_client_data_safety.py` — роли и защита данных.

## API

Полная спецификация — `/api/docs` (FastAPI Swagger). Основные группы:

```
матрица       GET/POST /api/clients/{id}/cells/{sid}/facts · PATCH|DELETE /api/facts/{id}
              POST /api/facts/{id}/{promote|reject|restore|move|merge|attribute|speaker|
                                    about-company|title|must-have|verification}
              GET  /api/clients/{id}/{matrix|review-queue|placement-history|activity}
методология   GET/PATCH /api/methodology[/{sid}] · /api/clients/{id}/methodology[/{sid}]
              POST /api/clients/{id}/methodology/reclassify/{start|apply}
ингест        POST /api/clients/{id}/ingest/{preview|confirm}
              POST /api/clients/{id}/ingest/llm-report/preview-text
              POST /api/clients/{id}/ingest/{client-facts|other-pdf}/{preview|commit}
              GET  /api/clients/{id}/ingest/llm-report/prompt
мониторинг    GET/POST /api/monitoring/watchlist[/{id}/{pause|resume}] · GET /api/monitoring/candidates
              POST /api/monitoring/{check|digests/start|duplicate-hints}
              POST /api/monitoring/candidates/{id}/{ingest|dismiss}
здоровье      GET  /api/clients/{id}/{scorecard|punch-list|interview-questions|dossier}
              POST /api/clients/{id}/{audit|find-duplicates|find-unattributed}[/start]
              POST /api/clients/{id}/{interview-guide|generate-titles|dossier/generate}/start
выдача        POST /api/clients/{id}/cycles/{weekly|event|quarterly} · GET /api/clients/{id}/artifacts
              POST /api/clients/{id}/brief · GET /api/clients/{id}/matrix/{export.json|format.md}
              GET  /api/clients/{id}/notebooklm-bundle?artifact_ids=1,2,3
сущности      GET/POST /api/clients/{id}/{entities|mentioned-companies} · POST /api/entities/{id}/facts
работа        GET/POST /api/clients/{id}/work-items · PATCH /api/work-items/{id}
доступ        GET /api/auth/{me|status} · POST /api/auth/{start|logout} · GET /api/users[/overview]
              PUT /api/clients/{id}/{owner|hidden|mine} · GET /api/admin/activity
задания       GET /api/jobs/{id}        ← все длинные LLM-вызовы идут фоновым job-ом
```

Долгие одиночные вызовы (> ~45 с: аудит, гайд, дедуп, обзор) обязаны идти job-ом, а не
синхронно: NAT/файрвол рвёт простаивающее соединение примерно на 60-й секунде.

## Структура проекта

```
ir_storyboard/                ← ядро (чистый Python, без FastAPI/UI)
├── models.py                 ← 8 канонических слоёв + dataclasses
├── matrix.py                 ← CRUD над матрицей, роли, журнал, методология
├── db.py                     ← SQLite + идемпотентные миграции
├── llm.py                    ← единый LLM-слой (generate_json / extract_json) + стабы
├── channels/                 ← 4 канонических канала
├── ingest/
│   ├── pipeline.py           ← LLM Report: preview → commit
│   ├── youtube_pipeline.py   ← YouTube: URL → аудио → расшифровка → факты
│   ├── audio_pipeline.py     ← загруженный аудиофайл
│   ├── ir.py, citations.py, transcript_to_ir.py, snippet_anchor.py, snippet_resolver.py
│   ├── layer_guard.py        ← блокировка чужих для канала слоёв
│   ├── classifiers/          ← section→layer, source→channel, флаги
│   └── loaders/              ← docx / pdf / md / youtube_url / youtube_audio /
│                               audio_chunker / transcriber
├── watchlist.py, digest.py   ← мониторинг и обзор эпизода
├── verification.py           ← аудит, дубли, неатрибутированные, заголовки
├── dossier.py, brief.py, deliver.py, company.py, interview.py
├── cycles/                   ← weekly / event / quarterly
├── outputs.py                ← punch-list, interview qs, scorecard, NotebookLM bundle
├── workitems.py              ← процессный слой
├── backup.py, archive.py     ← бэкап/restore клиента, Wayback
└── cli.py

backend/
├── main.py                   ← FastAPI приложение
├── deps.py                   ← get_conn (здесь же миграция схемы)
├── auth.py                   ← клиент центрального auth-шлюза
└── routers/monitoring.py

frontend/src/
├── App.tsx                   ← зоны и вкладки
├── api.ts, types.ts, persist.ts
└── components/               ← MatrixGrid, CellDrawer, Ingest{LLMReport,YouTube,Audio,
                                 ClientFacts}, MonitoringView, EpisodeOverview,
                                 FactAuditView, DossierView, BriefComposer, AdminView, …

scripts/                      ← clone_client.py (песочница), seed_search_sources.py,
                                backup.sh / restore.sh, check_migration.sh, diff_with_golden.py
tests/                        ← pytest (56 файлов) + fixtures/llm_report/ (golden)
```

## Добавление клиента

Через UI: «+ New» в сайдбаре (владельцем становится создатель). Либо через CLI из seed-YAML
по образцу `seeds/stripe.yaml`:

```bash
python -m ir_storyboard add-client --from seeds/acme.yaml
```

`add-client` с существующим id падает (или `--force`). Другие команды CLI: `init`,
`seed-accumulator`, `weekly` / `event` / `quarterly`, `outputs`, `work-items`,
`backfill-snippets`, `demo`.

Дальше: завести фаундеров в «Упомянутые» (компания клиента — с флагом «текущая»), добавить
`search_query` в мониторинг («\<Фаундер\> \<Компания\> interview»), проверить Punch-list.

## Что осознанно НЕ сделано

- **Real-time collaborative editing** — конкурентное редактирование одной ячейки:
  last-write-wins.
- **Мобильный layout** — desktop-only.
- **Audit log diff-вью** — история есть в `fact_activity`, но без визуального было/стало.
- **`adjacent` и `cross_ref` work-items** не генерируются автоматически (требуют
  LLM-судьи) — создаются вручную.
- **Смысловой поиск** (эмбеддинги) — сейчас поиск лексический.
- **Гард «чья компания» в ingest-классификаторе** — правило пока живёт только в
  переклассификации; при первичном разборе `about_company` ещё не задан.
- **Автоматический разбор находок мониторинга** — принципиально: система приносит
  кандидатов, решение и разбор остаются за аналитиком.

Всё перечисленное добавляется поверх архитектуры без её слома.

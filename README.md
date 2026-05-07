# IR Storyboard

Внутренний инструмент для IR-агентства: ведёт **персистентную нарративную матрицу** по каждому клиенту, собирает факты из разных каналов и продуцирует артефакты для производства контента (Weekly бриф, Event-реакция, Квартальный досье).

Стек:
- **Backend** — Python + FastAPI поверх ядра `ir_storyboard` (SQLite-матрица, 4 канала, 3 цикла, аналитические выходы)
- **Frontend** — React + TypeScript + Vite + Tailwind, через nginx
- **Деплой** — `docker-compose up` на сервере агентства

## Что это решает

8 концентрических нарративных слоёв (от личной истории фаундера до PEST-контекста), факты с тегами green/red/grey, четыре канала сбора (online research / online interview / archival / offline interview), три рабочих цикла. Подробный разбор архитектуры — ниже.

## Запуск на сервере (production)

```bash
git clone <repo> ir-storyboard
cd ir-storyboard
HOST_PORT=8000 docker-compose up -d --build
```

Откройте `http://<server>:8000`. SQLite-база лежит в Docker-volume `storyboard-data`, переживает рестарты.

В пустой БД нажмите в сайдбаре «Загрузить пилот (Accumulator)» — подтянутся демо-данные из DE.pdf и план на 2026Q2 с тремя narrative tracks.

## Локальная разработка

```bash
# 1. Backend (порт 8080)
cd ir-storyboard
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8080

# 2. Frontend (порт 5173, проксирует /api → 8080)
cd frontend
npm install
npm run dev
```

Vite-конфиг (`frontend/vite.config.ts`) прокинет все запросы `/api/*` на бэкенд автоматически.

## Архитектура

### Матрица (данные)

Один клиент = 25 ячеек = 8 концентрических слоёв × 2–4 подсекции:

```
L1 Founder Personal Story        ← интимность 1 (ядро)
L2 Founder Professional Story
L3 Community Culture
L4 Community Professional Experience
L5 Clients — Stories
L6 Product & Business
L7 Social Impact Vision
L8 PEST Context                  ← интимность 8 (макро)
```

Каждая ячейка содержит факты с тегами:
- `green` — позитивный сигнал
- `red` — концерн / негативный сигнал
- `grey` — явная нехватка данных («мы знаем, что не знаем»)

В UI ячейка визуально отражает доминирующий тег (зелёная / красная / смешанная / серая / пустая).

### Каналы сбора

Каждый канал отвечает за свою зону. Это методологическая защита от того, что web-поиск пытается «домыслить» личные слои фаундера или надёргать устаревших фактов из обучающих данных LLM.

| Канал | Может питать слои | Назначение |
|---|---|---|
| `offline_interview` | 1, 2, 3, 5 | Интервью аналитика с фаундером — единственный путь к слоям 1–3 |
| `online_interview` | 1, 2, 3, 4, 7 | Подкасты, выступления, длинные интервью |
| `archival` | 2–8 | Книги, SEC filings, исторические материалы |
| `online_research` | 4, 5, 6, 7, 8 | Веб-поиск, новости, sell-side ноты |

Когда канал пробует записать факт в чужой слой, система фиксирует методологическое предупреждение в источнике, но не блокирует запись (аналитик может явно настоять).

### Циклы (производство)

**Weekly** — берёт активный narrative track из плана квартала, тянет 2–3 свежих green/red факта в его таргет-ячейках, выдаёт бриф для NotebookLM. Не сценарий — рычаг для аналитика, который превращает 4 часа просеивания в 30 минут редактирования.

**Event** — событие приземляется в конкретную ячейку, система автоматически подтягивает факты из соседних слоёв (±1 концентрически), сопоставляет с активными треками и выдаёт реактивный бриф с углами на 48 часов.

**Quarterly** — рендерит всю матрицу как нарративную арку через все 8 слоёв (inside-out от L1 к L8 или outside-in от L8 к L1). Honesty-секция показывает явные red и open research targets как часть рассказа, не как приложение.

### Аналитические выходы

Доступны как отдельные экраны в UI и через API:

- **Punch-list** — три категории: untouched cells (нет фактов вообще), explicit gaps (есть grey-маркеры), thinly covered (<2 green фактов). Каждая строка кликабельна — переход прямо в редактор ячейки.
- **Interview questions** — серые ячейки в слоях 1–3 переформулированы как шаблонные вопросы для аналитика, плюс конкретные пробелы под каждой темой.
- **Scorecard** — таблица 25 строк с количеством green/red/grey и датой последнего апдейта. Это та измеримая метрика, которую агентство показывает клиенту: «за квартал перевели 4 серых в зелёные, сняли 2 красных».
- **NotebookLM bundle** — куратированный markdown-пакет из выбранных артефактов для прямой загрузки в NotebookLM (или любой downstream-инструмент).

## API

Полная спецификация — `http://<server>/api/docs` (FastAPI Swagger). Ключевые эндпоинты:

```
GET    /api/clients
GET    /api/clients/{id}/matrix
GET    /api/clients/{id}/cells/{sid}/facts
POST   /api/clients/{id}/cells/{sid}/facts
PATCH  /api/facts/{id}
DELETE /api/facts/{id}
GET    /api/clients/{id}/plans/{quarter}/tracks
POST   /api/clients/{id}/plans/{quarter}/tracks
POST   /api/clients/{id}/cycles/{weekly|event|quarterly}
GET    /api/clients/{id}/artifacts
GET    /api/artifacts/{id}
GET    /api/clients/{id}/punch-list
GET    /api/clients/{id}/interview-questions
GET    /api/clients/{id}/scorecard
GET    /api/clients/{id}/notebooklm-bundle?artifact_ids=1,2,3
```

## Структура проекта

```
ir-storyboard/
├── README.md
├── docker-compose.yml
├── schema.sql                      ← SQLite-схема матрицы
├── ir_storyboard/                  ← ядро (Python package)
│   ├── models.py                   ← 8 канонических слоёв + dataclasses
│   ├── matrix.py                   ← CRUD над матрицей
│   ├── llm.py                      ← stub-классификатор + точки расширения
│   ├── seed.py                     ← пилотные данные Accumulator
│   ├── channels/                   ← 4 канала сбора
│   ├── cycles/                     ← 3 цикла (weekly / event / quarterly)
│   ├── outputs.py                  ← punch-list, interview qs, scorecard, NotebookLM bundle
│   └── cli.py                      ← CLI (для скриптов и smoke-теста)
├── backend/
│   ├── main.py                     ← FastAPI приложение
│   ├── requirements.txt
│   └── Dockerfile
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.js
    ├── nginx.conf                  ← nginx для production раздачи + проксирования /api
    ├── Dockerfile
    └── src/
        ├── App.tsx                 ← роутинг + табы
        ├── api.ts                  ← typed API клиент
        ├── types.ts
        ├── lib/cellColor.ts        ← модель цвета ячейки
        └── components/
            ├── Sidebar.tsx         ← клиенты + план + кнопки циклов
            ├── MatrixGrid.tsx      ← цветная сетка матрицы
            ├── CellDrawer.tsx      ← редактор фактов
            ├── CycleRunner.tsx     ← модал запуска цикла
            ├── ArtifactsView.tsx   ← список + рендер markdown + bundle
            ├── PunchListView.tsx
            ├── InterviewView.tsx
            └── ScorecardView.tsx
```

## Добавление нового клиента

1. Создать seed YAML по образцу `seeds/stripe.yaml`:
   ```yaml
   client:
     id: acme-inc
     name: Acme Inc.
     sector: saas
   founder_name: Jane Smith
   initial_quarter: 2026Q3
   seed_facts: [...]
   seed_tracks: [...]
   ```
2. Загрузить через CLI: `python -m ir_storyboard add-client --from seeds/acme.yaml`
   или через UI: кнопка «+ New» в сайдбаре → таб «Import YAML».
3. Проверить в UI: открыть клиента → таб «Punch-list» → убедиться что пустые ячейки соответствуют ожидаемому покрытию.
4. Work-items создаются автоматически при импорте. Открыть таб «Work» → запустить «Synthesize» если нужно обновить backlog.

## Provenance rules

Каждый факт из online-каналов (`online_research`, `online_interview`, `archival`) требует:

- `source_url` начинающийся с `http(s)://`
- `evidence_snippet` ≥ 20 символов — дословная цитата из источника

Факт из `offline_interview` требует `source_title` (например `"Interview with X 2026-05-12"`). Snippet опционален.

Для фактов с флагом `grey` (явная нехватка данных) snippet необязателен даже для online-каналов — URL по-прежнему требуется.

Нарушение → API возвращает `422 Unprocessable Entity` с описанием правила.

Для существующих фактов без snippet используйте CLI: `python -m ir_storyboard backfill-snippets --client <id> --interactive`

## Daily workflow: work-items

```
1. Открыть таб «Work» → посмотреть Queued колонку
2. Кликнуть карточку → «Claim» (берёт на себя, статус → in_progress)
3. Собрать факт → добавить в соответствующую ячейку через Matrix → CellDrawer
4. Система автоматически переводит fill_gap/interview в needs_review
5. Открыть work-item снова → «Done» + указать id закрывающего факта
6. Конец недели: запустить Weekly бриф → worklog обновится автоматически
```

CLI-альтернатива:
```bash
python -m ir_storyboard work-items list --client stripe --status queued,in_progress
python -m ir_storyboard work-items claim 42 --as Dmitry
python -m ir_storyboard work-items complete 42 --fact 178 --notes "интервью 2026-05-14"
python -m ir_storyboard work-items synthesize --client stripe
```

## Подключение настоящего LLM и веб-поиска

В `ir_storyboard/llm.py` реализован полный LLM-слой с автоматическим переключением между режимами:

- Если `ANTHROPIC_API_KEY` установлен — используется Claude (Haiku) для батчевой классификации и генерации контента циклов
- Если `TAVILY_API_KEY` установлен — используется Tavily для веб-поиска в `online_research` канале
- Без ключей — deterministic keyword stub (работает offline, хуже качество)

Батчевая классификация (10–20 фактов одним вызовом) в ~15× дешевле pay-per-fact. Ключи прописывать в `.env` на сервере.

## Что осознанно НЕ сделано

- **Авторизация и multi-user.** Сервер — общий доступ внутри агентства. Для ограничения доступа — Basic Auth в Caddy или IP-allowlist.
- **Версионирование фактов.** Каждый факт иммутабелен с `captured_at`. Устаревший факт → добавляется новый.
- **Real-time collaborative editing.** Конкурентное редактирование одной ячейки → last-write-wins.
- **Мобильный layout.** Десктоп-only.
- **Audit log diff-вью.** История через `captured_at`, без визуального было/стало.
- **`adjacent` и `cross_ref` work-items** не генерируются автоматически (требуют LLM-судьи) — создаются вручную через UI или API.

Все эти пункты добавляются поверх архитектуры без её слома.

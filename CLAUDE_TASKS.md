# План работ для Claude Code — Process Layer

> **Аудитория этого документа — Claude Code**, запущенный в этой папке.
> Прочитай этот файл целиком, потом выполняй задачи строго по порядку (Task 1 → 2 → 3 → 4 → 5).
> После каждой завершённой задачи — `git add . && git commit -m "<task-N>: <subject>"`.
> Если задача неоднозначна — задай ОДИН уточняющий вопрос аналитику и подожди ответа.

---

## Контекст

`ir-storyboard` — внутренний инструмент IR-агентства (FastAPI + SQLite ядро `ir_storyboard/` + React/TS фронт `frontend/`). Уже работает: 8-слойная матрица, 4 канала сбора (online_research / online_interview / archival / offline_interview), 3 цикла (weekly / event / quarterly), 3 read-only аналитических вью (punch-list / interview questions / scorecard), seed-сценарий «Accumulator».

Подробно — `README.md`. Перед стартом перечитай: `schema.sql`, `ir_storyboard/models.py`, `ir_storyboard/matrix.py`, `ir_storyboard/outputs.py`, `backend/main.py`, `frontend/src/App.tsx`, `frontend/src/components/PunchListView.tsx`.

## Зачем эти задачи

После v1 в проде остались три дыры в процессе:

1. **Добавить нового клиента — только демо-сидом «Accumulator».** Произвольного клиента можно создать через `POST /api/clients`, но это пустой grid — без ввода фаундера, без seed-фактов, без стартового плана, без автоматически поставленных задач на исследование.
2. **Источник у факта не enforced.** В `schema.sql` `facts.source_id` nullable, в `FactCreate` `source_title`/`source_url` опциональны и default `""`. Поле `evidence_snippet` (точная цитата) отсутствует. LLM-предложенный факт легко попадает в матрицу без следа.
3. **Punch-list / interview-questions — это вью, не процесс.** Аналитик видит «10 пустых ячеек», но не может взять одну на себя, отметить «закрыто», связать с пришедшим фактом, проставить дедлайн или назначить другому. Циклы (weekly/event/quarterly) — это ПРОДАКШН артефактов, а не РАБОТА по сбору данных.

Закрываем эти три дыры. Не ломая то что работает (4 канала + 3 цикла + 3 вью + Accumulator demo).

**Принципы, которые нельзя нарушать:**

- **Provenance.** Факт из online-каналов без URL и без `evidence_snippet` — невалиден. Точка.
- **Idempotency.** Повторный `add-client` с тем же id — fail с понятной ошибкой (или `--force`). Повторный `synthesize_work_items` не дублирует open work-items.
- **Никаких `DELETE CASCADE` на work_items** при удалении facts — наоборот, закрытый факт должен оставлять след в work-item-е, который он закрыл.
- **SQLite-only миграции** делаем через явные `ALTER TABLE` в `db.init_schema` (детектить колонку → добавлять). Никакого Alembic — это overkill для текущего стека.
- **Frontend на react-query** (см. `PunchListView.tsx`) — без новых стейт-менеджеров.

---

## Промпт для Claude Code (копировать в чат)

```
Прочитай CLAUDE_TASKS.md в этой папке — это пошаговый план закрытия Process Layer
поверх существующего ir-storyboard (FastAPI + SQLite + React).

Сначала освежи контекст: schema.sql, ir_storyboard/models.py, ir_storyboard/matrix.py,
ir_storyboard/outputs.py, backend/main.py, frontend/src/App.tsx,
frontend/src/components/PunchListView.tsx.

Поведение:
- Выполняй Task 1 → 2 → 3 → 4 → 5 строго по порядку.
- После каждой завершённой задачи делай git commit "<task-N>: <subject>".
- Перед стартом каждой задачи перечитывай её DoD.
- Не ломай обратную совместимость: существующие эндпоинты (GET /api/clients,
  POST /api/clients, /punch-list, /interview-questions, /scorecard, /cycles/*),
  seed Accumulator, прохождение weekly/event/quarterly должны продолжать работать.
- Миграции схемы делай только через идемпотентные ALTER TABLE в
  ir_storyboard/db.py::init_schema (детектируй наличие колонки/таблицы и добавляй).
- Все новые поля в pydantic-моделях бэкенда — с валидацией, не Optional[]=None
  «на всякий случай».
- Фронтовый код держи в стиле PunchListView.tsx: react-query + Tailwind, без новых
  библиотек.

Перед стартом задай ОДИН блок уточняющих вопросов:
- Wayback Save Page Now включать на запись каждого online-источника или достаточно
  lookup-only? (default: lookup-only синхронно, save — асинхронно с retry)
- Новый таб «Work» в основной навигации или вкладка внутри Punch-list? (default:
  отдельный таб «Work», Punch-list остаётся read-only вью как сейчас)
- Делать ли реальный HEAD-чек URL'а на запись факта или достаточно валидации
  формата? (default: валидация формата + асинхронный health-check на фоне)

После ответа стартуй с Task 1 и не останавливайся, пока не дойдёшь до Task 5
или не упрёшься в блокер. Используй TodoWrite для трекинга.
```

---

## Task 1 — `add-client` end-to-end (Backend + CLI + Frontend)

Цель: одно действие создаёт клиента, заводит сетку, импортирует seed-факты с источниками, ставит первый план квартала и (после Task 3) генерит начальный backlog work-items.

### 1.1 Backend

**Расширить** `POST /api/clients` или добавить `POST /api/clients:create-with-seed` — на твоё усмотрение. Я бы оставил `POST /api/clients` для простого upsert (как сейчас), а добавил **новый** `POST /api/clients/{id}/import-seed`, чтобы поведение сидирования было идемпотентным и отделимым.

Pydantic-модель `ClientSeedIn`:

```python
class SeedFactIn(BaseModel):
    subsection_id: str            # '1.1', '6.2', etc.
    text: str
    flag: Literal["green", "red", "grey"]
    channel: Literal["online_research", "online_interview", "archival", "offline_interview"]
    source_title: str = ""
    source_url: str = ""
    evidence_snippet: str = ""    # обязательно для online-каналов после Task 2

class SeedTrackIn(BaseModel):
    name: str
    angle: str = ""
    target_layer_ids: list[int] = []
    target_subsection_ids: list[str] = []
    priority: int = 1

class ClientSeedIn(BaseModel):
    client: ClientOut             # id, name, sector, one_liner
    founder_name: str = ""
    founder_handle: str = ""      # @handle / linkedin slug
    aliases: list[str] = []
    initial_quarter: str | None = None   # e.g. '2026Q3'
    seed_facts: list[SeedFactIn] = []
    seed_tracks: list[SeedTrackIn] = []
    notes: str = ""
```

Логика:

1. `matrix.upsert_client(...)` + `matrix.ensure_full_grid(...)`.
2. Сохранить `founder_name`, `founder_handle`, `aliases` — это потребует расширения таблицы `clients` (см. ниже).
3. Для каждого `seed_facts[i]` — `add_source` + `add_fact` через существующий `matrix.py` (он сам разруливает методологический warning).
4. Если задан `initial_quarter` и `seed_tracks` — `upsert_plan` + `add_track` для каждого.
5. После Task 3 — здесь же синтезировать initial work-items.
6. Возврат: `{client, fact_count, source_count, track_count, work_items_count}`.

**Миграция `clients`** (в `db.py::init_schema`, идемпотентно):

```sql
ALTER TABLE clients ADD COLUMN founder_name TEXT DEFAULT '';
ALTER TABLE clients ADD COLUMN founder_handle TEXT DEFAULT '';
ALTER TABLE clients ADD COLUMN aliases TEXT DEFAULT '[]';   -- JSON array
ALTER TABLE clients ADD COLUMN notes TEXT DEFAULT '';
```

В `db.init_schema` сделать детект: если колонок нет — добавить. Существующие БД с Accumulator не должны сломаться.

**Идемпотентность:** если клиент с таким `id` уже существует И у него ≥1 факт — `import-seed` без `?force=true` возвращает 409 с текстом «Client already seeded, use ?force=true to overwrite». С `force=true` — старые факты НЕ удаляются (provenance важнее), но новые seed_facts добавляются как обычные записи с свежим `captured_at`.

### 1.2 CLI

В `ir_storyboard/cli.py` добавить команду:

```bash
python -m ir_storyboard add-client --from seeds/stripe.yaml
python -m ir_storyboard add-client --id stripe --name "Stripe" --sector fintech \
    --founder "Patrick Collison" --no-seed-facts
```

**Формат YAML** (`seeds/stripe.yaml`):

```yaml
client:
  id: stripe
  name: Stripe
  sector: fintech
  one_liner: Internet payments infrastructure
founder_name: Patrick Collison
founder_handle: patrickc
aliases:
  - Stripe Inc.
  - Stripe Inc
initial_quarter: 2026Q3
seed_tracks:
  - name: "AI infra positioning"
    angle: "Stripe — единственный rails для AI-нативных компаний"
    target_layer_ids: [6, 8]
    target_subsection_ids: ["6.1", "6.3", "8.2"]
    priority: 1
seed_facts:
  - subsection_id: "2.1"
    text: "Patrick Collison founded Auctomatic at 17, sold for $5M to Live Current."
    flag: green
    channel: archival
    source_url: https://en.wikipedia.org/wiki/Patrick_Collison
    source_title: Patrick Collison — Wikipedia
    evidence_snippet: >
      In 2007, while still in school, Collison founded Auctomatic with his brother John;
      it was acquired by Live Current Media in 2008 for US$5 million.
notes: "Целевой клиент пилота за рубежом."
```

Положи рабочие примеры в `seeds/`: `seeds/stripe.yaml`, `seeds/accumulator.yaml` (последний — реверс из текущего `seed.py`, чтобы demo-данные могли перепрогоняться через универсальный путь).

### 1.3 Frontend

В `Sidebar.tsx`:

1. Кнопка «+ Новый клиент» рядом с «Загрузить пилот (Accumulator)».
2. По клику — drawer/модал с формой:
   - Базовое: id (slug, валидация: `[a-z0-9-]+`), name, sector, one_liner, founder_name, founder_handle.
   - Опционально: textarea «Импортировать seed YAML» + кнопка «Загрузить файл».
3. Submit → `POST /api/clients` (upsert) → если есть seed → `POST /api/clients/{id}/import-seed`.
4. По успеху — закрыть drawer, выбрать нового клиента в Sidebar, тост «Создан client X · M фактов · K work-items».

Используй `useMutation` из react-query. Стилистика — как у существующих кнопок Sidebar.

### 1.4 Тесты

`tests/test_add_client.py` (новый файл):

- `import-seed` пустой → клиент с гридом, 0 фактов, ≥0 work-items (после Task 3 — N).
- `import-seed` с 3 seed_facts → 3 факта в матрице, 3 source-записи.
- Повторный `import-seed` без force → 409.
- `import-seed?force=true` поверх существующего → seed_facts добавлены, старые не удалены.
- CLI smoke: `python -m ir_storyboard add-client --from tests/fixtures/dummy.yaml` → 0 ошибок, exit 0.

### DoD Task 1

- `pytest -q` зелёный (включая существующие).
- `python -m ir_storyboard add-client --from seeds/stripe.yaml` создаёт клиента с фактами и треком за <1 сек.
- В UI кнопка «+ Новый клиент» работает, после создания клиент сразу выбран.
- README дополнен разделом «Adding a new client» (3–5 шагов: положить seed YAML, нажать кнопку или вызвать CLI, проверить punch-list).
- Существующий `POST /api/clients/{id}/seed-accumulator` продолжает работать (НЕ переписан под новый путь — там специфичные демо-данные из `seed.py`).

Коммит: `task-1: add-client end-to-end (CLI, API, Sidebar form, seed YAML format)`.

---

## Task 2 — Source provenance enforcement

Закрываем дыру: факт из online-канала без URL и без цитаты — это не факт.

### 2.1 Schema

В `db.init_schema` добавить идемпотентные миграции:

```sql
-- facts: добавить evidence_snippet (литеральная цитата из источника)
ALTER TABLE facts ADD COLUMN evidence_snippet TEXT DEFAULT '';

-- sources: расширить provenance
ALTER TABLE sources ADD COLUMN accessed_at TIMESTAMP;
ALTER TABLE sources ADD COLUMN content_hash TEXT;        -- sha256 raw response
ALTER TABLE sources ADD COLUMN archive_url TEXT;         -- Wayback snapshot
ALTER TABLE sources ADD COLUMN publisher TEXT DEFAULT '';
ALTER TABLE sources ADD COLUMN author TEXT DEFAULT '';
ALTER TABLE sources ADD COLUMN published_at DATE;
```

Не добавляй UNIQUE-индекс на `sources.url` — у offline_interview url пустой/internal, у других может быть один URL для разных дат захвата (legitimate). Дедуп по `content_hash` выше уровнем (см. 2.2).

### 2.2 Validation

В `matrix.add_fact` и `matrix.add_source` (или в новом `matrix.add_fact_with_source`) — слой валидации:

```
RULE 1 — online_research / online_interview / archival:
  source.url не пустой И начинается с http(s)://
  fact.evidence_snippet длиной ≥ 20 символов

RULE 2 — offline_interview:
  source.title не пустой (например "Interview with Patrick 2026-05-12")
  source.url может быть пустой ИЛИ начинаться с internal://
  fact.evidence_snippet опционален

RULE 3 — любой канал:
  Если flag = grey ("we know we don't know") — evidence_snippet опционален,
  но source всё равно требуется (хотя бы offline-интервью с пометкой "asked, no answer")
```

Нарушение — `ValueError` с понятным сообщением вида `"online_research fact requires non-empty evidence_snippet (≥20 chars)"`. На API это конвертируется в `422 Unprocessable Entity`.

### 2.3 Wayback integration

Новый модуль `ir_storyboard/archive.py`:

```python
def lookup_snapshot(url: str, timestamp: str | None = None) -> str | None:
    """GET https://archive.org/wayback/available?url=<url>[&timestamp=<ts>]
    Возвращает closest.url или None."""

def save_snapshot(url: str, timeout: float = 30.0) -> str | None:
    """POST https://web.archive.org/save/<url>
    Возвращает архивный URL или None при сбое. Никаких retry в синхронном пути."""
```

Поведение по умолчанию (см. ответ на уточняющий вопрос в промпте):

- На `add_source` для online_research / archival / online_interview — синхронно вызывать `lookup_snapshot`. Если есть — сразу записать в `archive_url`.
- Если `lookup_snapshot` вернул None — поставить таск в фоновую очередь (минимально — `threading.Thread`, не блокировать API) на `save_snapshot`. По завершении — апдейт `sources.archive_url`.
- Кэш в памяти процесса для `lookup_snapshot` — чтобы дребезг не бил по archive.org.

Rate-limit на save: ≤1/сек, ≤200/час. Если бьёшь лимит — backoff и retry через час.

### 2.4 API

`FactCreate` (в `backend/main.py`):

```python
class FactCreate(BaseModel):
    text: str
    flag: Literal["green", "red", "grey"]
    channel: Literal[...]
    source_title: str = ""
    source_url: str = ""
    evidence_snippet: str = ""
    confidence: float = 1.0

    @model_validator(mode="after")
    def _check_provenance(self):
        online = self.channel in ("online_research", "online_interview", "archival")
        if online and not self.source_url.startswith(("http://", "https://")):
            raise ValueError("online channels require source_url starting with http(s)://")
        if online and len(self.evidence_snippet.strip()) < 20:
            raise ValueError("online channels require evidence_snippet ≥20 chars (literal quote)")
        if self.channel == "offline_interview" and not self.source_title.strip():
            raise ValueError("offline_interview requires source_title (e.g., 'Interview with X 2026-05-12')")
        return self
```

`FactOut` дополнить полями: `evidence_snippet`, `archive_url`, `publisher`, `published_at`.

### 2.5 Frontend

В `CellDrawer.tsx`:

1. Под полем «Source URL» добавить textarea «Цитата (≥20 символов)» — обязательная для online-каналов, опциональная для offline.
2. При смене канала — динамически проставлять required-флаг на цитату.
3. Под URL — чек-маркер «Заархивировано в Wayback» если `archive_url` присутствует, или «Архивируем…» если факт только что создан.
4. На отображении факта в drawer'е — clickable ссылка на оригинал + маленькая иконка на архивный snapshot.

### 2.6 Backfill

Для существующих фактов (Accumulator demo) — не мигрировать насильно. Добавить отдельный CLI-скрипт `python -m ir_storyboard backfill-snippets --client accumulator --interactive`, который для каждого факта без `evidence_snippet` показывает `(text, source_url)` и просит у аналитика цитату. Фоновый аналитик закроет это руками.

### 2.7 Тесты

`tests/test_provenance.py`:

- `add_fact` channel=online_research, url пустой → ValueError.
- `add_fact` channel=online_research, snippet="short" (10 chars) → ValueError.
- `add_fact` channel=offline_interview, source_title пустой → ValueError.
- `add_fact` channel=offline_interview, source_title="Interview with X", snippet пустой → OK.
- `lookup_snapshot` mock'ан через `respx` — sources.archive_url проставляется.
- API: POST /facts с broken payload → 422 с понятным detail.

### DoD Task 2

- Все тесты зелёные.
- Попытка добавить факт через UI без цитаты на online-канале — кнопка «Save» disabled с подсказкой.
- В CellDrawer у каждого факта на online-канале видна цитата + ссылка на Wayback.
- Существующие демо-факты (Accumulator) показываются с пустым snippet — не ломаются, но `backfill-snippets` команда работает.
- README дополнен разделом «Provenance rules».

Коммит: `task-2: source provenance — evidence_snippet, Wayback, validation gates`.

---

## Task 3 — Work-item layer (поверх Punch-list)

Punch-list, interview questions и thin-coverage остаются как **сигналы**, но появляется **состояние**: claim / in_progress / done / blocked. Аналитик берёт пункт, закрывает фактом, видит трекинг.

### 3.1 Schema

```sql
CREATE TABLE IF NOT EXISTS work_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       TEXT NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    type            TEXT NOT NULL CHECK(type IN (
                       'fill_gap',         -- empty cell → fill any fact
                       'discover',         -- initial scan over a brand-new layer
                       'verify',           -- low-confidence / single-source fact needs cross-check
                       'deepen',           -- thin coverage (<2 green) — add more facts
                       'interview',        -- inner-layer (1-3) gap, requires interview channel
                       'adjacent',         -- research a related entity (investor, partner)
                       'cross_ref'         -- two facts in same cell contradict
                   )),
    subsection_id   TEXT REFERENCES subsections(id),    -- nullable for client-level tasks
    source_signal   TEXT NOT NULL CHECK(source_signal IN (
                       'empty_cells', 'known_gaps', 'thin_coverage',
                       'low_confidence', 'manual', 'track_alignment',
                       'contradiction'
                   )),
    status          TEXT NOT NULL DEFAULT 'queued' CHECK(status IN (
                       'queued', 'in_progress', 'needs_review',
                       'done', 'blocked', 'cancelled'
                   )),
    assignee        TEXT DEFAULT '',                    -- analyst handle / name
    priority        INTEGER DEFAULT 3,                  -- 1 (high) .. 5 (low)
    title           TEXT NOT NULL,
    rationale       TEXT DEFAULT '',
    suggested_channel TEXT,                             -- one of ALL_CHANNELS
    related_track_id INTEGER REFERENCES narrative_tracks(id) ON DELETE SET NULL,
    related_fact_id INTEGER REFERENCES facts(id) ON DELETE SET NULL,
    due_date        DATE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at    TIMESTAMP,
    notes           TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_wi_client_status ON work_items(client_id, status);
CREATE INDEX IF NOT EXISTS idx_wi_assignee ON work_items(assignee, status);
```

### 3.2 Generator

Новый модуль `ir_storyboard/workitems.py`:

```python
def synthesize_work_items(conn, client_id: str, *,
                          quarter: str | None = None) -> list[int]:
    """Сравнивает текущее состояние матрицы с активным планом квартала
    и создаёт НОВЫЕ work-items для тех зон, где их ещё нет в активных
    статусах (queued / in_progress / needs_review).

    Возвращает список id созданных work-items."""
```

Правила (минимум):

1. **`fill_gap`** на каждую subsection из `matrix.empty_cells(client_id)`. `suggested_channel` — первый из `LayerSpec.primary_channels`. Priority 3, или 2 если subsection в `target_subsection_ids` любого активного track'а.
2. **`interview`** на каждую subsection из `matrix.empty_cells` ИЛИ `cells_with_known_gaps`, у которой `layer_id ∈ {1, 2, 3}`. `suggested_channel = offline_interview`. Title использует `outputs.QUESTION_TEMPLATES[sid]` если есть.
3. **`deepen`** на каждую subsection из `matrix.thinly_covered_cells(client_id, min_green=2)` где `n_green ≥ 1` и `n_grey == 0`. Priority 4, или 3 если в active track.
4. **`verify`** на каждый факт с `confidence < 0.7` или единственным источником (`COUNT(*) FROM facts WHERE source_id = X` = 1) — чёрный ящик low-trust.
5. **`adjacent`** не генерим автоматом в этом таске (отложено в Task 4 / следующий цикл) — слишком много false positives без LLM-судьи. Поле в схеме оставляем, чтобы можно было создавать вручную.
6. **`cross_ref`** не генерим автоматом — тоже требует LLM-judge. В этом таске возможна только manual постановка.

**Idempotency:** перед `INSERT` для каждого `(client_id, type, subsection_id)` — проверка, что нет уже active (`status IN ('queued', 'in_progress', 'needs_review')`). Если есть — пропустить.

**Auto-close:** в `matrix.add_fact` — после успешной вставки факта со `flag='green'` найти active work-items с этим `client_id` + `subsection_id` + `type IN ('fill_gap', 'deepen', 'interview')` и:
- если `flag=green` факт — апдейт `work_item.status = 'needs_review'`, `related_fact_id = <new_fact_id>`. Аналитик апрувит вручную.
- если `flag=red` — статус не меняется автоматически (red ≠ закрытие gap'а).
- если `flag=grey` — статус не меняется (grey подтверждает наличие gap, а не закрытие).

### 3.3 Hooks

`synthesize_work_items` вызывать:

- На `import-seed` (Task 1) — после загрузки seed_facts.
- На `seed_accumulator` — для обратной совместимости.
- В конце `cycles.run_weekly` — рефреш backlog раз в неделю.
- По явной команде через API (см. ниже).

### 3.4 API

```python
@app.get("/api/clients/{client_id}/work-items")
def list_work_items(client_id, status: list[str] | None = None,
                    assignee: str | None = None, type: list[str] | None = None,
                    subsection_id: str | None = None): ...

@app.get("/api/work-items/{wid}")
def get_work_item(wid: int): ...

@app.post("/api/clients/{client_id}/work-items")
def create_work_item(client_id, body: WorkItemCreate): ...   # manual

@app.patch("/api/work-items/{wid}")
def update_work_item(wid, body: WorkItemUpdate): ...
# меняет: status, assignee, priority, due_date, notes, related_fact_id

@app.post("/api/clients/{client_id}/work-items:synthesize")
def synthesize(client_id, quarter: str | None = None): ...
# триггерит generator, возвращает {created: [ids], skipped: int}
```

Pydantic-модели — по образцу `FactCreate`/`FactUpdate`.

### 3.5 Frontend

Новая компонента `WorkView.tsx`. Добавить таб «Work» в `App.tsx` рядом с Punch-list.

Структура:

1. Сверху: счётчики и фильтры (status / type / assignee / track) — query params в URL.
2. Kanban с 4 колонками: **Queued** / **In progress** / **Needs review** / **Done (last 14d)**.
3. Карточка work-item:
   - тип-бейдж (`fill_gap`, `interview` etc.) с цветом по типу;
   - subsection link (`L2.1 Path to expertise →` jumps to cell в Matrix);
   - priority dot (красный = 1);
   - assignee initials или «Unassigned»;
   - age (`3d`, `2w`).
4. Клик по карточке → drawer:
   - Title, rationale, suggested_channel.
   - Кнопки: «Claim (assign me)», «In progress», «Mark needs review», «Done», «Block», «Cancel».
   - При «Done» — поле «Закрыто фактом id N» (выпадашка из последних фактов клиента в той же subsection).
   - Notes textarea.
5. Кнопка вверху «Synthesize» — POST `:synthesize`. Tooltip: «Сгенерирует work-items из punch-list и thin coverage».

Стиль — copy-paste из `PunchListView.tsx`, та же палитра.

### 3.6 Тесты

`tests/test_workitems.py`:

- На пустого клиента после `synthesize_work_items` → ровно 25 fill_gap (по числу subsections) + 0 deepen + 10 interview (только layers 1–3 + subsection в layer 1–3 ∩ empty).
- Повторный `synthesize` → 0 новых.
- После `add_fact(green, subsection 1.1)` → существующий `fill_gap` для 1.1 переходит в `needs_review` с `related_fact_id`.
- После `add_fact(red, subsection 1.1)` → статус не меняется.
- API smoke: `POST :synthesize` → 200, payload содержит `created` и `skipped`.
- Manual creation `POST /work-items` с `type=adjacent` → 200, item в БД.

### DoD Task 3

- Все тесты зелёные.
- На UI таб Work показывает реальные work-items для Accumulator после повторного `seed_accumulator` + `:synthesize`.
- Создание факта через CellDrawer закрывает соответствующий fill_gap в `needs_review` (видно глазом без рефреша страницы — react-query invalidate).
- README дополнен разделом «Daily workflow: work-items».

Коммит: `task-3: work-item layer — schema, generator, API, Kanban view`.

---

## Task 4 — Hand-off polish + регрессия

### 4.1 CLI для work-items

```bash
python -m ir_storyboard work-items list --client accumulator [--status queued]
python -m ir_storyboard work-items show <id>
python -m ir_storyboard work-items claim <id> --as Dmitry
python -m ir_storyboard work-items complete <id> --fact <fact_id> --notes "..."
python -m ir_storyboard work-items block <id> --reason "..."
python -m ir_storyboard work-items synthesize --client accumulator
```

### 4.2 Smoke-tests (e2e)

`tests/test_e2e_process.py` — один полный сценарий:

1. `add-client --from seeds/dummy.yaml` (3 seed_facts, 1 track).
2. Проверить: 1 client, 3 facts, 3 sources, 1 plan, 1 track.
3. `:synthesize` → ≥20 work-items.
4. Через API закрыть один `fill_gap` (создав факт в его subsection с flag=green) → status=needs_review.
5. PATCH work-item → status=done, completed_at != NULL.
6. `cycles/weekly` → рантайм не сломан, артефакт сохранился.

### 4.3 README + DEPLOY

- В `README.md` обновить секцию «Что осознанно НЕ сделано в v1» — убрать пункты которые теперь сделаны, добавить остаточные.
- Добавить разделы:
  - «Adding a new client» (с примером seeds/*.yaml)
  - «Daily workflow» (как аналитик использует Work-таб)
  - «Provenance rules» (что enforced, что нет)
- В `DEPLOY.md` — заметка про backup миграции (новые таблицы автоматически создаются на init_schema, дамп БД перед апдейтом — рекомендация).

### 4.4 Migration safety check

Скрипт `scripts/check_migration.sh`:

```bash
#!/bin/bash
# Берёт текущую staging БД, копирует, запускает init_schema, проверяет
# что все Accumulator-факты остались на месте.
```

Запускать руками перед релизом.

### DoD Task 4

- `pytest tests/test_e2e_process.py` зелёный.
- README и DEPLOY актуальны.
- На staging-сервере (если есть) старая БД с Accumulator + новые таблицы — 0 потерь.
- Финальный коммит: `task-4: e2e tests, CLI work-items, docs refresh`.

---

## Task 5 — Layer 1: выровнять до 3 подсекций (merge 1.3 + 1.4)

Цель: привести L1 в соответствие со всеми остальными слоями — три подсекции (`X.1`, `X.2`, `X.3`). Сейчас L1 — единственный outlier с четырьмя (1.1 Origin & Childhood · 1.2 Values & Beliefs · 1.3 Fears & Vulnerability · 1.4 Dreams & Identity). Заказчик попросил объединить 1.3 и 1.4 — внутреннее «я» фаундера (страхи + мечты + идентичность) как один буфер.

**Нейминг.** Слитая подсекция получает id `"1.3"` (старый 1.3 расширяет scope, `"1.4"` исчезает). Предлагаемое имя — `"Fears, Dreams & Identity"`, `code` — `FEARS_DREAMS_IDENTITY`. Если аналитик в уточняющем блоке предложит другую формулировку — заменить, но id `"1.4"` всё равно уходит.

### 5.1 Reference data
- В источнике истины subsections (`ir_storyboard/models.py` `LAYERS`/`SUBSECTIONS` и/или начальный INSERT в `schema.sql`/`seed.py`): удалить запись `"1.4"`, обновить `name`/`description`/`code` у `"1.3"` под объединённый смысл (страхи и уязвимость + мечты и идентичность как две стороны внутреннего «я»).
- Итог: ровно 24 строки `subsections` (8 × 3), не 25.

### 5.2 Миграция данных (в `init_schema`)

Идемпотентный шаг, защищённый проверкой существования старой подсекции. Порядок:

1. Если subsection `"1.4"` есть в БД:
   - Для каждого клиента, у которого есть клетка с `subsection_id = "1.4"` — найти или создать его клетку с `subsection_id = "1.3"`.
   - Перепривязать все `facts` с этой 1.4-клетки на 1.3-клетку.
   - Удалить осиротевшие 1.4-клетки.
   - Удалить запись subsection `"1.4"`.
2. `work_items` с `subsection_id = "1.4"`: status в (`queued`, `in_progress`, `needs_review`) — перевести на `"1.3"`; уже завершённые (`done`, `cancelled`) — оставить как есть (исторический след).
3. `narrative_tracks.target_subsection_ids` (JSON-массив): заменить `"1.4"` на `"1.3"`, дедуплицировать массив.

Всё в `ir_storyboard/db.py::init_schema`, после блока создания таблиц. На пустой БД миграция — no-op. На любой старой БД — отрабатывает один раз и потом тоже no-op (повторный вызов не должен ничего ломать).

### 5.3 Классификатор и keyword stub

- `ir_storyboard/llm.py::KEYWORDS_BY_SUBSECTION`: слить ключи `"1.3"` и `"1.4"` под `"1.3"` (объединить списки слов, дедуплицировать).
- Пробежать `git grep -n "1\.4"` и `git grep -n "Dreams"` / `"Identity"` по `ir_storyboard/`, `backend/`, `frontend/`, `seeds/`, `tests/` — везде, где подсекция 1.4 упомянута явно (промпты, шаблоны interview-questions, фикстуры, copy в UI) — обновить ссылки.

### 5.4 Frontend

- `frontend/src/components/MatrixGrid.tsx` и любой компонент, где число клеток L1 жёстко = 4 → теперь 3. Если сетка строится по `subsections` из API — изменений в коде быть не должно, только проверить визуально.
- Хардкод-метки `"1.4"` или `"Dreams & Identity"` в UI и e2e-тестах — удалить или заменить на новую 1.3.

### 5.5 Seeds

- `seeds/*.yaml` (Accumulator + любые другие): записи с `subsection_id: "1.4"` → `"1.3"`. Tracks с `"1.4"` в `target_subsection_ids` — `"1.3"` с дедупликацией. Описания (имя/scope) у новой 1.3 — синхронизировать с reference data.

### 5.6 Тесты

- Новый юнит-тест `tests/test_migration_layer1_collapse.py`: фикстура со старой схемой (1.4-клетка + 1 факт с источником + 1 open work-item на 1.4 + 1 narrative_track с `"1.4"` в target) → `init_schema` → ассерты: подсекция 1.4 удалена, факт под новой 1.3-клеткой, work-item на 1.3, track обновлён, повторный вызов `init_schema` идемпотентен (state не меняется).
- Регрессия: `pytest tests/` весь зелёный. Accumulator-сценарий weekly/event/quarterly не падает после миграции.

### DoD Task 5

- `SELECT count(*) FROM subsections` = 24, `WHERE id = '1.4'` = 0.
- На staging-БД с Accumulator: после миграции факты, ранее лежавшие в 1.4, видны в UI под 1.3, дополнительной клетки нет.
- `pytest` зелёный.
- `README.md` обновлён: «4 подсекции у L1» убрано; «25 ячеек» → «24 ячейки (8 × 3)».
- Финальный коммит: `task-5: layer 1 collapsed to 3 subsections (merge 1.3 + 1.4)`.

---

## Условия остановки и эскалации

- Если миграция `ALTER TABLE` падает на проде — НЕ форсить, откатить и сообщить.
- Если Wayback Save Page Now даёт >50% ошибок за час — переключиться на lookup-only, save отключить флагом `WAYBACK_SAVE_DISABLED=1`.
- Если генератор work-items начинает плодить >100 на одного клиента за прогон — это баг, остановиться.
- Любой merge в main без зелёного `pytest` — запрещён.

## Полезные команды (cheatsheet)

```bash
# создать клиента из seed
python -m ir_storyboard add-client --from seeds/stripe.yaml

# что висит на мне сегодня
python -m ir_storyboard work-items list --client stripe --assignee Dmitry --status queued,in_progress

# взять задачу
python -m ir_storyboard work-items claim 42 --as Dmitry

# закрыть задачу — система спросит, какой факт её закрыл
python -m ir_storyboard work-items complete 42 --fact 178 --notes "интервью 2026-05-14"

# освежить backlog после weekly
python -m ir_storyboard work-items synthesize --client stripe
```

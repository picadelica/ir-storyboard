# План работ для Claude Code — LLM Report Ingest

> **Аудитория этого документа — Claude Code**, запущенный в этой папке.
> Прочитай файл целиком, потом выполняй задачи строго по порядку
> (Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8).
> После каждой завершённой задачи — `git add . && git commit -m "<llm-N>: <subject>"`.
> Если задача неоднозначна — задай ОДИН уточняющий вопрос аналитику и подожди ответа.

---

## Контекст

`ir-storyboard` — внутренний инструмент IR-агентства (FastAPI + SQLite ядро
`ir_storyboard/` + React/TS фронт `frontend/`). Уже работает: 8-слойная матрица,
4 канала сбора (`online_research` / `online_interview` / `archival` /
`offline_interview`), 3 цикла (weekly / event / quarterly), 3 read-only вью
(punch-list / interview questions / scorecard), seed «Accumulator», Process
Layer (CLAUDE_TASKS.md — Tasks 1–5 закрыты).

Подробно — `README.md`. Перед стартом перечитай:
* `LLM_REPORT_INGEST_SPEC.md` — спецификация процесса (pipeline, маппинги,
  правила provenance, экран подтверждения, аудит). **Это твой контракт.**
* `LLM_REPORT_PROMPT_TEMPLATES.md` — промпты для эксперта, формат которых
  должен правильно парситься.
* `schema.sql`, `ir_storyboard/models.py`, `ir_storyboard/matrix.py`,
  `ir_storyboard/channels/base.py`, `ir_storyboard/channels/online_research.py`,
  `ir_storyboard/llm.py`, `backend/main.py`.
* `tests/fixtures/llm_report/gonka_chatgpt_deep_research.docx` — реальный
  вход (отчёт ChatGPT Deep Research по Gonka AI).
* `tests/fixtures/llm_report/libermans_gonka.expected.yaml` — golden output
  после прогона парсера (23 факта, 7 уникальных URL, 3 grey). **К нему мы
  стремимся** в Task 8.

## Зачем эта задача

Сегодня единственный путь наполнить матрицу нового клиента — это `import-seed`
с готовым YAML, который собирает аналитик руками. Это узкое место: эксперты
уже работают через LLM (ChatGPT Deep Research, Claude Research, Perplexity,
Gemini), и заставлять их повторно раскладывать факты в YAML — двойная работа.

Делаем **LLM Report Ingest** — новый способ загрузки: эксперт даёт нам
`.docx`/`.md`/`.pdf` файл от deep-research-агента, система сама извлекает
сноски, классифицирует каждый источник по канонам канала
(`archival`/`online_interview`/`online_research`), раскладывает атомарные
факты по подсекциям матрицы, открывает каждый URL и подтягивает дословную
цитату (`evidence_snippet` ≥ 20 chars), показывает эксперту preview, ждёт
confirm — и только тогда коммитит в БД через существующий `matrix.add_fact`.

LLM Report Ingest — это **способ ингеста**, не пятый канал. На запись в БД
источник получает один из четырёх существующих каналов. Слои L1–L3 он не
заполняет принципиально (методология).

**Принципы, которые нельзя нарушать:**

* **Provenance.** Каждый факт коммитится через `matrix.add_fact` с
  `source_id`, который ссылается на source-row с реальным `http(s)://` URL.
  `evidence_snippet` обязателен для не-grey фактов и должен быть ≥ 20 chars.
  Парафраз LLM может быть `evidence_snippet` на MVP, но в audit-логе фиксируется
  как `paraphrase=True`; SnippetResolver на v2 заменяет на дословную цитату.
* **Методологические каналы остаются 4.** Никаких новых `Channel` подклассов
  «llm_report». Используем существующие `OnlineResearchChannel` /
  `OnlineInterviewChannel` / `ArchivalChannel`. LLM Report Ingest —
  оркестратор, который строит `IngestPayload` с `pre_facts` и
  делегирует канонам.
* **Каналы L1–L3 из веб-источников запрещены.** Если FactExtractor предложил
  факт в L1/L2/L3 со ссылкой на web — он попадает в `skipped` с warning'ом,
  не в БД. Исключение: `archival` (press release / SEC) и `online_interview`
  могут заполнять L2/L3.
* **Идемпотентность.** Повторный ингест того же файла даёт `0 new sources,
  0 new facts` (по нормализованному URL и нормализованному тексту факта).
* **Без новых LLM-провайдеров.** Используем существующий
  `ir_storyboard/llm.py`. Если нужен расширенный промпт — расширяем там
  же, не плодим клиентов.
* **Frontend на react-query + Tailwind**, как в `PunchListView.tsx`. Без
  новых state-менеджеров и UI-китов.
* **Миграции схемы — идемпотентные `ALTER TABLE`** в `db.init_schema`
  (детектить колонку → добавлять). Никакого Alembic.

---

## Промпт для Claude Code (копировать в чат)

```
Прочитай CLAUDE_TASKS_llm_report_ingest.md в этой папке — это пошаговый план
встраивания LLM Report Ingest поверх существующего ir-storyboard (FastAPI +
SQLite + React).

Перед стартом перечитай:
  LLM_REPORT_INGEST_SPEC.md, LLM_REPORT_PROMPT_TEMPLATES.md, schema.sql,
  ir_storyboard/models.py, ir_storyboard/matrix.py,
  ir_storyboard/channels/base.py, ir_storyboard/channels/online_research.py,
  ir_storyboard/llm.py, backend/main.py.

Поведение:
- Выполняй Task 1 → 8 строго по порядку.
- После каждой завершённой задачи — git commit "llm-<N>: <subject>".
- DoD каждой задачи перечитывай перед стартом.
- Не ломай существующие эндпоинты, seed Accumulator, Process Layer тесты
  (tests/test_e2e_process.py, tests/test_provenance.py, tests/test_workitems.py,
  tests/test_add_client.py должны оставаться зелёными после каждой задачи).
- Никаких новых каналов. Никаких новых LLM-клиентов. Никакого Alembic.
- Frontend держи в стиле PunchListView.tsx.

Перед стартом задай ОДИН блок уточняющих вопросов:
- SnippetResolver: реализовать в MVP с реальным HTTP-fetch и
  поиском utterance в HTML или оставить заглушку (paraphrase + needs_review)
  и закрыть только на v2? (default: заглушка на MVP, реальный fetch — Task 4
  отдельной веткой)
- LLM-промпт для FactExtractor: расширить существующий llm.py или сделать
  отдельную функцию extract_facts_from_llm_report? (default: отдельная
  функция в llm.py, чтобы не ломать классификатор каналов)
- Архивирование исходного docx: класть в /artifacts на диск с client_id в
  пути или в БД blob? (default: на диск под data/llm_reports/<client_id>/,
  путь сохранять в audit-row)

После ответа стартуй с Task 1 и не останавливайся, пока не дойдёшь до Task 8
или не упрёшься в блокер. Используй TodoWrite для трекинга.
```

---

## Task 1 — Loaders: docx/md/pdf → canonical IR

Цель: универсальный «вход», который умеет читать три самых частых формата
LLM-экспортов и приводить их к одному внутреннему представлению.

### 1.1 Канонический IR

`ir_storyboard/channels/llm_report/ir.py`:

```python
@dataclass
class RawCitation:
    cite_id: int                  # 1..N как стоит у LLM
    raw_marker: str               # как было написано: '[1]', '(Source 1)', '¹' ...
    url: str                      # извлечённый или None если не нашли
    title: str = ""
    publisher: str = ""           # из URL host или подписи

@dataclass
class RawSection:
    heading: str                  # 'Обзор', 'Investments & Financing'
    level: int                    # 1 = H1, 2 = H2
    paragraphs: list[str]         # параграфы текста, со сносками внутри
    table_rows: list[list[str]] = field(default_factory=list)  # если в секции была таблица

@dataclass
class LLMReportIR:
    source_filename: str
    detected_agent: str | None    # 'chatgpt-deep-research' / 'claude' / 'perplexity' / 'gemini' / 'unknown'
    detected_cite_format: str     # 'bracket_n' / 'paren_source_n' / 'superscript' / 'unknown'
    sections: list[RawSection]
    citations: list[RawCitation]
    open_questions: list[str] = field(default_factory=list)
    parser_notes: list[str] = field(default_factory=list)
```

### 1.2 Loaders

`ir_storyboard/channels/llm_report/loaders/`:

* `docx_loader.py` — `python-docx`, обходит paragraphs + tables, ставит
  `level=1` для Heading 1 и `level=2` для Heading 2 (на нашем эталоне
  заголовки — Heading 1).
* `md_loader.py` — простой parser по `#`/`##`, fenced code не парсим как
  факты.
* `pdf_loader.py` — `pdfplumber` или `pypdf` для текстового слоя, без OCR
  (OCR — выносим в v2 отдельной задачей).

Каждый loader: `def load(path: Path) -> LLMReportIR`.

### 1.3 Тесты

`tests/test_llm_report_loader.py`:

* `test_docx_loader_on_gonka_fixture` — на нашем эталоне получаем
  ≥ 8 секций (Обзор, История..., Основатели..., Инвестиции..., Технология...,
  Планы..., Конкурентная..., Выводы), таблица хронологии не теряется,
  `citations` содержит 32 raw-сноски (как в исходном документе).
* `test_md_loader_basic_smoke` — крошечный md с двумя секциями и одной `[1]`
  сноской.

**DoD:** `pytest tests/test_llm_report_loader.py -q` зелёный. Никаких изменений
в существующих файлах вне `channels/llm_report/loaders/` и `ir.py`.

---

## Task 2 — CitationExtractor + Source classification

Цель: из `LLMReportIR.citations` достать чистый `[{cite_id, url, title,
publisher, channel}]` со скоррелированным каналом.

### 2.1 CitationExtractor (presets)

`ir_storyboard/channels/llm_report/citations.py`:

```python
def extract_citations(ir: LLMReportIR) -> list[ResolvedCitation]:
    ...
```

Логика:
1. По `ir.detected_cite_format` выбрать regex для inline-маркеров и для
   списка источников в конце.
2. Дедуплицировать URL: lower-case host, без trailing `/`, без UTM-параметров
   (`utm_*`, `fbclid`, `gclid`). Если разные `[N]` указывают на один URL —
   слить.
3. Распарсить publisher: для businesswire.com → `Businesswire`, для
   u.today → `U.Today`, для medium.com/@X → `Medium / X`, для прочего
   `urllib.parse.urlparse(url).hostname`.
4. Сохранить `RawCitation.raw_marker` для отладки.

`ResolvedCitation`:

```python
@dataclass
class ResolvedCitation:
    cite_id: int                  # из IR
    canonical_url: str
    title: str
    publisher: str
    channel: Literal["online_research","online_interview","archival","offline_interview"]
    classification_reason: str    # 'press_release domain', 'interview hostname', ...
```

### 2.2 SourceClassifier (URL → channel)

`ir_storyboard/channels/llm_report/classifiers/source_channel.py`:

Правила (в порядке убывания приоритета):

1. **archival** — `businesswire.com`, `prnewswire.com`, `globenewswire.com`,
   `sec.gov`, `*.gov`, `*.gc.ca`, `web.archive.org`, корпоративные
   `/press`/`/newsroom` пути.
2. **online_interview** — `youtube.com/watch`, `youtu.be`, `*.fm`,
   `*.podcast.*`, `vimeo.com`, `spotify.com/episode/*`, `u.today/interviews/`,
   `*/podcast/*`, путь содержит `interview` или `q-a` или `qanda`.
3. **online_research** — всё остальное web (новости, блоги, корпоративные
   страницы, статьи Medium вне `/podcast/`, Twitter/X threads,
   Binance Square / CoinRank-style reposts).
4. **offline_interview** — НИКОГДА не возникает из URL по построению;
   если функция вернула этот канал — это баг.

Каждое срабатывание правила пишет читаемую причину в
`classification_reason` (для debug-вывода и preview).

### 2.3 Тесты

`tests/test_llm_report_citations.py`:

* `test_extract_gonka_citations` — на нашем эталоне получаем 7 уникальных URL
  (после канонизации) и 8 publishers, классификация:
  * `businesswire.com/.../Bitfury-Announces` → `archival`
  * `u.today/interviews/...` → `online_interview`
  * `cryptobriefing.com/...`, `medium.com/@BitfuryGeorge/...`,
    `odaily.news/...`, `binance.com/en/square/...`,
    `libermans.co/press/forbes` → `online_research`
* `test_canonicalize_strips_utm` — `?utm_source=x&utm_campaign=y` уходит.
* `test_no_offline_from_url` — не возвращает `offline_interview` ни для
  какого URL.

**DoD:** все тесты зелёные. `extract_citations` детерминистичен (одинаковый
вход → одинаковый выход, без LLM-вызовов).

---

## Task 3 — FactExtractor (LLM, 2-й проход) + section→layer mapper

Цель: текст секций + сноски → атомарные `PreFact` с предложенным
`subsection_id`, `flag` и `cite_ids`. Используем существующий LLM-клиент.

### 3.1 Section → subsection_id mapper

`ir_storyboard/channels/llm_report/classifiers/section_to_layer.py`:

Канонический dict — синонимы для каждой стартовой подсекции. Старт (расширять
по мере столкновений с новыми отчётами):

```python
SECTION_HINTS: dict[str, list[str]] = {
    "2.1": ["history", "history & timeline", "история", "хронология",
            "path to expertise", "background", "журналистика", "карьерный путь"],
    "2.3": ["founders", "founder", "ownership", "основатели",
            "co-founders", "team", "команда"],
    "3.3": ["investments", "investors", "funding", "raise", "round",
            "инвесторы", "инвестиции", "финансирование"],
    "6.1": ["technology", "architecture", "архитектура", "технология",
            "consensus", "protocol", "what is", "обзор"],
    "6.2": ["philosophy", "tokenomics", "governance", "principles",
            "философия", "управление"],
    "6.3": ["roadmap", "plans", "future", "evolution", "планы",
            "дорожная карта"],
    "7.1": ["mission", "vision", "social impact", "миссия", "видение"],
    "7.2": ["risks", "criticism", "cost", "contradictions", "критика"],
    "8.1": ["historical moment", "macro", "context", "контекст"],
    "8.2": ["market", "competitive landscape", "competitors", "конкуренты",
            "конкурентная среда", "market & technology"],
    "8.3": ["regulation", "policy", "legal", "compliance",
            "регулирование", "политика", "policy & regulation"],
}
```

Функция `def suggest_subsection(heading: str) -> str | None`:
case-insensitive substring, возвращает первый match. Если не нашли — `None`,
факт уйдёт в `skipped` с пометкой «section heading unknown».

### 3.2 FactExtractor (LLM)

В `ir_storyboard/llm.py` добавить:

```python
def extract_facts_from_llm_report(
    section_heading: str,
    section_paragraphs: list[str],
    available_subsections: list[str],
    citation_index: dict[int, ResolvedCitation],
) -> list[ExtractedFact]:
    """Один LLM-вызов на секцию. Возвращает атомарные факты с предложенным
    subsection_id (из available_subsections), flag (green/red/grey) и cite_ids.
    """
```

`ExtractedFact`:

```python
@dataclass
class ExtractedFact:
    text: str
    subsection_id: str
    flag: str
    cite_ids: list[int]            # ссылки на ResolvedCitation
    confidence: float              # уверенность LLM 0..1
    raw_paraphrase: str            # дословное предложение из отчёта,
                                   # которое стало основой; для audit
```

Промпт LLM (system + user):

* system: «Ты — экстрактор фактов для нарративной IR-матрицы. На вход —
  одна секция отчёта. На выход — JSON-массив атомарных фактов. Каждый факт:
  одно предложение, ≤ 240 символов, связан с одной или несколькими `cite_ids`,
  имеет flag (green=позитивный/нейтральный, red=концерн, grey=явная нехватка
  данных). НЕ придумывай факты, которых нет в тексте. НЕ объединяй несколько
  утверждений в один факт.»
* user: имя секции + параграфы + список доступных `subsection_id` + reference
  на цитаты `{N: title}`.

### 3.3 Heuristics: flag green/red/grey

В `classifiers/flag_heuristics.py` — простая постобработка LLM-вывода:
* Если в тексте есть «не покрыт», «не известен», «not covered», «unknown»,
  «no information» — переписать `flag = grey`.
* Если есть «отозван», «провал», «убыток», «scandal», «lawsuit», «fraud»,
  «sanction», «losing», «down» — кандидат на `red` (LLM сам предлагает, но
  эвристика — safety net).
* Остальное — `green`.

LLM-результат + эвристика комбинируются: если расходятся в сторону «более
осторожно» (grey, red) — берём более осторожный.

### 3.4 Тесты

`tests/test_llm_report_extractor.py`:

* `test_section_to_layer_known` — заголовки из нашего эталона маппятся в
  ожидаемые подсекции.
* `test_section_to_layer_unknown_returns_none` — «Выводы» → `None`
  (мета-секции не парсим).
* `test_grey_heuristic_overrides_green` — на синтетическом тексте «in the
  report regulatory risks are not covered» → flag grey.
* `test_extract_facts_smoke` — мок LLM-клиента (классический паттерн из
  существующих тестов; не дёргать настоящий API), 3 параграфа на вход → 3
  ExtractedFact с разумными subsection_id.

**DoD:** `pytest tests/test_llm_report_extractor.py -q` зелёный. Никаких
реальных API-вызовов в тестах.

---

## Task 4 — SnippetResolver (MVP: заглушка, v2: реальный fetch)

Цель: подтянуть к каждому факту дословную цитату из источника ≥ 20 chars.

### 4.1 MVP — заглушка

`ir_storyboard/channels/llm_report/snippet_resolver.py`:

```python
def resolve_snippets(facts: list[ExtractedFact],
                     citation_index: dict[int, ResolvedCitation],
                     mode: Literal["paraphrase", "fetch"] = "paraphrase") -> list[ResolvedFact]:
    ...
```

В режиме `paraphrase` (MVP):
* `evidence_snippet = fact.raw_paraphrase[:400]` — берём предложение из отчёта.
* Если parafraz < 20 chars — `flag = grey`, `needs_review = True`.
* В audit: `snippet_source = "llm_paraphrase"`.

`ResolvedFact` добавляет к `ExtractedFact` поля: `evidence_snippet`,
`needs_review`, `snippet_source`.

### 4.2 v2 (отдельной веткой, не блокирует MVP) — реальный fetch

В режиме `fetch`:
* HTTP GET с user-agent и timeout=10s.
* HTML → текст через `trafilatura` или `readability-lxml` (выбрать что
  взлетит без headless-браузера).
* Найти предложение, наиболее похожее на `raw_paraphrase` (cosine на
  word-shingles ≥ 0.7). Вернуть как `evidence_snippet`, обрезать до 400 chars.
* Не нашли — упасть в paraphrase fallback + `flag=grey, needs_review=True`.
* Wayback fallback: если 4xx/5xx/timeout — `web.archive.org/web/2*/{url}`,
  если и оттуда не нашли — paraphrase + needs_review.
* Все fetch-операции — за feature-flag `LLM_REPORT_RESOLVE_FETCH=1` (default
  off, чтобы CI не зависел от сети).

### 4.3 Тесты

`tests/test_llm_report_snippet.py`:

* `test_paraphrase_mode_smoke` — на мок-фактах snippet берётся из paraphrase
  без сети.
* `test_short_paraphrase_marks_grey` — paraphrase из 10 chars → `flag=grey`,
  `needs_review=True`.
* `test_fetch_mode_offline` — fetch-режим со включённым feature-flag, но
  monkey-patched HTTP, который возвращает заранее заготовленный HTML;
  проверяем что нашли цитату.

**DoD:** MVP-режим работает без сети; v2-режим за флагом, тесты на моках
зелёные. Никаких реальных HTTP в pytest по умолчанию.

---

## Task 5 — Orchestrator + MatrixMerger (идемпотентный коммит)

Цель: связать всё в один pipeline и записать в БД, не плодя дубли.

### 5.1 Orchestrator

`ir_storyboard/channels/llm_report/pipeline.py`:

```python
@dataclass
class IngestPreview:
    audit_id: str                   # uuid, кладётся в БД на commit
    source_artifact_path: str
    detected_agent: str | None
    sources: list[ResolvedCitation]
    facts: list[ResolvedFact]
    notes: list[str]                # parser_notes + warnings
    stats: dict[str, int]           # facts_emitted, greys, channel_warnings, ...

def preview_llm_report(path: Path, client_id: str,
                       conn: sqlite3.Connection,
                       agent_hint: str | None = None) -> IngestPreview:
    """Прогон без записи в БД. Используется бэкендом для экрана подтверждения."""

def commit_llm_report(preview: IngestPreview, client_id: str,
                      conn: sqlite3.Connection,
                      expert_email: str) -> CommitResult:
    """Записывает sources + facts через matrix.add_source / matrix.add_fact.
    Идемпотентность по канонизированному URL и нормализованному тексту факта."""
```

### 5.2 Идемпотентность

* `_normalize_url(url)` — то же, что в Task 2.2: lower host, без trailing `/`,
  без utm.
* `_normalize_fact(text)` — lower, strip, схлопнуть пробелы, выкинуть числа
  в круглых скобках (для capacity 6 000 → 10 000 → 12 000+ это не «новые
  факты», а обновления — пометить в audit `superseded_by`).
* Перед `add_source`: SELECT по нормализованному URL; если есть — переиспользуем
  `source_id`.
* Перед `add_fact`: SELECT по `(client_id, subsection_id, normalized_text)`;
  если matched — update вместо insert (set `superseded_at = NULL`, новый
  `valid_until` если задан).

### 5.3 Audit-таблица

В `schema.sql` (через `db.init_schema` ALTER TABLE):

```sql
CREATE TABLE IF NOT EXISTS ingest_audit (
  id              TEXT PRIMARY KEY,         -- uuid
  client_id       TEXT NOT NULL,
  ingest_kind     TEXT NOT NULL CHECK(ingest_kind IN ('llm_report', 'manual_seed')),
  source_artifact TEXT NOT NULL,
  agent           TEXT,
  cite_format     TEXT,
  parsed_at       TIMESTAMP NOT NULL,
  facts_emitted   INTEGER NOT NULL,
  facts_committed INTEGER NOT NULL,
  greys_emitted   INTEGER NOT NULL,
  channel_warnings INTEGER NOT NULL,
  expert_email    TEXT NOT NULL,
  confirmed_at    TIMESTAMP NOT NULL,
  preview_json    TEXT NOT NULL              -- IngestPreview сериализованный
);
```

### 5.4 Тесты

`tests/test_llm_report_pipeline.py`:

* `test_preview_then_commit_gonka` — на нашем фикстуре получаем
  `IngestPreview` с `len(sources)==7`, `len(facts)==23`, `greys==3`,
  `channel_warnings==3`. Коммит создаёт 7 рядов в `sources`, 23 в `facts`,
  1 в `ingest_audit`.
* `test_double_commit_is_idempotent` — повторный `commit_llm_report` тем же
  preview-ом не плодит дубли (delta 0).
* `test_capacity_supersede` — два preview с фактами «6000 H100» и
  «10000 H100» по subsection_id `6.3` → второй помечает первый как
  superseded.

**DoD:** все тесты зелёные. `tests/test_provenance.py` и существующие e2e
тесты остаются зелёными — методология не сломана.

---

## Task 6 — Backend endpoint

Цель: дать фронту три эндпоинта — preview, commit, history.

### 6.1 Эндпоинты

В `backend/main.py`:

```
POST   /api/clients/{client_id}/ingest/llm-report/preview
       multipart/form-data: file=<docx|md|pdf>, agent_hint=<str|None>
       → IngestPreviewOut (без audit_id; preview lives in memory, отдаётся клиенту)

POST   /api/clients/{client_id}/ingest/llm-report/commit
       json: { preview: IngestPreviewOut, edits: [...] , expert_email }
       → { audit_id, committed_facts, committed_sources, ingested_at }

GET    /api/clients/{client_id}/ingest/llm-report/history
       → list[IngestAuditOut]   (последние N с пагинацией)
```

`IngestPreviewOut` — pydantic-аналог `IngestPreview`, серилизованный.
`edits` — массив правок от эксперта: `[{fact_idx, action: 'drop'|'edit'|'keep',
new_text, new_subsection_id, new_flag}]`.

Архивирование исходного файла: на диск в `data/llm_reports/<client_id>/
<audit_id>.<ext>`. Путь сохраняется в `ingest_audit.source_artifact`.

### 6.2 Тесты

`tests/test_llm_report_api.py`:

* `test_preview_endpoint_docx` — `POST .../preview` с фикстурой возвращает
  ≥ 7 sources и ≥ 23 facts.
* `test_commit_with_edits` — preview → commit с drop одного факта → в БД 22
  факта, не 23.
* `test_history_endpoint` — после commit `GET .../history` отдаёт 1 row.

**DoD:** все тесты зелёные. FastAPI Swagger (`/api/docs`) показывает новые
эндпоинты с заполненными `summary` / `description`.

---

## Task 7 — Frontend: экран подтверждения

Цель: эксперт открывает клиента → «Ingest LLM report» → upload → preview →
правит → confirm.

### 7.1 Маршрут и компоненты

* Новый таб «Ingest» в `Sidebar.tsx` — рядом с Punch-list / Interview /
  Scorecard / Work. Видимость: если у клиента ещё нет фактов — выделить
  цветом.
* `frontend/src/components/IngestLLMReport.tsx` — двухэкранный flow:
  1. **Upload**: drag-n-drop / file input, optional `agent_hint` (radio:
     ChatGPT / Claude / Perplexity / Gemini / unknown). Кнопка «Анализировать».
  2. **Preview**: список sources с channel и кол-вом фактов; список facts
     сгруппированных по слою; на каждом — `[keep] [edit] [drop]`. Серые
     ячейки помечены `chip="gap"`.
* Кнопка «Сохранить в матрицу» внизу — disabled, пока эксперт не подтвердил
  ≥ 1 факт (нельзя коммитить пустой preview).
* После commit — toast «Сохранено N фактов, M источников. История: …» и
  редирект в Punch-list, который теперь показывает обновлённые ячейки.

### 7.2 Стиль

Tailwind + react-query, как `PunchListView.tsx`. Цвета каналов:
* `archival` — синий
* `online_interview` — фиолетовый
* `online_research` — серо-голубой
* `offline_interview` — никогда не появится; если появилось — красный
  badge «BUG: offline from URL».

### 7.3 Тесты

`frontend/src/components/__tests__/IngestLLMReport.test.tsx` (если есть
test-runner; если нет — `tests/manual_ingest_smoke.md` с пошаговым QA).

* Загрузка docx → preview не пустой
* Edit факта → отображение обновляется
* Commit без подтверждений → кнопка disabled

**DoD:** руками открыть → загрузить `tests/fixtures/llm_report/
gonka_chatgpt_deep_research.docx` → увидеть preview → нажать commit → увидеть
факты в Punch-list. Скриншот в PR.

---

## Task 8 — e2e: Gonka.docx → libermans-gonka client (golden fixture diff)

Цель: автотест, который прогоняет реальный фикстур-docx через весь pipeline
и сверяет результат с `libermans_gonka.expected.yaml`.

### 8.1 Тест

`tests/test_llm_report_e2e.py`:

```python
def test_e2e_gonka_matches_expected_yaml(tmp_path, monkeypatch):
    # 1) спин-ап чистой БД
    # 2) upsert_client('libermans-gonka', ...)
    # 3) preview_llm_report(fixtures/llm_report/gonka_chatgpt_deep_research.docx)
    # 4) commit_llm_report(preview, expert_email='ci@example.com')
    # 5) выгрузить state клиента через matrix.* в dict
    # 6) загрузить libermans_gonka.expected.yaml
    # 7) сверить:
    #    - sources: множество canonicalized URL == ожидаемое
    #    - facts: количество ≥ 20, ≤ 25 (LLM может варьировать на 1-2)
    #    - greys: 2 ≤ count ≤ 4
    #    - в каждой ожидаемой subsection есть хотя бы один fact
    #    - channel_warnings: 2 ≤ count ≤ 5
    #    - ни один factов не попал в L1.1/1.2/1.3/2.1-2.3 через online_research,
    #      кроме явно разрешённых в expected (с warning'ом)
```

Толерантность: LLM-вывод варьируется. Тест проверяет **инварианты**, не
дословное совпадение. Жёсткие проверки — на детерминистические части:
канал-классификация URL, маппинг секций, идемпотентность.

### 8.2 Golden-diff (опционально)

Скрипт `scripts/diff_with_golden.py`, который при `--update` обновляет
`libermans_gonka.expected.yaml` под новый pipeline (для случаев, когда мы
сознательно поменяли поведение). По умолчанию `--check` — падает, если
расхождение выше порога.

### 8.3 CI

Добавить новый job в `.github/workflows/ci.yml` (или эквивалент, если есть
другой CI):

```
- name: LLM Report Ingest e2e
  env:
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}   # для FactExtractor
  run: pytest tests/test_llm_report_e2e.py -q
```

Если в репо ещё нет CI, его поднимать не надо — задача только в локальном
прогоне.

**DoD:** `pytest tests/test_llm_report_e2e.py -q` зелёный локально с
переменной `ANTHROPIC_API_KEY`. Без ключа — `pytest.skip` с понятным
сообщением.

---

## Хронология коммитов (ориентир)

```
llm-1: loaders + LLMReportIR
llm-2: citation extractor + source classifier
llm-3: fact extractor + section→layer mapper + flag heuristics
llm-4: snippet resolver (paraphrase MVP)
llm-4b: snippet resolver (fetch v2, за feature-flag)   ← опционально
llm-5: pipeline + matrix merger + ingest_audit table
llm-6: backend endpoints (preview / commit / history)
llm-7: frontend IngestLLMReport component
llm-8: e2e test + golden YAML diff
```

## Что НЕ делаем в этой задаче

* Не добавляем новый канал `llm_report` в `ALL_CHANNELS`.
* Не делаем OCR для отсканированных PDF (v3).
* Не делаем второй LLM-аудитор для верификации сносок — это отдельный
  будущий шаг (см. `LLM_REPORT_PROMPT_TEMPLATES.md` §5).
* Не делаем «авто-listing» новых клиентов из отчёта. Клиент должен быть
  создан заранее через `POST /api/clients/{id}/import-seed` или хотя бы
  `POST /api/clients`. Ingest наполняет существующего клиента, не создаёт.
* Не пишем интерпретации («Conclusions»). Если LLM-отчёт содержит секцию
  «Выводы» — `section_to_layer` возвращает `None`, факты игнорируются.

---

## Проверка перед PR

* `pytest -q` — все тесты зелёные (старые + 7 новых файлов).
* `python -m ir_storyboard.cli scorecard libermans-gonka` после прогона e2e
  показывает заполненные слои 4-8 и серые ячейки в 5.3 / 4.3 / 8.3.
* `python -m ir_storyboard.cli interview-questions libermans-gonka` отдаёт
  вопросы для L1-L3 (всё ещё пустые) — это правильный знак, что pipeline не
  залез в зону интервью.
* Frontend: `npm run build` без ошибок; вкладка Ingest рендерится.
* `LLM_REPORT_INGEST_SPEC.md` — в нём ничего не правим: spec был контрактом,
  он не должен меняться от реализации. Если по ходу разработки спека
  оказалась нереалистичной — выноси правки в отдельный коммит «spec:
  reflect MVP scope», чтобы они были видны в review.

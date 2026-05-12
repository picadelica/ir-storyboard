# LLM Report Ingest — спецификация нового канала ir-storyboard

> Базовый сценарий для эксперта: «нашёл в интернете → попросил большую LLM
> свернуть в отчёт со ссылками → залил в ir-storyboard → система сама
> разложила по матрице». Первый эталонный прогон — `seeds/libermans_gonka.yaml`,
> собранный из `Доработка openClaw.docx` (ChatGPT Deep Research по Gonka AI).

## 1. Зачем нужен этот канал

Эксперты уже работают так: гуглят, скармливают сводку в ChatGPT/Claude/Gemini/
Perplexity Deep Research, читают результат. Если ir-storyboard умеет принять
этот готовый артефакт напрямую и разложить его в матрицу — мы убираем последнюю
ручную операцию (перенос фактов) и при этом сохраняем привязку к
первоисточникам, что критично для green/red/grey-провенанса.

LLM-отчёт — это не «волшебная истина». Это **онлайн-канал с одной особенностью**:
вместо того, чтобы агент тянул и парсил отдельные статьи, эксперт принёс уже
свёрнутый набор статей с готовыми сносками. Дальше работают те же
методологические ограничения, что и для других каналов:

* `online_research` — может питать слои **4, 5, 6, 7, 8**
* `online_interview` — слои **1, 2, 3, 4, 7** (если LLM цитирует подкаст/интервью)
* `archival` — слои **2–8** (если LLM цитирует SEC filing / press release / книгу)
* `offline_interview` — НИКОГДА не появится из LLM-отчёта по построению
* **слои 1–3 не наполняются** из чисто веб-источников; LLM-отчёт оставляет их
  пустыми (или серыми), а аналитик закрывает их интервью с фаундером

## 2. Входной артефакт

Принимаемые форматы:

* `.docx` — экспортируется из ChatGPT Deep Research, Claude, Gemini, Perplexity
* `.md` или `.txt` — если эксперт скопировал ответ из чата руками
* `.pdf` — если отчёт сгенерирован как документ (Perplexity Pages, NotebookLM)

Каждый поддерживаемый агент кладёт сноски по-своему. Парсер должен распознать:

| Агент | Формат цитаты | Где живут URL-ы |
|---|---|---|
| ChatGPT Deep Research / Agent | `[1]`, `[2]` ... в тексте | блок ссылок в конце документа («Sources» / нумерованный список) |
| Claude Research | `(Source 1)` или footnote-маркеры | блок sources в конце |
| Perplexity / Perplexity Pages | надстрочные `¹` или `[1]` | inline-блок citations над абзацем |
| Gemini Deep Research | `[link]` inline + footnotes | sources panel сбоку, при экспорте — список ссылок в конце |

Пресет под каждый агент — отдельный модуль (см. §6).

## 3. Pipeline

```
docx/md/pdf
   │
   ▼
[1] DocumentLoader            ──► plain text + structural map
                                   (sections, headings, footnotes, tables)
   │
   ▼
[2] CitationExtractor         ──► [{cite_id: 1, url, title, publisher}, ...]
                                   (определяет формат сносок, дедуплицирует URL)
   │
   ▼
[3] SourceClassifier          ──► channel per source
                                   • businesswire / sec.gov / company press-room → archival
                                   • youtube.com / podcast hosts / *.fm → online_interview
                                   • *.com / blog.* / forum                → online_research
   │
   ▼
[4] FactExtractor (LLM, 2nd pass)
                              ──► [{text, subsection_id, flag, cite_ids[]},
                                   ...]
                                   • разрезает по секциям отчёта,
                                   • маппит секции → слои матрицы,
                                   • эвристики green/red/grey по тону
   │
   ▼
[5] SnippetResolver           ──► для каждого факта открывает source_url,
                                   находит ≥20-char буквальную цитату,
                                   подтверждающую факт; если не нашёл —
                                   flag понижается, либо grey + needs_review
   │
   ▼
[6] MatrixMerger              ──► идемпотентное наложение на существующие
                                   facts/sources в БД клиента
   │
   ▼
[7] ExpertConfirm UI          ──► экран «вот что система разобрала» с
                                   keep/edit/drop по каждому факту
   │
   ▼
[8] Commit + AuditLog
```

## 4. Маппинг секций отчёта → подсекции матрицы

Парсер не «угадывает», а опирается на список синонимов. Для ChatGPT Deep
Research-формата (как в `Доработка openClaw.docx`) стартовая таблица:

| Заголовок секции в отчёте | Целевые subsection_id |
|---|---|
| Обзор / Overview | 6.1, 6.2 (архитектура и философия продукта) |
| История и хронология | 2.1, 6.3 (path to expertise + evolution of the product) |
| Основатели / Founders | 2.3 (co-founder dynamics) |
| Инвестиции / Investments | 3.3 (investors & partners), 8.1 (historical moment) |
| Технология / Technology | 6.1 (architecture of the solution) |
| Планы / Roadmap | 6.3 (evolution of the product) |
| Конкурентная среда / Competitive landscape | 8.2 (market & technology) |
| Социальный/политический контекст | 7.1, 8.3 |
| Выводы / Conclusions | НЕ ингестим как факты — это интерпретация LLM |

«Выводы» и любые мета-разделы парсер должен явно отбрасывать — иначе в матрицу
попадут не факты, а пересказы фактов, и это испортит сорсинг.

## 5. Правила provenance в LLM-канале

Из `ir_storyboard/matrix.py:validate_provenance`:

* для `online_research` / `online_interview` / `archival`: `source_url`
  обязателен и должен начинаться на `http(s)://`, `evidence_snippet` — ≥20 chars
* для `offline_interview`: обязателен `source_title` (не возникает из LLM-канала)
* `flag = grey` снимает требование к snippet — это специально для «известных
  пробелов»

Дополнительные правила LLM Report Ingest:

* **dereference URL обязателен**. Парсер открывает каждый цитируемый URL и
  ищет утверждение, на которое LLM ссылался. Если utterance в URL не найдена,
  factу ставится `flag=grey` и `needs_review=true`.
* **парафраз vs цитата**. На первом проходе `evidence_snippet` — это
  пересказ LLM. На втором (SnippetResolver) — заменяется на дословную фразу из
  URL. Аудит-лог хранит оба варианта.
* **archive.org fallback**. Если URL мёртв, парсер пробует Wayback
  (`web.archive.org/web/*/<url>`) и сохраняет в `sources.archive_url`.
* **дата валидности**. Для динамических данных (capacity, ARR, число хостов)
  ставится `valid_until` — иначе через 2 месяца факт превращается в
  устаревшую «истину».

## 6. Архитектура парсеров (модули)

В стиле текущих channels/ (online_research.py, archival.py, ...):

```
ir_storyboard/channels/llm_report/
    __init__.py
    base.py                ← общий FactExtractor + SnippetResolver
    loaders/
        docx_loader.py
        md_loader.py
        pdf_loader.py
    presets/
        chatgpt_deep_research.py
        claude_research.py
        perplexity.py
        gemini_deep_research.py
    classifiers/
        source_channel.py  ← URL → channel
        section_to_layer.py← заголовок → subsection_id
        flag_heuristics.py ← тон фразы → green/red/grey
```

LLM Report Ingest НЕ регистрируется как пятый канал в `ALL_CHANNELS`. Это
**оркестратор поверх существующих каналов**: pipeline парсит документ,
классифицирует каждый источник по URL, и для каждой группы источников строит
`IngestPayload` с `pre_facts`, который скармливается соответствующему
существующему `Channel` (`OnlineResearchChannel` / `OnlineInterviewChannel` /
`ArchivalChannel`). На запись в БД факт получает один из четырёх канонических
каналов — никакой «llm_report» в `sources.channel` появиться не должен.

## 7. Экран подтверждения (UX)

После прогона парсера эксперт видит превью:

```
LLM Report Ingest preview · Libermans (Gonka AI) · 2026-05-12

Sources (8 unique):
  ✓ businesswire.com/.../Bitfury-Announces-$50M    archival       [1 fact uses]
  ✓ u.today/interviews/...                          online_interview [2 facts use]
  ✓ cryptobriefing.com/gonka-decentralized-ai...    online_research  [4 facts]
  ✓ medium.com/@BitfuryGeorge/...                   online_research  [3 facts]
  ⚠ binance.com/en/square/post/32276709244242       online_research  [2 facts]  ← dynamic page, snippet weak
  ✓ libermans.co/press/forbes                       online_research  [2 facts]
  ✓ odaily.news/en/post/5207968                     online_research  [2 facts]
  ✓ productscience.ai                               online_research  [0 facts]   ← cited but no usable claim
                              [open URL]  [verify]  [edit channel]  [drop]

Facts (22 emitted · 3 grey · 0 red):
  [L2.1] green   "Братья Либерман выстроили путь из distributed-computing..."
                 src: u.today/interviews/... · snippet: "Their experience includes..."
                                              [keep]  [edit]  [drop]
  [L8.3] grey    "Регуляторные риски DePIN/AI ... в отчёте не покрыты"
                 [keep as gap]  [edit]  [drop]
  ...

[ ] Подтверждаю импорт      [ ] Отметить серые ячейки в interview-questions
```

Экран — `frontend/src/components/IngestPreview.tsx`. После confirm — `POST
/api/clients/{id}/ingest/llm-report/commit`.

## 8. Идемпотентность и слияние

* Сорсы матчатся по `source_url` (canonicalized: lower-case host, без
  trailing slash, без UTM-параметров). Дубль не создаётся; вместо этого к
  существующему source добавляется fact.
* Факты матчатся по триплету `(client_id, subsection_id, normalized_text)`,
  где `normalized_text` — lowercased + stripped + без чисел в скобках. Если
  совпадение ≥0.85 cosine — это update, а не insert.
* На update: старая версия факта остаётся в `facts_history` (новая таблица,
  Task 16 в дорожной карте), новая получает `superseded_at = NULL`,
  `prev_fact_id`.

## 9. Аудит-журнал

Каждый прогон LLM Report Ingest пишет строку в `ingest_audit`:

```sql
CREATE TABLE ingest_audit (
    id              INTEGER PRIMARY KEY,
    client_id       TEXT NOT NULL,
    ingest_kind     TEXT NOT NULL,        -- 'llm_report'
    source_artifact TEXT NOT NULL,        -- filename
    agent           TEXT NOT NULL,        -- 'chatgpt-deep-research' и т.д.
    prompt_hash     TEXT,                 -- если эксперт приложил промпт
    cite_format     TEXT,
    parsed_at       TIMESTAMP NOT NULL,
    facts_emitted   INT,
    facts_committed INT,
    greys_emitted   INT,
    expert_email    TEXT NOT NULL,
    confirmed_at    TIMESTAMP
);
```

Это даёт сквозную traceability: если через год факт из 2026-05-12 окажется
неверным, мы видим, что он пришёл из ChatGPT Deep Research, из конкретного
файла, через конкретный URL, и подтверждён конкретным экспертом.

## 10. Что НЕ делает этот канал

* Не закрывает слои 1–3 — для этого нужен offline_interview / online_interview
  с самой персоной, не LLM-сводка
* Не заменяет EventWatcher: LLM-отчёт — это срез на момент компиляции, а не
  поток
* Не «верифицирует» факты — он их **импортирует с пометкой источника**.
  Проверка достоверности — отдельный шаг (Tavily + cross-source consensus)
* Не пишет интерпретации («Выводы», «Что это значит») в матрицу — только
  атомарные факты с источником

## 11. Roadmap внедрения

1. **MVP** — DocxLoader + ChatGPT preset + ручная разметка subsection_id
   экспертом на экране подтверждения. Без второго прохода по URL.
   `seeds/libermans_gonka.yaml` — эталонный output этого этапа.
2. **v1** — автоматический section→layer mapping + flag-эвристики
3. **v2** — SnippetResolver открывает URL и заменяет парафраз цитатой
4. **v3** — пресеты под Claude / Perplexity / Gemini
5. **v4** — pdf-loader (Perplexity Pages, NotebookLM-экспорт)
6. **v5** — diff-вид «второй LLM-отчёт по тому же клиенту» с conflict highlight

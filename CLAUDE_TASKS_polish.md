# План работ для Claude Code — Polish (карточки + клиент)

> **Аудитория этого документа — Claude Code**, запущенный в этой папке.
> Прочитай файл целиком, потом выполняй задачи строго по порядку
> (Task 1 → 2 → 3 → 4 → 5 → 6).
> После каждой завершённой задачи — `git add . && git commit -m "polish-<N>: <subject>"`.
> Если задача неоднозначна — задай ОДИН уточняющий вопрос аналитику и подожди ответа.

---

## Контекст

`ir-storyboard` к моменту запуска этой серии имеет полностью работающие 3 ingest pipeline'а (Research / LLM Report / YouTube), 8-слойную матрицу, 3 цикла, Methodology layer, Plan tab. Накопились системные хвосты по карточкам:

* источник на карточке факта визуально не считывается (10px шрифт, скрытие `internal://` URL'ов)
* для red флага нет AI-объяснения «почему это проблема»
* клиента нельзя редактировать после создания
* подписи «GREEN/RED/GREY» дублируют цветовую индикацию
* `clients.created_at` не отображается

Подробно — `POLISH_SPEC.md`. **Это твой контракт.** Перед стартом перечитай:

* `POLISH_SPEC.md` — спецификация (10 разделов)
* `CLAUDE.md`, `NEXT.md` — текущая архитектура и состояние
* `schema.sql` — точки миграций (полная схема)
* `ir_storyboard/models.py`, `ir_storyboard/matrix.py` — `validate_provenance`, `add_fact`, `facts_for_cell`
* `backend/main.py` строки 59-110 — `ClientOut`, `FactCreate`, `FactUpdate`, `IngestConfirmIn`
* `backend/main.py` строки 471-485 — существующий `upsert_client`, рядом будет PATCH
* `backend/main.py` строки 1067-1094 — `research_ingest_confirm` (точка, где надо принимать rationale)
* `frontend/src/components/CellDrawer.tsx` — основная карточка факта (строки 112-182 — render fact card; 271-279 — `FlagBadge`)
* `frontend/src/components/Sidebar.tsx` строки 16-149 — `NewClientDrawer`, будем параметризовать
* `frontend/src/components/IngestYouTube.tsx` — preview-карточки (искать `▶ timeStr` ~строка 967, `effectiveFlag` ~945)
* `frontend/src/components/IngestLLMReport.tsx`, `frontend/src/components/ResearchView.tsx` — аналогичные preview-карточки
* `frontend/src/types.ts` — типы `Fact`, `Client`

## Зачем эта серия

Закрыть набор «по мелочам, но раздражает» в карточках. После этой серии:
* Эксперт смотрит на карточку и сразу видит источник (URL или LLM report download)
* На красном флаге — короткое объяснение AI, что именно проблема
* Карточку клиента можно редактировать (все поля бэка)
* Дублирующие текстовые подписи убраны
* Заложен `created_by` под мульти-пользователя

**Принципы:**

* **Не ломать ingest pipeline'ы.** Только промпты extractor'ов расширяем, формат IR/Transcript не меняем.
* **Не ломать цветовую модель `MatrixGrid`.** Полировка только на уровне карточек.
* **Schema-миграции идемпотентные `ALTER TABLE` в `db.init_schema`.** Без Alembic.
* **Existing red facts с пустым rationale** не валидим как ошибку — UI показывает `(не указано)`. Эксперт может дописать через PATCH.
* **id клиента read-only** в edit-режиме — slug связан FK во всех таблицах.
* **Никаких новых стейт-менеджеров.** React-query, как везде.

---

## Промпт для Claude Code (копировать в чат)

```
Прочитай CLAUDE_TASKS_polish.md в этой папке — это пошаговый план
полировки карточек и клиента в ir-storyboard.

Перед стартом перечитай:
  POLISH_SPEC.md, CLAUDE.md, NEXT.md, schema.sql,
  ir_storyboard/models.py, ir_storyboard/matrix.py, backend/main.py,
  frontend/src/components/CellDrawer.tsx,
  frontend/src/components/Sidebar.tsx,
  frontend/src/components/IngestYouTube.tsx,
  frontend/src/components/IngestLLMReport.tsx,
  frontend/src/components/ResearchView.tsx,
  frontend/src/types.ts.

Поведение:
- Выполняй Task 1 → 6 строго по порядку.
- После каждой завершённой задачи — git commit "polish-<N>: <subject>".
- DoD каждой задачи перечитывай перед стартом.
- Не ломай существующие тесты — все pytest должны оставаться зелёными
  после каждой задачи.
- Не трогай ingest pipeline'ы (loaders, chunkers, transcribers,
  classifiers, snippet_anchor, layer_guard) — только промпты extractor'ов.
- Не меняй MatrixGrid (цветовая модель ячеек), только карточки.
- Frontend — react-query + Tailwind, без новых стейт-менеджеров.

Зафиксированные решения (не открывать заново):
- existing red facts с пустым rationale остаются как есть; UI показывает
  '(не указано)'. Валидация ругается только на новые.
- id клиента read-only в edit-режиме.
- created_by пока NULL — заготовка под мульти-пользователя.
- Шрифт source-блока на карточке: 12px минимум.

Перед стартом задай ОДИН уточняющий вопрос:
- Backfill rationale: реально хочется migration-скрипт, который
  пройдётся по существующим red фактам и попросит LLM сгенерировать
  rationale задним числом? (default: НЕ делать; existing red остаются
  с пустым rationale, эксперт допишет через UI при необходимости)

После ответа стартуй с Task 1 и не останавливайся, пока не дойдёшь до
Task 6 или не упрёшься в блокер. Используй TodoWrite для трекинга.

После Task 6 — обнови NEXT.md (HEAD, что сделано, открытые вопросы).
```

---

## Task 1 — Schema migrations + Pydantic models

Цель: добавить `rationale` к facts, `created_by` к facts и clients, выставить `created_at` клиента в API. Без логики, без UI.

### 1.1 Миграции

В `ir_storyboard/db.py`, в `init_schema` после существующих `ALTER TABLE` LLM Report Ingest миграций:

```python
# Polish migrations
if "rationale" not in _cols(conn, "facts"):
    conn.execute("ALTER TABLE facts ADD COLUMN rationale TEXT DEFAULT ''")
if "created_by" not in _cols(conn, "facts"):
    conn.execute("ALTER TABLE facts ADD COLUMN created_by TEXT")
if "created_by" not in _cols(conn, "clients"):
    conn.execute("ALTER TABLE clients ADD COLUMN created_by TEXT")
```

`_cols(conn, table)` — существующая хелпер-функция (см. как делаются предыдущие миграции). Если нет — добавить через `PRAGMA table_info`.

### 1.2 Pydantic-модели в `backend/main.py`

`ClientOut` — добавить поля:

```python
class ClientOut(BaseModel):
    # ... существующие поля ...
    created_at: Optional[str] = None
    created_by: Optional[str] = None
```

`FactOut` — добавить:

```python
class FactOut(BaseModel):
    # ... существующие поля ...
    rationale: str = ""
    created_by: Optional[str] = None
```

`FactCreate`, `FactUpdate` — добавить `rationale: Optional[str] = None`.

В `IngestConfirmIn` каждого ingest endpoint'а (research, llm-report, youtube) — расширить fact-payload: `rationale: Optional[str] = None`.

`_row_to_client`, `_row_to_fact` — отдавать новые поля. Для `created_at` — `row["created_at"]` уже в БД, просто пробросить (SQLite вернёт строку формата `YYYY-MM-DD HH:MM:SS`, оставить как есть).

### 1.3 Тесты

`tests/test_polish_schema.py`:

* `test_facts_has_rationale_column` — через `PRAGMA table_info` подтверждаем
* `test_facts_has_created_by_column`
* `test_clients_has_created_by_column`
* `test_client_out_includes_created_at` — создаём клиента, дёргаем GET `/api/clients/{id}`, ожидаем непустой `created_at`
* `test_idempotent_re_init` — `init_schema` вызывается дважды, второй вызов не падает

**DoD:** все тесты зелёные. `pytest tests/ -q` — все существующие тесты тоже зелёные (миграция не ломает старые таблицы).

**Коммит:** `polish-1: schema migrations (rationale, created_by) + ClientOut.created_at`

---

## Task 2 — Extractor prompts + validation

Цель: научить три extractor'а возвращать `rationale` для red, добавить серверную валидацию.

### 2.1 Промпт-расширение

Файлы (точные пути проверь через grep `_EXTRACT_SYSTEM` или `EXTRACT_PROMPT`):

* `ir_storyboard/ingest/extractor.py` (бывший `channels/llm_report/extractor.py` после рефактора)
* `ir_storyboard/ingest/youtube_extractor.py` (или одного extractor'а — посмотри как сделано)
* `ir_storyboard/llm.py` — если там есть Research-specific extractor

Во все промпты добавить блок:

```
RATIONALE field rules:
- If flag is "red": you MUST provide a rationale (1-2 sentences) explaining
  what specifically is the concern. Be concrete, not generic.
  GOOD: "Founder hasn't disclosed Series B valuation, while peers like X
        and Y did. This raises a transparency concern for institutional
        investors."
  BAD:  "This is bad."
- If flag is "grey": rationale is RECOMMENDED (1-2 sentences explaining
  what specifically we don't know and why it matters). Optional.
- If flag is "green": leave rationale empty (do not emit the field, or
  emit empty string).
```

JSON output schema каждого extractor'а пополняется полем `rationale: str` (default empty).

### 2.2 Серверная валидация

В `ir_storyboard/matrix.py::validate_provenance` (или отдельно — `validate_rationale`):

```python
def validate_rationale(flag: str, rationale: str) -> str:
    """Returns possibly-normalized rationale, raises ValueError if invalid."""
    rationale = (rationale or '').strip()
    if flag == 'red' and not rationale:
        raise ValueError("red fact requires rationale explaining the concern")
    if flag == 'green' and rationale:
        return ''   # silently drop — green doesn't carry rationale
    return rationale
```

`matrix.add_fact(...)` принимает `rationale` параметр (default `""`), валидирует через `validate_rationale`, пишет в БД.

`matrix.update_fact(...)` — если приходит `rationale` и приходит `flag`, валидирует пару. Если только `rationale` — валидирует против текущего `flag` в БД.

### 2.3 API endpoints

* `POST /api/clients/{id}/cells/{sid}/facts` — `f.rationale` пробрасывается в `add_fact`. На `red` без rationale — 422.
* `PATCH /api/facts/{id}` — `u.rationale` пробрасывается в `update_fact`.
* `research_ingest_confirm`, `llm_report_commit`, `youtube_commit` — пробрасывают `rationale` из payload в `add_fact`. Существующие red factы из preview (где extractor его сгенерировал) попадают в БД с rationale. Если preview каким-то путём не сгенерировал — 422 на commit.

### 2.4 Тесты

`tests/test_polish_rationale.py`:

* `test_validate_rationale_red_requires_text`
* `test_validate_rationale_grey_optional`
* `test_validate_rationale_green_silently_drops`
* `test_add_fact_red_without_rationale_422` — через FastAPI test client, POST с `flag=red`, `rationale=""` → ожидаем 422
* `test_add_fact_red_with_rationale_succeeds` → 201
* `test_patch_fact_rationale_update` → PATCH меняет rationale, отдаёт в response
* `test_existing_red_with_empty_rationale_returns_empty_string` — старые facts с rationale=NULL/'' в БД GETятся нормально, не 500
* `test_extractor_prompt_includes_rationale_block` — assert на содержание промпта

**DoD:** все тесты зелёные. Существующие тесты ingest pipeline'ов остаются зелёными.

**Коммит:** `polish-2: rationale field — extractor prompts + validation + API`

---

## Task 3 — Edit client API + ClientPatch model

Цель: новый эндпоинт `PATCH /api/clients/{id}` для частичного обновления полей клиента.

### 3.1 Pydantic-модель

В `backend/main.py`:

```python
class ClientPatch(BaseModel):
    name: Optional[str] = None
    sector: Optional[str] = None
    one_liner: Optional[str] = None
    founder_name: Optional[str] = None
    founder_handle: Optional[str] = None
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None
    tone_preset: Optional[str] = None
    # id, created_at, created_by — НЕ редактируемые
```

### 3.2 Endpoint

```python
@app.patch("/api/clients/{client_id}", response_model=ClientOut)
def patch_client(client_id: str, u: ClientPatch, conn=Depends(get_conn)):
    if matrix.get_client(conn, client_id) is None:
        raise HTTPException(404, "client not found")
    
    sets, params = [], []
    for field, value in u.dict(exclude_unset=True).items():
        if field == 'aliases':
            sets.append("aliases=?"); params.append(json.dumps(value or []))
        else:
            sets.append(f"{field}=?"); params.append(value)
    
    if not sets:
        return _row_to_client(matrix.get_client_row(conn, client_id))
    
    params.append(client_id)
    conn.execute(f"UPDATE clients SET {','.join(sets)} WHERE id=?", params)
    conn.commit()
    return _row_to_client(matrix.get_client_row(conn, client_id))
```

`exclude_unset=True` — критично, обновляются только реально пришедшие поля. `None` остаётся `None`.

### 3.3 Тесты

`tests/test_polish_client_patch.py`:

* `test_patch_client_updates_one_field`
* `test_patch_client_unset_fields_untouched`
* `test_patch_client_aliases_serialized_correctly` — list пишется как JSON, обратно читается как list
* `test_patch_client_404_on_missing`
* `test_patch_client_id_field_ignored` — даже если в body есть `id`, оно игнорируется (используется path)
* `test_patch_then_get_returns_updated`

**DoD:** все тесты зелёные. Существующий `POST /api/clients` (upsert) остаётся работать.

**Коммит:** `polish-3: PATCH /api/clients/{id} + ClientPatch model`

---

## Task 4 — SourceLine component + новый рендер источника

Цель: универсальный `<SourceLine>` — единственная точка визуализации провенанса на карточках во всех 4 вью.

### 4.1 Компонент

Новый файл `frontend/src/components/SourceLine.tsx`:

```tsx
interface SourceLineProps {
  channel?: Channel;
  source_url?: string;
  source_title?: string;
  source_publisher?: string;
  source_archive_url?: string;
  ingest_audit_id?: string;
  client_id: string;   // нужен для построения URL к /ingest/llm-report/{audit}/file
  captured_at?: string;
  timestamp_sec?: number;  // если YouTube
}

export default function SourceLine(props: SourceLineProps) {
  const { source_url, ingest_audit_id, client_id, channel, ... } = props;
  
  const kind =
    source_url?.startsWith("http") ? "web" :
    source_url?.startsWith("internal://") && ingest_audit_id ? "llm_report" :
    !source_url && channel === "offline_interview" && props.source_title ? "offline" :
    "none";
  
  // Render branches по kind, см. POLISH_SPEC.md §3
}
```

Поведение по веткам:

* **web**: `<ChannelBadge> <displayTitle> ↗ <wayback?>` + при `timestamp_sec` добавляется `▶ MM:SS` (deep-link с `&t={sec}s`)
* **llm_report**: `<ChannelBadge> LLM Report #{audit_id} <DownloadLink href="/api/clients/{client_id}/ingest/llm-report/{audit_id}/file">↓</DownloadLink>`
* **offline**: `<ChannelBadge> {source_title} · 🎙 offline`
* **none**: `<span text-amber>⚠ no source</span>`

Шрифт — 12px (`text-xs` Tailwind). Не 10px (`text-[10px]`).

Captured_at — справа той же строки, `text-ink-mute`.

### 4.2 Применение

* `CellDrawer.tsx` строки 154-178 — заменить inline-блок на `<SourceLine ... />`
* `IngestYouTube.tsx` — там сейчас рендерится только `▶ timeStr` без channel/title. Заменить на полный `<SourceLine>`. При наличии `meta.title` показываем title видео, не просто timestamp.
* `IngestLLMReport.tsx` — аналогично заменить блок source на `<SourceLine>`
* `ResearchView.tsx` — preview-карточки на `<SourceLine>`

### 4.3 Тесты

UI-тестов в проекте нет, но в `tests/test_polish_source_line.py` — backend smoke: создать факт с каждым из 4 типов provenance (http, internal://, offline only, none), GET через API, проверить что `_row_to_fact` отдаёт все нужные поля. Это backend regression, не UI.

Ручной smoke: запустить dev (`npm run dev` в frontend), открыть все 4 вью, проверить визуально.

**DoD:** SourceLine рендерится во всех 4 вью без `console.error`. Все типы provenance отображаются без скрытия. Шрифт ≥ 12px. Backend smoke зелёный.

**Коммит:** `polish-4: SourceLine component + replace 10px source rows in 4 card views`

---

## Task 5 — Edit Client drawer (frontend)

Цель: после создания клиента можно открыть тот же drawer в edit-режиме и поменять любое поле кроме id.

### 5.1 Параметризация NewClientDrawer

В `frontend/src/components/Sidebar.tsx`:

* Переименовать `NewClientDrawer` → `ClientDrawer`
* Добавить пропсы: `mode: "create" | "edit"`, `initial?: ClientOut`
* В edit-режиме:
  - `id` поле — `disabled` + tooltip «slug нельзя менять»
  - Все остальные поля предзаполняются из `initial`
  - YAML-режим скрыт (он только для создания)
  - Кнопка `Save` вызывает `api.patchClient(initial.id, payload)` вместо `upsertClient`
  - Сверху drawer'а — info-блок:
    ```
    Created: 2026-05-12
    Created by: —
    ```
  - `onSuccess` инвалидирует queries `["clients"]` и закрывает

### 5.2 Pencil в Sidebar

В списке клиентов:

```tsx
<li key={c.id} className="group flex items-center">
  <Link to={...} className="flex-1 ...">
    <span>{c.name}</span>
    <span className="text-[10px] ...">{c.sector?.split("/")[0]}</span>
  </Link>
  <button
    onClick={(e) => { e.preventDefault(); setEditingClient(c); }}
    className="opacity-0 group-hover:opacity-100 transition px-1.5 text-ink-mute hover:text-ink"
    title="Edit"
  >✎</button>
</li>
```

State `editingClient: ClientOut | null` рядом с `showNewClient`. При непустом — рендерим `<ClientDrawer mode="edit" initial={editingClient} ... />`.

### 5.3 API client

В `frontend/src/api.ts`:

```ts
patchClient: (id: string, patch: Partial<Omit<Client, 'id' | 'created_at' | 'created_by'>>) =>
  fetch(`/api/clients/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  }).then(r => r.json()),
```

`Client` в `types.ts` — добавить `created_at?: string`, `created_by?: string`.

### 5.4 Тесты

UI-тестов нет — ручной smoke:
1. Создать клиента
2. Открыть pencil → edit drawer открывается с предзаполненными значениями
3. Изменить `notes`, save → drawer закрывается, sidebar обновляется
4. Reopen edit → видим новое значение
5. Попробовать вписать в `id` — input заблокирован

**DoD:** smoke проходит. Backend test `test_patch_client_*` (polish-3) остаётся зелёным. Frontend type-check проходит (`npm run build` без TS-ошибок).

**Коммит:** `polish-5: Edit client drawer + pencil in sidebar`

---

## Task 6 — Visual cleanup карточек

Цель: убрать GREEN/RED/GREY текстовые подписи везде, отобразить rationale для red, заменить FlagBadge на FlagDot.

### 6.1 Новый компонент FlagDot

`frontend/src/components/FlagDot.tsx`:

```tsx
export default function FlagDot({ flag, size = 8 }: { flag: Flag; size?: number }) {
  const color = flag === 'green' ? 'bg-flag-green' :
                flag === 'red'   ? 'bg-flag-red' :
                                   'bg-flag-grey';
  return (
    <span 
      className={`inline-block rounded-full ${color}`}
      style={{ width: size, height: size }}
      aria-label={flag}
    />
  );
}
```

`aria-label` сохраняет доступность (screen readers).

### 6.2 Замены

* `CellDrawer.tsx` — заменить `<FlagBadge flag={f.flag} />` на `<FlagDot flag={f.flag} />` (ставится в начало строки с текстом факта). Удалить определение `FlagBadge` (или оставить только для редактирования). 
* `IngestYouTube.tsx` строка ~945 — там сейчас `{effectiveFlag}` в bordered span. Заменить на `<FlagDot flag={effectiveFlag} />`. Подпись текстом убрать.
* `IngestLLMReport.tsx` — найти аналогичную конструкцию, заменить.
* `ResearchView.tsx` — найти аналогичную конструкцию, заменить.

Подпись цветом ячейки в `MatrixGrid.tsx` НЕ трогать — это другая визуализация.

`FlagPicker` (`<select>` для редактирования) — оставить как есть. Это форма ввода, там текст уместен.

### 6.3 Rationale display

В `CellDrawer.tsx` после `<div>{f.text}</div>`:

```tsx
{f.rationale && f.flag !== 'green' && (
  <div className={`mt-2 text-xs border-l-2 pl-2 leading-snug ${
    f.flag === 'red' ? 'border-flag-red/60 text-flag-red-deep' : 'border-flag-grey/60 text-ink-mute'
  }`}>
    <span className="font-medium uppercase tracking-wide text-[10px] mr-1">
      {f.flag === 'red' ? 'concern' : 'gap'}:
    </span>
    {f.rationale}
  </div>
)}
{!f.rationale && f.flag === 'red' && (
  <div className="mt-2 text-xs text-amber-600 italic">
    ⚠ Concern: (не указано) — обновите факт через edit
  </div>
)}
```

Аналогичный rationale-блок добавить в три preview-вью (IngestYouTube, IngestLLMReport, ResearchView). В edit-форме фактов на preview — поле rationale обязательно для red.

### 6.4 Edit fact form (CellDrawer)

В существующей edit-форме CellDrawer (строки 115-131) — добавить textarea для rationale:

```tsx
<textarea
  placeholder={draftFlag === 'red' ? 'Concern: что именно проблема (обязательно)' : 'Rationale (опц.)'}
  value={draftRationale}
  onChange={e => setDraftRationale(e.target.value)}
  className={`w-full text-xs border rounded px-2 py-1.5 min-h-[3rem] ${
    draftFlag === 'red' && !draftRationale.trim() ? 'border-red-400' : 'border-ink-line'
  }`}
/>
```

Disable Save если `draftFlag === 'red' && !draftRationale.trim()`.

### 6.5 Тесты

* `tests/test_polish_visual_smoke.py` — ничего нет, frontend ручной smoke
* Ручной smoke:
  1. Открыть CellDrawer на ячейке с фактами разных флагов — текст GREEN/RED/GREY нет нигде, цветной dot есть
  2. Открыть red факт — видно rationale в красном блоке
  3. Открыть red факт без rationale — видно warning «(не указано)»
  4. Открыть YouTube preview с любым видео — на карточках нет «green/red/grey» текста
  5. Edit red факт без rationale → Save заблокирован
  6. Edit red факт с rationale → Save проходит

**DoD:** smoke проходит. `npm run build` без TS-ошибок. Все backend pytest зелёные.

**Коммит:** `polish-6: drop GREEN/RED/GREY labels + show rationale in card views`

---

## После Task 6 — обновить NEXT.md

```
1. Прочитать существующий NEXT.md
2. Перезаписать «Что в фокусе» — Polish closed (polish-1..6), линки на коммиты
3. Open questions: backfill rationale для legacy red фактов (если эксперты попросят)
4. Следующие шаги — пусто или то, что было до polish серии
5. git commit -m "chore: update NEXT.md after polish series"
```

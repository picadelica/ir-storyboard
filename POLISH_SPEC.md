# Polish — спецификация системных правок карточек и клиента

> Закрываем 5 «системных хвостов» накопившихся к 2026-05-24:
> провенанс на карточке не очевиден, для красных флагов нет AI-объяснения,
> клиента нельзя редактировать, текстовые подписи флагов избыточны,
> дата создания клиента не отображается. Никакой новой логики ingest'а
> или матрицы — это качественный полировочный слой.

## 1. Контекст

`ir-storyboard` к этому моменту имеет 4 канала ingest'а, 3 цикла, 8-слойную матрицу, и три тяжёлых pipeline'а извлечения фактов (Research / LLM Report / YouTube). По коду все они корректно сохраняют провенанс через `matrix.add_source` + `matrix.add_fact(source_id=...)`. Однако:

* Карточки в `CellDrawer.tsx` показывают источник 10px шрифтом справа внизу — визуально его «нет».
* Часть фактов сохраняется с `source_url='internal://<audit_id>/<idx>'` (когда LLM Report Ingest не извлёк HTTP URL у цитаты). Эти URL'ы намеренно скрываются фронтом, и для пользователя карточка выглядит как «факт без источника», хотя реальный источник (LLM-отчёт) скачивается по микроскопической ссылке «report».
* `flag` рендерится дважды: цветной фон карточки + текст «GREEN/RED/GREY» в badge. Дублирование.
* Поле `rationale` в `facts` отсутствует. LLM ставит `red`, но не объясняет почему — эксперту нужно вычитывать факт целиком и догадываться.
* Клиент создаётся через `NewClientDrawer`, после создания — `<Link>` без edit-режима. Поля бэкенда (`one_liner`, `notes`, `aliases`, `tone_preset`) можно изменить только через API руками.
* `clients.created_at` уже есть в схеме (`DEFAULT CURRENT_TIMESTAMP`), но не отдаётся в `ClientOut` и не показывается в UI.

## 2. Что меняется

Один связанный набор правок, чтобы карточка факта и карточка клиента выглядели «закончено» и говорили эксперту то, что нужно с одного взгляда.

| Что | Где | Тип изменения |
|---|---|---|
| Source-блок на карточке факта | CellDrawer + 3 preview-вью | UI (новый компонент) |
| AI-rationale для `red` | extractor + schema + API + UI | Полный сквозной слой |
| Edit-режим клиента | Sidebar + новый Drawer | UI + расширение API |
| Убрать подписи «GREEN/RED/GREY» | Все 4 вью с карточками | UI (cleanup) |
| `created_at` клиента в UI | ClientOut + Edit Drawer | API + UI |
| Заготовка `created_by` | schema + ClientOut + FactOut | Schema migration (без UI) |

## 3. Source-блок на карточке (универсальный компонент)

Заводим `<SourceLine>` в `frontend/src/components/SourceLine.tsx`. Используется одинаково в `CellDrawer`, `IngestYouTube`, `IngestLLMReport`, `ResearchView`.

Контракт пропсов:

```ts
interface SourceLineProps {
  channel: Channel;
  source_url?: string;              // canonical URL or internal://
  source_title?: string;
  source_publisher?: string;        // optional, из sources.publisher
  source_archive_url?: string;
  ingest_audit_id?: string;
  captured_at?: string;             // ISO; рендерим как 'YYYY-MM-DD'
  // youtube-specific
  timestamp_sec?: number;           // если есть — рисуем ▶ MM:SS как часть URL
}
```

Поведение по приоритету визуализации:

* **`source_url` начинается с `http(s)://`** — отрисовывается полная строка:
  > `<ChannelBadge> <source_title или host(source_url)> · <a href=source_url>↗</a> [📦 wayback?] [▶ MM:SS если youtube]`
  Шрифт 12px (не 10), на отдельной строке внутри карточки. Это первый класс провенанса.
* **`source_url` начинается с `internal://`** и есть `ingest_audit_id`:
  > `<ChannelBadge> LLM Report #<audit_id> · <a href=/api/.../{audit_id}/file>↓ скачать отчёт</a>`
  Шрифт 12px, отдельная строка. Это второй класс провенанса. Без скрытия.
* **Нет ни того, ни другого** (offline_interview без URL, source_title есть):
  > `<ChannelBadge> <source_title> · 🎙 offline`
  Тоже отдельная строка.
* **Ничего нет вообще** (легаси факт без provenance):
  > `<span text-amber>⚠ no source</span>`
  Желто-предупреждающим — это явная аномалия, эксперт должен видеть.

`captured_at` идёт справа от source-блока в той же строке, серым.

Никаких 10px шрифтов в провенансе. Минимум 12px, максимум 14.

## 4. AI rationale для красных флагов

### 4.1 Хранение

Миграция в `db.init_schema` (идемпотентный `ALTER TABLE`):

```sql
ALTER TABLE facts ADD COLUMN rationale TEXT DEFAULT '';
```

`rationale` — 1-2 предложения, заполняется при `flag='red'`, опционально для `flag='grey'`, должно быть пусто для `flag='green'`. Хранится как plain text, не markdown (рендерим без форматирования).

### 4.2 Извлечение

Промпты всех трёх extractor'ов (Research, LLM Report, YouTube) расширяются:

```
If the fact has flag=red, you MUST provide a `rationale` field:
1-2 sentences explaining what specifically is the concern. Be concrete.
Не "это плохо", а "X сделал Y, что противоречит Z и создаёт риск W".

If the fact has flag=grey, rationale is recommended (explain what
specifically we don't know and why it matters), but optional.

For flag=green, do NOT emit rationale — leave it empty.
```

### 4.3 Валидация

В `matrix.add_fact` / `matrix.validate_provenance` — добавить:

```python
if flag == 'red' and not rationale.strip():
    raise ValueError("red fact requires rationale explaining the concern")
if flag == 'green' and rationale.strip():
    # warning, не error — обнуляем тихо
    rationale = ''
```

API `POST /api/clients/{id}/cells/{sid}/facts` и `PATCH /api/facts/{id}` принимают `rationale`. `FactOut` отдаёт `rationale`.

### 4.4 Отображение

В карточке факта, под `text`:

```
[RED ●]   <fact.text>
          ⚠ Concern: <fact.rationale>     ← новый блок, красная левая граница
          <source-line>
          <captured_at>                    
```

Для `grey` — аналогично, серая граница, префикс «Gap:». Для `green` — ничего.

Включая `CellDrawer`, `IngestYouTube`-preview, `IngestLLMReport`-preview, `ResearchView`-preview. На preview-экранах эксперт может редактировать `rationale` так же, как `text` / `subsection` / `flag`.

## 5. Edit client (полное редактирование)

### 5.1 UI

`NewClientDrawer` в `Sidebar.tsx` параметризуется:
* `mode: "create" | "edit"`
* `clientId?: string` (для edit)
* `initial?: ClientOut` (предзагрузка)

В edit-режиме:
* Поле `id` read-only (slug нельзя менять — он связан с FK во всех таблицах)
* `name`, `sector`, `one_liner`, `founder_name`, `founder_handle`, `aliases` (comma-separated input), `notes` (textarea), `tone_preset` (select из existing presets) — редактируемые
* Сверху drawer'а — блок-инфо: `Created: 2026-05-12` и `Created by: —` (placeholder для будущего)
* Кнопка `Save` → `PATCH /api/clients/{id}` (см. §5.2)
* `Cancel` закрывает без изменений

В Sidebar рядом с каждым клиентом — мелкая кнопка «✎» (pencil), открывает Edit-drawer. На hover карточки клиента она проявляется, иначе скрыта, чтобы не загромождать.

### 5.2 API

Новый эндпоинт:

```python
@app.patch("/api/clients/{client_id}", response_model=ClientOut)
def patch_client(client_id: str, u: ClientPatch, conn=Depends(get_conn)):
    """Partial update. Никаких изменений id."""
```

`ClientPatch` — Pydantic model с всеми полями `ClientOut` кроме `id`, все Optional. None означает «не менять».

Существующий `POST /api/clients` (upsert) НЕ удаляется — он используется при создании. Edit идёт через PATCH.

`ClientOut` пополняется:

```python
class ClientOut(BaseModel):
    id: str
    name: str
    sector: Optional[str] = None
    one_liner: Optional[str] = None
    founder_name: Optional[str] = None
    founder_handle: Optional[str] = None
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None
    tone_preset: Optional[str] = None
    created_at: Optional[str] = None     # ISO, был в схеме, не отдавался
    created_by: Optional[str] = None     # NULL пока нет пользователей
```

### 5.3 Заготовка `created_by`

Миграция:

```sql
ALTER TABLE clients ADD COLUMN created_by TEXT;
ALTER TABLE facts ADD COLUMN created_by TEXT;
```

NULL по умолчанию. На UI пока показывается как «—». При наличии — `<created_by> · <created_at>`. Это задел под мульти-пользователя, делаем заранее, чтобы не было обратно-несовместимой миграции потом.

## 6. Убрать подписи «GREEN/RED/GREY»

Подписи живут в:
* `CellDrawer.tsx` → компонент `FlagBadge` (строки 271-279)
* `IngestYouTube.tsx` (строка ~945, текст `effectiveFlag` внутри bordered span)
* `IngestLLMReport.tsx` — проверить, скорее всего та же конструкция
* `ResearchView.tsx` — проверить

Решение: заменить badge на цветную точку 8×8px в начале строки текста факта. Никаких надписей.

```tsx
<FlagDot flag={f.flag} />   // <span className="inline-block w-2 h-2 rounded-full ${color}" />
```

Цветной фон/border всей карточки (`flagBg` / `flagBorder` в CellDrawer) — **остаётся**, потому что это и есть основной визуальный сигнал. Убираем только дублирующий текстовый бэйдж.

`FlagPicker` (для edit-режима) — остаётся как `<select>`, там текст уместен. Это форма ввода, не дисплей.

## 7. Schema migrations

Все идемпотентные `ALTER TABLE` в `db.init_schema`:

```sql
-- Polish migrations
ALTER TABLE facts ADD COLUMN rationale TEXT DEFAULT '';
ALTER TABLE facts ADD COLUMN created_by TEXT;
ALTER TABLE clients ADD COLUMN created_by TEXT;
```

Детект колонки → добавление. Без Alembic.

## 8. API контракт (изменения)

### Новые поля

* `FactOut.rationale: str` (default `""`)
* `FactOut.created_by: Optional[str]`
* `ClientOut.created_at: Optional[str]`
* `ClientOut.created_by: Optional[str]`

### Новые эндпоинты

* `PATCH /api/clients/{client_id}` — partial update, см. §5.2

### Расширения существующих

* `POST /api/clients/{id}/cells/{sid}/facts` принимает `rationale`
* `PATCH /api/facts/{id}` принимает `rationale`
* `POST /api/clients/{id}/ingest/confirm` (research) принимает `rationale` в каждом fact
* `POST /api/clients/{id}/ingest/llm-report/commit` — аналогично
* `POST /api/clients/{id}/ingest/youtube/commit` — аналогично

### Валидация

* `red` без `rationale` → 422
* `green` с `rationale` — server обнуляет тихо

## 9. Что НЕ делает этот PR

* Не меняет ingest pipeline'ы — только промпты extractor'ов
* Не вводит мульти-пользователя — только заготовку колонки
* Не меняет цветовую модель ячеек матрицы (`MatrixGrid.tsx`) — только карточки
* Не меняет схему source (sources.publisher уже было, sources.url остаётся)
* Не делает миграцию старых red-фактов с пустым rationale — оставляем пустыми, эксперт допишет вручную через PATCH при необходимости

## 10. Open questions

* **Backfill rationale для existing red фактов.** В БД сейчас могут быть red-факты без rationale. Валидация `add_fact` начнёт ругаться только на новые. Решено: existing — не трогаем (rationale = ''), на UI показываем как `⚠ Concern: (не указано)`. Эксперт может дописать через CellDrawer edit.
* **Должен ли LLM emit rationale для grey?** В §4.2 заложено как recommended/optional. Если эксперты говорят «мешает» — выключим heuristic'ом. Решение — после первого прогона.
* **Format rationale.** Plain text без markdown. Если потом захочется ссылок или bold — расширим.

# NEXT — где мы остановились

> Снимок оперативного состояния. Обновлять в конце каждой сессии (overwrite,
> не append). Цель — за 30 секунд понять, где находимся.
>
> Стабильная архитектура и инварианты — в `CLAUDE.md`. Сюда — только
> «здесь и сейчас».

---

**Последнее обновление:** 2026-05-22
**Ветка:** `feat/v2`
**Working tree:** clean (untracked: `12.jpeg` — не относится к проекту)
**HEAD:** `fix: surface silent LLM chunk failures + skipped fact timestamps`

## Что в фокусе

**Диагноз "preview пропускает первые 2 часа" — closed.** На одном и том же
кэшированном транскрипте (`HdDNw-VxCvA`) три прогона выдали 20 / 28 / 7 фактов.
Причина: `_generate_real` молча возвращал `""` при любой Anthropic-ошибке
(overloaded / rate-limit / network), а `extract_facts_from_transcript:697`
`if raw:` тихо проглатывал пустой chunk. Plus `skipped` сериализация теряла
timestamp/quote → в UI skipped-карточки выглядели без таймкода.

Один коммит закрывает оба бага:

* **`ir_storyboard/llm.py`** — retry 3× (backoff 2/5/10s) на `anthropic.APIError`
  в `_generate_real`, logger.warning/error на attempt-ах.
  `extract_facts_from_transcript` → `(facts, chunk_errors)`. Каждый
  `empty_llm_response` / `invalid_json` записывается с `chunk_start_min`,
  `chunk_end_min`, `reason`, `detail`.
* **`youtube_pipeline.py`** — `stats.chunks_total/chunks_failed`,
  `preview_json.chunk_errors`, по строке на каждый failed chunk в `notes`.
  `skipped` сериализация выровнена с `facts` (text_ru/text_en/quote/
  snippet_start_sec/snippet_end_sec/flag/confidence).
* **`backend/main.py:YouTubeSkippedOut`** — те же поля.
* **`frontend/IngestYouTube.tsx`** — оранжевый баннер "X of Y chunks failed —
  re-run preview, transcript is cached". `SkippedCard` теперь рендерит
  RU/EN/quote/timestamp ровно как `FactCard`.

**YouTube Ingest** — основная серия (`youtube-1..8` + ~10 пост-фиксов)
закрыта.

**LLM Report Ingest** — закрыт.

## Открытые вопросы (что ещё пользователь просил по YouTube)

- **#2 edit-before-drop в preview** — сейчас только `drop`/`restore`. Нужно
  inline-редактирование `text_ru`/`text_en`/`subsection_id`/`flag` перед
  коммитом. Не сделано.
- **#4 history tab в UI** — endpoint `/api/clients/{id}/ingest/youtube/history`
  есть (`youtube-6`), но фронт-таба, который его показывает списком прошлых
  preview-ов, нет. Не сделано.
- **chunks_failed на ранних chunks** — даже с retry Haiku-4.5 может быть
  занят. Решение пока: оранжевый баннер + re-run (бесплатно из кэша).
  Если будет упорно падать — попробовать поднять `LLM_GENERATE_MODEL` до
  Sonnet через env var.
- **Embedding-dedup / speaker diarization / параллелизация chunks** — v2.

## Следующие разумные шаги (если пользователь скажет «продолжаем»)

1. Доделать **#2 edit-before-drop** — inline-edit на FactCard перед commit.
2. Доделать **#4 history tab** — отдельный экран со списком past previews
   (id / video / parsed_at / facts_emitted / committed) + кнопка "open".
3. **Skipped facts: режим override+edit** — после override разрешить
   менять subsection_id (если LayerGuard ругался на запрещённый layer,
   аналитик может перебросить факт в L4/L7 и принять).

## Как обновлять этот файл

В конце сессии, когда что-то значимое сделано:

```
1. Обновить "Последнее обновление" — сегодняшняя дата.
2. Обновить "HEAD" — `git log -1 --oneline`.
3. Перезаписать раздел "Что в фокусе" — что только что закрыли.
4. Если открыты вопросы — в "Открытые вопросы".
5. Скорректировать "Следующий разумный шаг".
6. git add NEXT.md && git commit -m "chore: update NEXT.md"
```

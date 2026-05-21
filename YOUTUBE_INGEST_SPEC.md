# YouTube Ingest — спецификация ингеста подкастов/интервью в ir-storyboard

> Базовый сценарий: «вот YouTube-ссылка на интервью с фаундером — разложи в матрицу с дословными цитатами и привязкой ко времени».
>
> Это не новый канал. Это **новый loader поверх существующего `online_interview`**: видео скачивается, прогоняется через Whisper, факты извлекаются той же LLM-механикой, что и у LLM Report Ingest, source row пишется в `online_interview` детерминистично (без URL-классификатора).

## 1. Зачем

В матрице L1–L4 и L7 (и в особенности L1–L3) методологически закрываются интервью с самой персоной. Сегодня единственный путь — `offline_interview` (живой разговор аналитика с фаундером) и редкие выписки из подкастов, которые аналитик руками заносит в YAML. Большой пласт сигналов — публичные YouTube-интервью фаундера — недоступен без ручного транскрибирования.

Кроме того, YouTube даёт **лучший provenance из доступных онлайн-источников**: deep-link с timestamp (`?t=123s`) и дословная цитата прямо из транскрипта. То, чего у LLM Report Ingest приходится добиваться вторым проходом по URL, у YouTube есть бесплатно по построению.

Цель — превратить YouTube-ссылку в набор атомарных фактов в матрице за один прогон, с эталонной точностью провенанса и интерактивным confirm-экраном.

## 2. Что это НЕ

* **Не новый канал.** Источники пишутся в `online_interview` со всем его методологическим режимом (имеет право на L1, L2, L3, L4, L7). Никакого `youtube` в `sources.channel`.
* **Не верификатор.** Если фаундер в интервью сказал «мы выросли в 10×», ingest это запишет с источником, но не проверит правдивость. Это работа cross-source consensus, отдельный шаг.
* **Не stream-канал.** Идёт прогон на одну ссылку. Подписки на новые видео канала / автоматический watch — будущее (см. §11).
* **Не закрывает offline_interview.** Публичное интервью — это не приватный разговор. Слой 1.3 (Fears, Dreams, Identity) почти всегда требует offline; ingest не должен «подменять» это самоощущением фаундера на камеру.

## 3. Входной артефакт

Принимаемые URL-форматы:

* `https://www.youtube.com/watch?v=VID` (canonical)
* `https://youtu.be/VID`
* `https://www.youtube.com/shorts/VID` (но обычно ничего не даст — слишком короткие)
* `https://www.youtube.com/live/VID`
* короткие ссылки (`t.co/...`, `bit.ly/...`) — резолвить через HEAD-редирект до канонического YouTube URL

После канонизации храним в БД `https://www.youtube.com/watch?v=VID` без `&t=`, `&list=`, `&pp=` и прочих параметров. `VID` — единственный ключ идемпотентности.

**Длительность** не ограничена сверху. Видео любой длины режется AudioChunker'ом (§4, шаг 3a) на 60-минутные куски с 5-сек overlap, каждый кусок транскрибируется независимо, результаты склеиваются с правильным сдвигом timestamps. Тест на 4-часовом подкасте — часть Task 8.

## 4. Pipeline

```
youtube URL
   │
   ▼
[1] URLNormalizer            ──► canonical youtube URL + video_id
                                  отсечь параметры, резолвить shortlinks
   │
   ▼
[2] MetadataFetcher (yt-dlp) ──► title, channel_name, channel_url,
                                  duration_sec, upload_date, description
                                  (без скачивания аудио)
   │
   ▼
[3] AudioFetcher (yt-dlp)    ──► OGG/opus 16kHz mono
                                  пишется в tmp/<video_id>.opus,
                                  cache hit на youtube_transcripts → пропускаем шаги 3a-4
   │
   ▼
[3a] AudioChunker (ffmpeg)   ──► режет на ≤3600-секундные куски с 5-сек overlap
                                  список: [{path, chunk_start_sec}, ...]
                                  одно видео ≤1h → один chunk без резки
                                  политика overlap: следующий чанк начинается
                                  за 5s до конца предыдущего, чтобы не резать
                                  посередине слова
   │
   ▼
[4] Transcriber              ──► для каждого chunk:
       (faster-whisper            transcribe → [{text, start, end}]
        + large-v3-turbo          к каждому segment.start/end прибавляем
        локально по дефолту;      chunk_start_sec
        OpenAI Whisper API и      затем deduplicate сегменты в зоне overlap
        Deepgram за feature-      (сравнение по тексту + IoU по timestamp)
        flag)                     результат — единый Transcript на всё видео
                                  кэшируем в youtube_transcripts как blob
   │
   ▼
[5] TranscriptToReportIR     ──► one-source IR-структура совместимая с
                                  существующим FactExtractor:
                                  {sections: [{heading: "Transcript",
                                               paragraphs: [...], cite_id: 1}],
                                   citations: [{cite_id: 1,
                                                url: canonical_url,
                                                title: video_title,
                                                publisher: channel_name,
                                                forced_channel: "online_interview"}]}
   │
   ▼
[6] FactExtractor (LLM, существующий)
                              ──► [{text, subsection_id, flag, segment_idx_range}]
                                  Промпт расширяется: вместо "ссылок [N]"
                                  факт ссылается на индекс сегмента
                                  транскрипта. Маппинг section→layer
                                  тривиальный (всё из одной секции
                                  "Transcript"), реальный subsection
                                  определяется по содержимому факта.
   │
   ▼
[7] SnippetAnchor (новый)    ──► для каждого факта собирает:
                                  • source_url с ?t={start_sec}s
                                  • evidence_snippet = literal text из
                                    segments[start_idx..end_idx]
                                  • если объединённый текст < 20 chars —
                                    расширяет диапазон сегментов до ≥20
                                  • snippet_start_sec, snippet_end_sec
                                    сохраняются для подсветки в UI
   │
   ▼
[8] LayerGuard               ──► если subsection_id ∈ {L5, L6, L8.*} —
                                  факт пропускается с warning, потому что
                                  online_interview по методологии может
                                  только L1, L2, L3, L4, L7.
                                  Это сильнее, чем у LLM Report Ingest:
                                  там online_interview мог проползти в L4
                                  только если URL явно подкаст. Здесь URL
                                  — это всегда подкаст, поэтому L4 ок.
   │
   ▼
[9] MatrixMerger (существующий)
                              ──► matrix.add_fact с provenance, идемпотентно
   │
   ▼
[10] ExpertConfirm UI         ──► экран как у LLM Report Ingest,
                                  таблица фактов с keep/edit/drop
   │
   ▼
[11] Commit + AuditLog
```

## 5. Канал и слои

Источник из YouTube пишется в `sources.channel = "online_interview"` **детерминистично**. URL-классификатор (`source_channel.py`) не вызывается — мы знаем, что это интервью, по входному loader'у.

Допустимые слои для online_interview (из существующей таблицы):

* **L1** — Founder Personal Story (1.1 Origin, 1.2 Values, 1.3 Fears, Dreams & Identity) — да, если в подкасте есть прямые ответы фаундера про детство, ценности, мотивации
* **L2** — Founder Professional Story — да, основная зона YouTube-интервью
* **L3** — Community Culture — да, если фаундер описывает культуру компании / комьюнити
* **L4** — Community Professional Experience — да, если рассказывает про команду
* **L7** — Social Impact Vision — да, если развёрнуто описывает миссию

Запрещённые (LayerGuard в Step 8 их режет):

* **L5** Clients — Stories — нужно слово клиента, не фаундера
* **L6** Product & Business — это техническая зона, online_research/archival
* **L8** PEST Context — макро-контекст не из единичного подкаста

## 6. Whisper-адаптер

Конфигурация — единый интерфейс `Transcriber`:

```python
class Transcriber(Protocol):
    name: str
    def transcribe(self, audio_path: Path, language: str | None) -> Transcript:
        ...

@dataclass
class Transcript:
    segments: list[Segment]   # [(text, start_sec, end_sec)]
    language: str
    provider: str             # 'openai-whisper-1' и т.д.
```

Реализации (выбираются по env):

* `local_faster_whisper.py` — `faster-whisper` (CTranslate2 backend) с моделью `large-v3-turbo` (1.6 GB, ~4 GB RAM в пике, INT8-квантизация). Работает на CPU без внешних API. На 8-ядерном CPU ~1.5× realtime; час аудио → ~40 минут wall-clock (один chunk; с chunking'ом по часу — параллелизация даёт x2 на 2+ ядрах per chunk). Без сетевых вызовов — данные клиента не покидают VPS. **Дефолт.**
* `openai_whisper_api.py` — `openai>=1.0`, модель `whisper-1`, формат `verbose_json`. Требует `OPENAI_API_KEY`. ~$0.36 за час аудио, ~5–10 мин wall-clock. За feature-flag, для случаев когда нужно очень быстро или нет capacity на сервере. **Помни про 25 MB лимит API на один запрос — chunking spec'а решает это за нас**, каждый чанк меньше лимита (~1h opus 16kHz mono = ~7 MB).
* `deepgram.py` — `deepgram-sdk`, модель `nova-3`. Быстрее Whisper, дешевле, чуть хуже на russian/edge-case. За feature-flag.

Выбор провайдера — через env `TRANSCRIBER` (`local-faster-whisper` | `openai-whisper-1` | `deepgram-nova-3`). По умолчанию `local-faster-whisper`. Если модель ещё не скачана — загружается lazy при первом вызове и кэшируется в volume (см. ниже).

`.env.example` пополняется:

```
# YouTube Ingest
TRANSCRIBER=local-faster-whisper          # дефолт; или openai-whisper-1, deepgram-nova-3
FASTER_WHISPER_MODEL=large-v3-turbo       # или large-v3 (чуть точнее, в 2× медленнее)
FASTER_WHISPER_COMPUTE_TYPE=int8          # или int8_float16 для GPU
FASTER_WHISPER_DEVICE=auto                # cpu / cuda / auto
FASTER_WHISPER_MODEL_DIR=/data/whisper    # volume mount, см. ниже
TRANSCRIBE_PARALLEL_CHUNKS=1              # default 1 (последовательно); 2+ для параллелизации
OPENAI_API_KEY=                           # опционально
DEEPGRAM_API_KEY=                         # опционально
```

### Deployment веса faster-whisper

Веса (~1.6 GB) **не включаются в Docker-образ** — раздуется. Подход:

* В `docker-compose.yml` добавляется именованный volume `whisper-models`, монтируется в `/data/whisper`.
* При первом запросе ingest'а `faster-whisper.WhisperModel("large-v3-turbo", download_root="/data/whisper")` скачает модель и закэширует. Время инициализации первого запроса увеличено на ~30–60 сек (зависит от сети).
* После рестарта контейнера веса остаются в volume; cold-start модели — ~3–5 сек.
* В Dockerfile добавляются только: `pip install faster-whisper` (тянет `ctranslate2` и `tokenizers`) + `apt-get install -y ffmpeg` (для AudioChunker).

### Кэширование транскриптов

Новая таблица:

```sql
CREATE TABLE youtube_transcripts (
    video_id        TEXT PRIMARY KEY,
    canonical_url   TEXT NOT NULL,
    title           TEXT NOT NULL,
    channel_name    TEXT NOT NULL,
    duration_sec    INTEGER NOT NULL,
    language        TEXT NOT NULL,
    transcriber     TEXT NOT NULL,    -- 'openai-whisper-1' etc.
    segments_json   TEXT NOT NULL,    -- [{text, start, end}, ...]
    transcribed_at  TIMESTAMP NOT NULL
);
```

Повторный ингест того же video_id:
* Транскрипт берётся из `youtube_transcripts`, audio не скачивается, Whisper не вызывается.
* Если `transcriber` в кэше отличается от текущего — перетранскрибируем и обновляем строку (с инвалидацией дочерних `evidence_snippet`-ов, см. §8).

## 7. Provenance для YouTube

Каждый факт из YouTube ingest получает:

* **`source_url`** — `https://www.youtube.com/watch?v=VID&t={start_sec}s` (deep-link к моменту начала первого сегмента, на котором стоит факт)
* **`source_title`** — название видео (из `yt-dlp` metadata)
* **`publisher`** — название канала
* **`evidence_snippet`** — дословный текст из `segments[idx_start..idx_end]`, joined через пробел. Минимум 20 chars; если один сегмент короче — добираем соседними.
* `channel = "online_interview"` (детерминистично, см. §5)

Source-row в `sources`:

* `source_url = canonical_url` без `t=` (один source на видео)
* `evidence_snippet = NULL` на уровне source (snippet живёт на уровне fact)
* `archive_url = NULL` (Wayback не применим к YouTube; видео может быть удалено — это отдельная проблема, см. §11)
* `metadata_json = {video_id, channel_name, duration_sec, upload_date, transcriber}`

## 8. Идемпотентность

* **На уровне source**: `canonical_url` (с `video_id` как ключом). Дубль не создаётся, к существующему source привязываются новые facts если их раньше не было.
* **На уровне fact**: триплет `(client_id, subsection_id, normalized_text)`, как у LLM Report Ingest. Совпадение ≥ 0.85 cosine на embedding'ах от существующего LLM-провайдера → это update, не insert.
* **На уровне snippet**: если перетранскрибировали (изменился `transcriber`), все evidence_snippet'ы, привязанные к этому video_id, помечаются как `snippet_stale=true` и `needs_review=true`. Аналитик пересматривает на confirm-экране.

Повторный прогон с того же URL → preview показывает `0 new sources, 0 new facts (cached transcript)`.

## 9. Аудит-журнал

Расширяется существующая таблица `ingest_audit`:

```sql
-- уже есть:
ingest_kind = 'llm_report' | ...
-- добавляем:
ingest_kind = 'youtube'

-- ingest_audit пополняется полями, специфичными для youtube:
ALTER TABLE ingest_audit ADD COLUMN video_id TEXT;
ALTER TABLE ingest_audit ADD COLUMN transcriber TEXT;
ALTER TABLE ingest_audit ADD COLUMN transcribe_cost_usd REAL;
ALTER TABLE ingest_audit ADD COLUMN transcribe_duration_sec INT;
```

Каждый прогон пишет: video_id, transcriber, длительность транскрибирования и приблизительную стоимость ($0.006/min для OpenAI Whisper API). Это даёт операционную видимость: сколько мы тратим на ingest и где.

## 10. Экран подтверждения (UX)

```
YouTube Ingest preview · Libermans (Gonka AI) · 2026-05-21

Source:
  Video    "Libermans on Decentralized AI" (1:23:45)
  Channel  Some Crypto Podcast
  URL      youtube.com/watch?v=abc123XYZ
  Transcribed via openai-whisper-1 · $0.51 · 8m wall-clock

Facts (14 emitted · 2 grey · 1 red):
  [L2.1] green  "Братья начали в Bitfury в 2014, ушли в 2019 после раунда X"
               source: watch?v=abc123XYZ&t=420s
               snippet: "...we joined Bitfury in 2014, basically a year after
                         it was founded, and we left in 2019 after the Series B..."
                                                       [keep]  [edit]  [drop]

  [L1.2] green  "Ценности из детства: отец учил программированию с 6 лет"
               source: watch?v=abc123XYZ&t=156s
               snippet: "My dad sat me down with a Pascal book when I was six..."
                                                       [keep]  [edit]  [drop]

  [L8.2] —     ⚠ skipped: online_interview не пишет в L8
               text: "DePIN-рынок вырастет до $32B к 2028"
                                                       [override and keep]  [drop]

  ...

[ ] Подтверждаю импорт  [ ] Создать work-item на verify-claims-from-this-source
```

Экран — `frontend/src/components/IngestYouTube.tsx`, копия `IngestLLMReport.tsx` с одним отличием: вместо file-upload — `<input type="url">`. Превью использует тот же компонент таблицы фактов.

После confirm — `POST /api/clients/{id}/ingest/youtube/commit` с массивом подтверждённых fact_ids.

## 11. Что НЕ делает MVP

* **Идентификацию спикеров.** Если в подкасте говорят трое, мы не помечаем, кто из них фаундер. Whisper diarization (`whisper-1` его не делает, но Deepgram умеет) — за feature-flag, v2.
* **Verification.** Сказанное в подкасте не проверяется на правду. Это отдельный шаг.
* **Stream-режим.** Подписка на YouTube-канал, автоматический pull новых видео, push в work-items — будущее (`youtube_subscriptions` таблица + cron). v3.
* **PRIVATE / age-restricted видео.** yt-dlp требует cookies для них. MVP — только публичные.
* **Видео без аудио / только музыка.** Whisper вернёт пустой транскрипт — ingest пропускается с warning'ом.
* **Удалённые видео.** Если через год видео удалят — `evidence_snippet` останется в БД, но `source_url` будет битый. Wayback не сохраняет YouTube-аудио; на v2 можно прикрутить хранение оригинального аудио в S3, но это ёмкая дискуссия (rights, storage cost).

## 12. Roadmap

1. **MVP (v1)** — OpenAI Whisper API + ChatGPT-style fact extractor + preview UI. Один URL → preview → commit. **На этом этапе мы.**
2. **v1.1** — кэширование транскриптов в `youtube_transcripts`, идемпотентность.
3. **v2** — Deepgram + local-faster-whisper за feature-flag.
4. **v2.1** — diarization (когда несколько спикеров, помечать кто именно сказал).
5. **v3** — подписка на каналы, автоматический pull новых видео в work-items.
6. **v3.1** — diff-вид «второй подкаст с тем же фаундером» с conflict highlight (он сказал в 2024 одно, в 2026 другое).
7. **v4** — параллельно с YouTube — Spotify (RSS-feed подкаста + распознавание аудио).

## 13. Open questions

* **Embedding-провайдер для fact-dedup.** Для идемпотентности §8 нужен механизм сравнения «новый факт vs существующий». Сейчас в проекте нет embedding-сервиса. На MVP — string similarity (Jaccard / Levenshtein), этого должно хватить для большинства случаев. Embeddings — v2, когда станет понятно, где string similarity не справляется.
* **Параллелизация chunks.** В §6 заложен `TRANSCRIBE_PARALLEL_CHUNKS=1` (последовательно). На 16-ядерном сервере можно поставить 2 — это даст ускорение ~2× на видео >2h. Но `faster-whisper` уже сам пожирает все ядра одной инстанции, так что 2 параллельных воркера могут конкурировать. Реальный выбор — после первого замера на проде.

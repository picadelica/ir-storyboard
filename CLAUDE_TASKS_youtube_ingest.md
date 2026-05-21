# План работ для Claude Code — YouTube Ingest

> **Аудитория этого документа — Claude Code**, запущенный в этой папке.
> Прочитай файл целиком, потом выполняй задачи строго по порядку
> (Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8).
> После каждой завершённой задачи — `git add . && git commit -m "youtube-<N>: <subject>"`.
> Если задача неоднозначна — задай ОДИН уточняющий вопрос аналитику и подожди ответа.

---

## Контекст

`ir-storyboard` — внутренний инструмент IR-агентства (FastAPI + SQLite ядро `ir_storyboard/` + React/TS фронт `frontend/`). Уже работает: 8-слойная матрица, 4 канала сбора, 3 цикла, 3 read-only вью, Process Layer (Tasks 1–5 закрыты), LLM Report Ingest (Tasks 1–8 + пост-фиксы закрыты).

Подробно — `README.md` и `CLAUDE.md`. Перед стартом перечитай:

* `YOUTUBE_INGEST_SPEC.md` — спецификация (pipeline, Whisper-адаптер, provenance с timestamp-anchor, идемпотентность, LayerGuard). **Это твой контракт.**
* `LLM_REPORT_INGEST_SPEC.md` — родственная спека; YouTube ingest переиспользует её FactExtractor, matrix merger, audit, preview UX.
* `ir_storyboard/channels/llm_report/` — существующий пайплайн, который мы расширяем.
* `ir_storyboard/channels/online_interview.py` — канал, в который пишутся источники.
* `ir_storyboard/matrix.py:add_fact` + `validate_provenance` — единственная точка записи фактов.
* `backend/main.py` — паттерн endpoint'ов `/api/clients/{id}/ingest/llm-report/{preview,commit,history}`.
* `frontend/src/components/IngestLLMReport.tsx` — образец фронта.
* `schema.sql` — миграции делаем идемпотентным `ALTER TABLE` в `db.init_schema`.

## Зачем эта задача

Сегодня YouTube-интервью с фаундером — мёртвый зонi для матрицы: аналитик слушает руками, выписывает в YAML. YouTube ingest закрывает это: ссылка → транскрипт через Whisper → факты в матрице с deep-link на момент произнесения и дословной цитатой.

Это **не пятый канал** — источники пишутся в существующий `online_interview` детерминистично. Это **новый loader** в инфраструктуре `llm_report` (которую правильнее было бы переименовать в `ingest` — но не в этой задаче, см. §Hygiene в конце).

**Принципы, которые нельзя нарушать:**

* **Provenance enforced.** Каждый факт пишется через `matrix.add_fact` с `source_id`, который ссылается на source-row с `http(s)://www.youtube.com/...` URL. `evidence_snippet` ≥ 20 chars обязателен (для grey — опционален). `source_url` факта (не source) включает `&t={start_sec}s`.
* **Канал — `online_interview` детерминистично.** URL-классификатор не вызывается. На запись в БД `sources.channel = "online_interview"`.
* **LayerGuard.** Факты, претендующие на L5 / L6 / L8.* — пропускаются с warning'ом (online_interview не имеет права на эти слои). Аналитик может override на confirm-экране, но это требует явного клика.
* **Идемпотентность.** Повторный ингест того же `video_id` → `0 new sources, 0 new facts`. Транскрипт берётся из кэша.
* **Никаких новых каналов.** `OnlineInterviewChannel` — единственная точка записи. Никаких `YouTubeChannel`.
* **Никаких новых LLM-провайдеров для извлечения фактов.** Используем существующий `ir_storyboard/llm.py`. Whisper — отдельный transcriber, не «LLM-провайдер» в смысле проекта.
* **Frontend на react-query + Tailwind**, по образцу `IngestLLMReport.tsx`. Без новых стейт-менеджеров.
* **Миграции SQLite — только идемпотентные `ALTER TABLE`** в `db.init_schema`. Без Alembic.
* **CLAUDE.md / NEXT.md — поддерживать актуальными.** После каждой задачи обновляй `NEXT.md` (HEAD, статус).

---

## Промпт для Claude Code (копировать в чат)

```
Прочитай CLAUDE_TASKS_youtube_ingest.md в этой папке — это пошаговый план
встраивания YouTube Ingest поверх существующего LLM Report Ingest.

Перед стартом перечитай:
  YOUTUBE_INGEST_SPEC.md, LLM_REPORT_INGEST_SPEC.md, CLAUDE.md, NEXT.md,
  schema.sql, ir_storyboard/models.py, ir_storyboard/matrix.py,
  ir_storyboard/channels/online_interview.py,
  ir_storyboard/channels/llm_report/pipeline.py,
  ir_storyboard/channels/llm_report/snippet_resolver.py,
  ir_storyboard/llm.py, backend/main.py,
  frontend/src/components/IngestLLMReport.tsx.

Поведение:
- Выполняй Task 1 → 8 строго по порядку.
- После каждой завершённой задачи — git commit "youtube-<N>: <subject>".
- DoD каждой задачи перечитывай перед стартом.
- Не ломай существующие эндпоинты, seed Accumulator, LLM Report Ingest
  тесты, Process Layer тесты. Все pytest должны оставаться зелёными
  после каждой задачи.
- Никаких новых каналов в ALL_CHANNELS. online_interview — единственная
  точка записи. LayerGuard — это новый модуль, не channel.
- Никаких новых LLM-клиентов для extraction (используем существующий
  llm.py). Whisper — отдельная инфраструктура.

Зафиксированные решения (не открывать заново):
- Whisper-провайдер по умолчанию: local-faster-whisper + large-v3-turbo.
  OpenAI Whisper API и Deepgram — за feature-flag.
- Видео любой длины режется ffmpeg'ом на 60-минутные куски с 5-сек
  overlap. Авторазрезание — часть MVP, не v2.

Перед стартом задай ОДИН уточняющий вопрос:
- Embedding для fact-dedup в §8 спеки: реальный provider или fallback
  на string similarity (Jaccard/Levenshtein)? (default: string similarity
  на MVP, embeddings — v2)

После ответа стартуй с Task 1 и не останавливайся, пока не дойдёшь до
Task 8 или не упрёшься в блокер. Используй TodoWrite для трекинга.
```

---

## Task 1 — URL normalization + metadata fetching

Цель: вход в pipeline — корректный YouTube URL и базовые метаданные без скачивания аудио.

### 1.1 Что делается

Новый модуль `ir_storyboard/channels/llm_report/loaders/youtube_url.py`:

```python
@dataclass
class YouTubeVideoMeta:
    video_id: str               # 'abc123XYZ'
    canonical_url: str          # 'https://www.youtube.com/watch?v=abc123XYZ'
    title: str
    channel_name: str
    channel_url: str
    duration_sec: int
    upload_date: str            # 'YYYY-MM-DD'
    description: str
    language: str | None        # из metadata если есть

def normalize_url(raw_url: str) -> str:
    """t.co/... → реальный youtube URL; убирает t=, list=, pp=, si=."""

def fetch_metadata(canonical_url: str) -> YouTubeVideoMeta:
    """yt-dlp --skip-download --dump-json"""
```

`yt-dlp` добавить в `backend/requirements.txt`. На уровне Python используем как библиотеку (`yt_dlp.YoutubeDL`), не CLI.

### 1.2 Поддерживаемые форматы URL

`normalize_url` распознаёт и приводит к canonical:
* `https://www.youtube.com/watch?v=VID` (canonical)
* `https://youtu.be/VID`
* `https://www.youtube.com/shorts/VID`
* `https://www.youtube.com/live/VID`
* `https://m.youtube.com/watch?v=VID`
* `t.co/...`, `bit.ly/...`, `lnkd.in/...` — резолвить через `requests.head(allow_redirects=True)` до youtube URL

Не youtube URL → `ValueError("Not a YouTube URL: {url}")`.

### 1.3 Тесты

`tests/test_youtube_url.py`:
* `test_normalize_*` для всех 5 форматов youtube + 1 t.co (мок через `responses` или `pytest-httpx`)
* `test_normalize_rejects_non_youtube` — ожидаем ValueError на `https://example.com/foo`
* `test_normalize_strips_query_params` — `?t=120&list=PL...&si=xxx` → чистый watch URL
* `test_fetch_metadata_stub` — мокаем `YoutubeDL.extract_info` и проверяем mapping в `YouTubeVideoMeta`

**DoD:** `pytest tests/test_youtube_url.py -q` зелёный. `yt-dlp` в requirements.txt. Никаких изменений вне `channels/llm_report/loaders/`.

**Коммит:** `youtube-1: URL normalization + yt-dlp metadata fetch`

---

## Task 2 — Audio fetch + chunking + transcribe (faster-whisper adapter)

Цель: video_id → opus → ffmpeg-чанки по часу → транскрипт с правильными timestamp'ами → кэш. Локальный `faster-whisper + large-v3-turbo` по умолчанию, OpenAI/Deepgram за flag.

### 2.1 Audio fetch

`ir_storyboard/channels/llm_report/loaders/youtube_audio.py`:

```python
def fetch_audio(video_id: str, cache_dir: Path) -> Path:
    """yt-dlp -f bestaudio + extract_audio в opus 16kHz mono.
    Возвращает путь к файлу. Если уже есть в cache_dir — пропускает."""
```

`yt-dlp` параметры: `format='bestaudio'`, `postprocessors=[{'key': 'FFmpegExtractAudio', 'preferredcodec': 'opus', 'preferredquality': '64'}]`, `postprocessor_args=['-ac', '1', '-ar', '16000']` (мono 16 kHz — оптимум для Whisper), ratelimit, max retries. ffmpeg должен быть в Dockerfile (`apt-get install -y ffmpeg`).

### 2.2 AudioChunker

`ir_storyboard/channels/llm_report/loaders/audio_chunker.py`:

```python
@dataclass
class AudioChunk:
    path: Path
    chunk_start_sec: float    # offset исходного файла, к которому относится chunk
    chunk_end_sec: float

def split_audio(audio_path: Path, max_chunk_sec: int = 3600,
                overlap_sec: int = 5) -> list[AudioChunk]:
    """Если duration <= max_chunk_sec → [AudioChunk(path, 0, duration)].
    Иначе ffmpeg режет с overlap'ом:
      ffmpeg -i input.opus -ss <start> -t <max_chunk_sec+overlap_sec>
             -c copy chunks/<i>.opus
    chunk_start_sec для i-го куска = i * max_chunk_sec
    (overlap_sec идёт «вперёд», не «назад»).
    """
```

Параметры конфигурируются env: `MAX_CHUNK_SEC=3600`, `CHUNK_OVERLAP_SEC=5`. Дефолты — то, что в спеке.

### 2.3 Transcriber interface

`ir_storyboard/channels/llm_report/loaders/transcriber.py`:

```python
@dataclass
class TranscriptSegment:
    text: str
    start: float      # seconds, относительно начала ВСЕГО видео
    end: float

@dataclass
class Transcript:
    segments: list[TranscriptSegment]
    language: str
    transcriber: str   # 'local-faster-whisper:large-v3-turbo' и т.д.
    duration_sec: int

class Transcriber(Protocol):
    def transcribe(self, audio_path: Path, language_hint: str | None = None
                  ) -> list[TranscriptSegment]:
        """Возвращает segments В СИСТЕМЕ КООРДИНАТ chunk'а
        (от 0 до chunk_duration). Сдвиг к глобальному времени —
        в orchestrator'е get_or_transcribe."""

def get_transcriber() -> Transcriber:
    """По env TRANSCRIBER возвращает реализацию.
    Default: LocalFasterWhisperTranscriber.
    Если local не доступен (faster-whisper не установлен) — RuntimeError
    с понятной подсказкой про pip install + ffmpeg."""
```

Реализации:

* **`LocalFasterWhisperTranscriber`** (дефолт) — `faster_whisper.WhisperModel(model_name, device=FASTER_WHISPER_DEVICE, compute_type=FASTER_WHISPER_COMPUTE_TYPE, download_root=FASTER_WHISPER_MODEL_DIR)`. Singleton на процесс (одна загрузка модели на жизнь процесса). Параметры из env (см. §6 спеки): `FASTER_WHISPER_MODEL` (default `large-v3-turbo`), `FASTER_WHISPER_COMPUTE_TYPE` (default `int8`), `FASTER_WHISPER_DEVICE` (default `auto`), `FASTER_WHISPER_MODEL_DIR` (default `/data/whisper`).
* **`OpenAIWhisperTranscriber`** (за flag `TRANSCRIBER=openai-whisper-1`) — `openai.audio.transcriptions.create(model='whisper-1', response_format='verbose_json', timestamp_granularities=['segment'])`. 25 MB лимит API больше не проблема — chunking в §2.2 это решает за нас (1h opus 16kHz mono ~7 MB).
* **`DeepgramTranscriber`** (за flag `TRANSCRIBER=deepgram-nova-3`) — `deepgram-sdk`, модель `nova-3`. Опционально, для случаев когда хочется ещё быстрее.

### 2.4 Orchestrator + merge timestamps

```python
def get_or_transcribe(video_id: str, meta: YouTubeVideoMeta,
                     transcriber: Transcriber, conn: sqlite3.Connection
                     ) -> Transcript:
    """1. Если есть в youtube_transcripts с тем же transcriber → return cached
       2. fetch_audio (Task 2.1)
       3. split_audio (Task 2.2) → list[AudioChunk]
       4. для каждого chunk:
          segments = transcriber.transcribe(chunk.path)
          для каждого segment:
              segment.start += chunk.chunk_start_sec
              segment.end += chunk.chunk_start_sec
       5. dedupe сегменты в зоне overlap (см. ниже)
       6. сохранить в youtube_transcripts
       7. return Transcript
    """
```

**Dedup overlap-сегментов:** между концом chunk_i и началом chunk_{i+1} есть 5 сек перекрытия. После сдвига timestamps туда попадут дубликаты сегментов. Алгоритм:

```
для каждой пары соседних chunks (i, i+1):
    boundary = chunks[i+1].chunk_start_sec
    take segments_left = [s for s in chunks[i].segments if s.start < boundary]
    take segments_right = [s for s in chunks[i+1].segments if s.start >= boundary - 5]
    # в зоне boundary-5 .. boundary могут быть оба
    for sr in segments_right:
        if any(_similar(sl.text, sr.text) and abs(sl.start - sr.start) < 2.0
               for sl in segments_left if sl.start >= boundary - 5):
            skip sr
        else:
            keep sr
```

`_similar`: lower + strip + Jaccard ≥ 0.8 на словах. Это не идеально, но для overlap'а 5 сек ошибки редки и не критичны (один сегмент в 0.5% случаев).

### 2.5 Кэширование

Новая таблица в `schema.sql` + миграция в `db.init_schema`:

```sql
CREATE TABLE IF NOT EXISTS youtube_transcripts (
    video_id        TEXT PRIMARY KEY,
    canonical_url   TEXT NOT NULL,
    title           TEXT NOT NULL,
    channel_name    TEXT NOT NULL,
    duration_sec    INTEGER NOT NULL,
    language        TEXT NOT NULL,
    transcriber     TEXT NOT NULL,     -- 'local-faster-whisper:large-v3-turbo'
    segments_json   TEXT NOT NULL,     -- final merged segments, в координатах всего видео
    transcribed_at  TIMESTAMP NOT NULL,
    transcribe_duration_sec INTEGER NOT NULL  -- сколько wall-clock заняло
);
```

Идемпотентность: если `transcriber` в кэше отличается от текущего env-значения — перетранскрибируем (записываем заново) и логируем в audit, что snippets могут устареть.

### 2.6 Тесты

`tests/test_youtube_audio_chunker.py`:
* `test_split_under_max_returns_one_chunk` — 30-мин audio → 1 chunk, `chunk_start_sec=0`
* `test_split_2h_video_with_default_settings` — 2-часовое (мокаем ffprobe) → 2 chunks с правильными start_sec (0, 3600)
* `test_split_uses_overlap` — chunk[0] длительность включает overlap, chunk[1].chunk_start_sec на overlap НЕ сдвинут (overlap «вперёд»)
* `test_split_invokes_ffmpeg_correctly` — capture ffmpeg-команды через мок, проверяем `-ss`, `-t`, `-c copy`

`tests/test_youtube_transcribe.py`:
* `test_get_or_transcribe_cache_hit_same_transcriber` — пред-заполняем `youtube_transcripts`, мокаем transcriber и audio fetch, проверяем что ни один не вызван
* `test_get_or_transcribe_cache_miss_single_chunk` — пустая таблица, мокаем `fetch_audio` → возвращает фейковый Path длиной 30 мин (мок `ffprobe`), мокаем transcriber → возвращает hard-coded segments в координатах chunk'а, проверяем что в БД появилась строка с правильным `segments_json`
* `test_get_or_transcribe_multi_chunk_offsets_timestamps` — 2-часовое аудио, мокаем chunker → 2 chunks, transcriber возвращает по 3 segment'а на каждый (все с start=0..120), результат — 6 сегментов с start ∈ [0, 120, 3600, 3720, ...]
* `test_overlap_dedup_drops_duplicate_in_boundary_zone` — chunk[0].last_segment = "...we joined Bitfury in 2014" со start 3595; chunk[1].first_segment = "we joined Bitfury in 2014" со start 0 → после offset start=3600 → дубль детектится и режется
* `test_cache_invalidates_on_transcriber_change` — кэш с `transcriber='openai-whisper-1'`, env стал `local-faster-whisper:large-v3-turbo` → перетранскрибируем, audit получает warning
* `test_local_faster_whisper_import_error_hint` — если `faster-whisper` не установлен — RuntimeError с message «pip install faster-whisper + apt-get install ffmpeg»

CI не гоняет реальную транскрибацию — везде мок.

**DoD:** все тесты зелёные. `faster-whisper`, `yt-dlp`, `openai>=1.0` (optional) в `requirements.txt`. ffmpeg в `backend/Dockerfile`. `docker-compose.yml` имеет volume `whisper-models:/data/whisper`. `.env.example` пополнен (см. §6 спеки).

**Коммит:** `youtube-2: audio fetch + ffmpeg chunking + faster-whisper transcriber + cache`

---

## Task 3 — Transcript → ReportIR adapter

Цель: превратить `Transcript` в существующий `LLMReportIR`, чтобы переиспользовать FactExtractor.

### 3.1 Адаптер

`ir_storyboard/channels/llm_report/transcript_to_ir.py`:

```python
def transcript_to_ir(transcript: Transcript, meta: YouTubeVideoMeta) -> LLMReportIR:
    """Одна секция 'Transcript', один RawCitation с forced_channel='online_interview'.
    Параграфы — собранный текст сегментов, разбитый по паузам > 2.0 sec
    или каждые ~500 chars (whichever first).
    
    Возвращаемый IR хранит сегменты в parser_notes как JSON-сериализованный
    список — это будет нужен SnippetAnchor'у в Task 5.
    """
```

Расширить существующий `RawCitation`:

```python
@dataclass
class RawCitation:
    cite_id: int
    raw_marker: str
    url: str
    title: str = ""
    publisher: str = ""
    forced_channel: str | None = None   # ← НОВОЕ
```

В `source_classifier.classify_citation()` — если `forced_channel` непустой, возвращать его без вызова URL-классификатора.

### 3.2 Тесты

`tests/test_transcript_to_ir.py`:
* `test_transcript_to_ir_basic` — 10 сегментов с разными паузами; ожидаем 1 секцию, ≥1 параграф, 1 цитату с `forced_channel='online_interview'`
* `test_transcript_to_ir_preserves_segments_in_notes` — после adapter'а можем достать оригинальные сегменты из IR (это нужно для SnippetAnchor)

`tests/test_source_classifier.py` (расширить существующий):
* `test_classify_respects_forced_channel` — цитата с `forced_channel='online_interview'` остаётся `online_interview` независимо от URL.

**DoD:** оба теста зелёные. Не ломает существующий `tests/test_llm_report_citations.py`.

**Коммит:** `youtube-3: transcript-to-IR adapter + forced_channel in RawCitation`

---

## Task 4 — FactExtractor adaptation для транскриптов

Цель: научить `FactExtractor` принимать «одну большую секцию = транскрипт» и проставлять `segment_idx_range` для последующей привязки snippet'а.

### 4.1 Что меняется

`ir_storyboard/channels/llm_report/extractor.py` (где сейчас живёт промпт):

* Промпт расширяется: input может быть либо «document with N sections» (как сейчас), либо «transcript with M segments» — детектируется наличием поля `parser_notes.transcript_segments` в IR.
* Для transcript-mode output JSON для каждого факта дополняется:

  ```json
  {"text": "...", "subsection_id": "L2.1", "flag": "green",
   "cite_ids": [1],
   "segment_idx_start": 12, "segment_idx_end": 14}
  ```

* Section→layer mapping тривиальный (всё из одной "Transcript" секции). Реальный subsection_id определяется по содержимому факта — LLM решает.

### 4.2 Промпт

В `_EXTRACT_SYSTEM` добавить блок:

```
If input is a TRANSCRIPT (single section with timestamped segments,
indicated by `transcript_segments` in metadata):
- For each fact, return `segment_idx_start` and `segment_idx_end`
  pointing to segment indices that contain the literal phrasing
  supporting the fact.
- Range should be tight: prefer 1-3 segments. Wider only if a single
  segment is shorter than 20 characters.
- Skip segments that are filler ("um, you know, like, basically...").
- DO NOT invent segments — if the transcript doesn't say it, don't
  emit the fact.
- LayerGuard will reject facts mapped to L5/L6/L8 (online_interview
  cannot feed those). Avoid emitting them; if you must, mark with
  `layer_warning: true`.
```

### 4.3 Тесты

`tests/test_extractor_transcript_mode.py`:
* `test_transcript_mode_returns_segment_indices` — мокаем LLM-ответ с 3 фактами, проверяем что pipeline их пропускает не теряя `segment_idx_*`
* `test_transcript_mode_layer_warning_passed_through` — если LLM вернул L5 факт с `layer_warning=true`, он попадает в результат с этим маркером (LayerGuard зарежет на Task 5)

**DoD:** оба теста зелёные. `tests/test_llm_report_extractor.py` (document-mode) остаётся зелёным — не ломаем существующую логику.

**Коммит:** `youtube-4: FactExtractor transcript-mode with segment indices`

---

## Task 5 — SnippetAnchor + LayerGuard

Цель: собрать `source_url` с `?t=` и `evidence_snippet` из сегментов. Зарезать L5/L6/L8.

### 5.1 SnippetAnchor

`ir_storyboard/channels/llm_report/snippet_anchor.py`:

```python
def anchor_facts(facts: list[ExtractedFact],
                 transcript: Transcript,
                 canonical_url: str) -> list[AnchoredFact]:
    """Для каждого факта:
       - join transcript.segments[idx_start..idx_end].text → evidence_snippet
       - если result < 20 chars: расширить idx_end (до idx_end+2 макс)
       - если всё ещё < 20: пометить needs_review=true и flag=grey
       - source_url = f'{canonical_url}&t={int(start_sec)}s'
       - сохранить snippet_start_sec, snippet_end_sec для UI
    """
```

### 5.2 LayerGuard

`ir_storyboard/channels/llm_report/layer_guard.py`:

```python
ALLOWED_LAYERS_BY_CHANNEL = {
    'online_interview': {'L1.1', 'L1.2', 'L1.3', 'L2.1', 'L2.2', 'L2.3',
                         'L3.1', 'L3.2', 'L3.3', 'L4.1', 'L4.2', 'L4.3',
                         'L7.1', 'L7.2', 'L7.3'},
    # online_research, archival — оставляем для будущего использования
}

def guard_layers(facts: list[AnchoredFact], channel: str) -> tuple[list[AnchoredFact], list[SkippedFact]]:
    """Разделяет facts на allowed / skipped по channel.
    SkippedFact: AnchoredFact + reason."""
```

LayerGuard вызывается до `MatrixMerger`. Skipped факты не пишутся в БД, но передаются в UI как «warning, can override».

### 5.3 Тесты

`tests/test_snippet_anchor.py`:
* `test_anchor_single_segment_above_20chars` — happy path
* `test_anchor_expands_short_segments` — первый сегмент 12 chars → добавляем next до ≥20
* `test_anchor_falls_back_to_grey` — все сегменты в диапазоне суммарно <20 chars → flag=grey, needs_review=true
* `test_anchor_source_url_has_timestamp` — `?t=420s` корректно

`tests/test_layer_guard.py`:
* `test_guard_passes_l1_l4_l7` — все три проходят
* `test_guard_blocks_l5_l6_l8` — все три попадают в skipped с понятным reason
* `test_guard_skipped_facts_carry_text` — для override-UX нужно показать текст и причину

**DoD:** оба теста зелёные.

**Коммит:** `youtube-5: SnippetAnchor (timestamp URL + literal snippet) + LayerGuard`

---

## Task 6 — Backend endpoints

Цель: REST API под YouTube Ingest, по образцу `llm-report` эндпоинтов.

### 6.1 Endpoints

В `backend/main.py`:

```
POST   /api/clients/{id}/ingest/youtube/preview
       body: {"url": "https://youtu.be/..."}
       response: {
         "ingest_audit_id": int,
         "meta": YouTubeVideoMeta,
         "facts": [{...AnchoredFact, target_subsection_id, target_flag}],
         "skipped": [{...SkippedFact, override_allowed: true}],
         "transcribe_cost_usd": float | null,
         "from_cache": bool
       }

POST   /api/clients/{id}/ingest/youtube/commit
       body: {"ingest_audit_id": int,
              "accepted_fact_ids": [int],
              "overrides": [{fact_id, force_keep: true}]}
       response: {"committed": int, "skipped": int}

GET    /api/clients/{id}/ingest/youtube/history
       response: list of past audits с meta и counts
```

### 6.2 ingest_audit миграция

```sql
ALTER TABLE ingest_audit ADD COLUMN video_id TEXT;
ALTER TABLE ingest_audit ADD COLUMN transcriber TEXT;
ALTER TABLE ingest_audit ADD COLUMN transcribe_cost_usd REAL;
ALTER TABLE ingest_audit ADD COLUMN transcribe_duration_sec INTEGER;
```

Идемпотентно (детектить колонку → добавлять). Существующие записи с `ingest_kind='llm_report'` остаются нетронутыми.

### 6.3 Pipeline orchestrator

`ir_storyboard/channels/llm_report/youtube_pipeline.py`:

```python
def run_youtube_preview(client_id: str, url: str, conn) -> PreviewResult:
    """1. normalize_url + fetch_metadata
       2. get_or_transcribe (Task 2 cache)
       3. transcript_to_ir
       4. extract_facts (transcript-mode)
       5. anchor_facts
       6. guard_layers('online_interview')
       7. dedupe vs existing matrix facts (Jaccard 0.85)
       8. записать ingest_audit row со статусом 'preview'
       9. вернуть PreviewResult с ingest_audit_id"""

def run_youtube_commit(ingest_audit_id, accepted_fact_ids, overrides, conn) -> CommitResult:
    """1. подтянуть preview из audit
       2. для accepted + overrides — matrix.add_fact через
          OnlineInterviewChannel (он валидирует provenance)
       3. обновить ingest_audit: facts_committed, confirmed_at
       4. вернуть counts"""
```

### 6.4 Тесты

`tests/test_youtube_api.py`:
* `test_preview_returns_facts_with_anchors` — мокаем transcriber, отдаём готовый IR; проверяем что в response есть `facts[].source_url` с `&t=`
* `test_preview_separates_skipped_l5_facts` — LLM возвращает L5 факт, в response он в `skipped`, не в `facts`
* `test_commit_writes_to_matrix` — happy path, после commit'а у клиента +N фактов в нужных subsection_id
* `test_commit_idempotent_on_replay` — второй вызов preview→commit с тем же URL: 0 new sources, 0 new facts
* `test_commit_respects_overrides` — L5 факт с override=true пишется в БД (это явный choice аналитика)

**DoD:** все тесты зелёные. Существующие `tests/test_llm_report_api.py` зелёные.

**Коммит:** `youtube-6: backend endpoints (preview/commit/history) + youtube_pipeline`

---

## Task 7 — Frontend: IngestYouTube tab

Цель: UI для нового ingest, копия `IngestLLMReport.tsx` с одним отличием — URL вместо file upload.

### 7.1 Компонент

`frontend/src/components/IngestYouTube.tsx`:

* Input: `<input type="url" placeholder="https://youtube.com/watch?v=...">` + submit button "Preview"
* Loading state: spinner + сообщение «Скачиваем аудио и транскрибируем (~5–10 минут для часового видео)»
* Preview state: таблица фактов (тот же компонент `<FactRow>`, что и в LLM Report Ingest), source-row сверху с meta (title, channel, duration, transcriber, cost), отдельный блок skipped facts со spaceом override
* После commit: success-banner с counts + кнопка «Перейти к матрице»

### 7.2 Интеграция

`frontend/src/App.tsx`: новый tab "YouTube" в правом контейнере (рядом с "LLM Report" и "Research"). Tab активен, если выбран client.

`frontend/src/api.ts`: типизированные клиенты для трёх новых endpoints.

`frontend/src/types.ts`: типы `YouTubePreviewResult`, `YouTubeFact`, `YouTubeSkipped`.

### 7.3 Тесты

UI-тесты не требуются (фронт-тестов в проекте нет). Smoke-тест вручную: запустить локально, прогнать с моком backend'а через MSW (если уже подключён) или просто проверить рендер на dev-сервере.

**DoD:** компонент рендерится в dev-режиме, при сабмите вызывает `/api/clients/{id}/ingest/youtube/preview`, корректно показывает preview и skipped. nginx прокси работает (`frontend/nginx.conf` уже разрешает long timeouts с прошлой серии — проверь).

**Коммит:** `youtube-7: frontend IngestYouTube component + tab`

---

## Task 8 — E2E test + DEPLOY обновление

Цель: один публичный YouTube URL → matrix содержит ожидаемые факты. Зафиксировать в DEPLOY.md новые env переменные.

### 8.1 E2E test

`tests/test_youtube_e2e.py`:

* Видео-кандидат: 5–15 минут, английский, разговорный (можно подобрать TEDx с правильной лицензией; зафиксировать конкретный URL в фикстуре)
* Запуск **за тегом** `pytest.mark.network`, не гонится в обычном `pytest -q`. Запускается явно: `pytest -m network tests/test_youtube_e2e.py`
* Алгоритм: preview → checks → commit → checks
* Инвариант-ассерты (а не диффы):
  - `len(facts) >= 5`
  - `all(f.evidence_snippet.length >= 20 for f in facts if f.flag != 'grey')`
  - `all('&t=' in f.source_url for f in facts)`
  - `all(f.subsection_id in {'L1.*', 'L2.*', 'L3.*', 'L4.*', 'L7.*'} for f in facts)`
  - `len(skipped) >= 0`  (на этом видео может и не быть L5/L6/L8 фактов)
* Перед запуском: проверка ENV `OPENAI_API_KEY` (или подсказка использовать local-faster-whisper)

Можно создать дополнительно «cached» вариант теста без сети: предзаполнить `youtube_transcripts` для известного video_id mock-транскриптом, проверить что pipeline работает идемпотентно. Этот тест гонится в обычном `pytest -q`.

### 8.2 DEPLOY обновление

`DEPLOY.md`:

* Добавить раздел «YouTube Ingest» с описанием новых env-переменных (из §6 спеки):
  - `TRANSCRIBER` (default `local-faster-whisper`)
  - `FASTER_WHISPER_MODEL` (default `large-v3-turbo`)
  - `FASTER_WHISPER_COMPUTE_TYPE` (default `int8`)
  - `FASTER_WHISPER_DEVICE` (default `auto`)
  - `FASTER_WHISPER_MODEL_DIR` (default `/data/whisper`)
  - `MAX_CHUNK_SEC` (default 3600)
  - `CHUNK_OVERLAP_SEC` (default 5)
  - `TRANSCRIBE_PARALLEL_CHUNKS` (default 1; включать только после замера)
  - `OPENAI_API_KEY`, `DEEPGRAM_API_KEY` — optional, для feature-flag transcriber'ов
* Подтвердить что ffmpeg добавлен в `backend/Dockerfile` (`apt-get install -y ffmpeg`)
* Подтвердить что в `docker-compose.yml` есть volume `whisper-models:/data/whisper` (~2 GB после загрузки `large-v3-turbo`)
* Подтвердить что nginx `proxy_read_timeout` ≥ 1800s. Worst case: 2-часовое видео на CPU занимает ~80 минут wall-clock — это ingest-запрос дольше всех существующих
* Operational profile (без внешних API):
  - **CPU**: пик ~всё доступное на время transcribe (faster-whisper честно жрёт все ядра)
  - **RAM**: ~4 GB на инстанцию модели + ~1 GB на ingest pipeline
  - **Disk**: ~2 GB на модель в volume + до ~50 MB на каждое не очищенное audio в `/tmp` (cleanup на commit/cancel)
  - **Network**: только yt-dlp скачивает аудио (~30 MB на час видео в opus 16kHz mono)
  - **Стоимость**: $0 marginal. Только электричество сервера.
* Если capacity сервера не позволяет такие нагрузки — fallback на OpenAI API (`TRANSCRIBER=openai-whisper-1` + `OPENAI_API_KEY`). ~$0.36/час, ~5-10 мин wall-clock. Документировать как «emergency mode».

### 8.3 CLAUDE.md / NEXT.md

* `CLAUDE.md`: в разделе «Ключевые директории» отметить новые модули (`youtube_pipeline.py`, `transcript_to_ir.py`, `snippet_anchor.py`, `layer_guard.py`). В «Архитектурные инварианты» — добавить пункт про LayerGuard и forced_channel.
* `NEXT.md`: переписать «Что в фокусе» — YouTube Ingest в стабилизации, отметить open question'ы которые остались (provider, embeddings, длинные видео).

**DoD:**
* `pytest tests/test_youtube_e2e.py -q` (cached вариант) зелёный
* `pytest -m network tests/test_youtube_e2e.py` зелёный при наличии OPENAI_API_KEY (вручную)
* `DEPLOY.md`, `CLAUDE.md`, `NEXT.md` обновлены
* `git log --oneline` показывает чистую серию `youtube-1` .. `youtube-8`

**Коммит:** `youtube-8: e2e test + DEPLOY + docs update`

---

## Hygiene (не входит в эти 8 задач)

После закрытия YouTube ingest стоит сделать отдельную сессию рефакторинга:

* Папка `ir_storyboard/channels/llm_report/` фактически уже не «llm_report-only» — она содержит общую инфраструктуру (extractor, snippet, matrix merger, audit), плюс два loader'а (документы и YouTube). Правильно переименовать в `ir_storyboard/ingest/` и разнести loaders по подпапкам.
* `IngestLLMReport.tsx` и `IngestYouTube.tsx` шарят 80% кода (FactRow, source pane, commit flow) — вынести в `<IngestPreview>` базовый компонент.
* Это **отдельная задача**, не делать её в рамках youtube-1..8 чтобы не размывать scope.

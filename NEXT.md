# NEXT — где мы остановились

> Снимок оперативного состояния. Обновлять в конце каждой сессии (overwrite,
> не append). Цель — за 30 секунд понять, где находимся.
>
> Стабильная архитектура и инварианты — в `CLAUDE.md`. Сюда — только
> «здесь и сейчас».

---

**Последнее обновление:** 2026-05-21
**Ветка:** `feat/v2`
**Working tree:** clean (untracked: `.claude/settings.local.json`, `12.jpeg`, `CLAUDE.md`, `NEXT.md`, `YOUTUBE_INGEST_SPEC.md`, `CLAUDE_TASKS_youtube_ingest.md` — все ждут первого коммита)
**HEAD:** `65fea25 fix: pdf_loader per-page error isolation + pypdf fallback for Claude PDFs`

## Что в фокусе

**YouTube Ingest — дизайн готов, код впереди.** Сегодня согласовали с
пользователем feature: YouTube URL → Whisper → факты в матрице с
timestamp-anchor URL и дословной цитатой. Решения:

* Channel: `online_interview` детерминистично (не новый пятый канал)
* Transcriber: **local-faster-whisper + large-v3-turbo по умолчанию**.
  Данные клиента не покидают VPS. OpenAI Whisper API и Deepgram — за
  feature-flag, как «emergency mode» если capacity сервера не хватает.
  Модель (~1.6 GB) хранится в Docker volume `whisper-models:/data/whisper`,
  загружается lazy.
* Captions не используем — Whisper всегда (выбор пользователя за качество)
* **Видео любой длины** — режется ffmpeg'ом на 60-минутные куски с 5-сек
  overlap, transcribe идёт по куску, timestamps сдвигаются обратно к
  глобальной шкале, overlap-дубликаты режутся по Jaccard ≥ 0.8 + timestamp
  proximity
* LayerGuard режет факты в L5/L6/L8 (online_interview не имеет на них права)
* Provenance: `source_url` с `?t={start_sec}s`, `evidence_snippet` —
  literal text из transcript segments
* Preview UI — копия `IngestLLMReport.tsx` с URL-input вместо file-upload
* Идемпотентность по `video_id` через новую таблицу `youtube_transcripts`

**Артефакты дизайна** (не закоммичены, ждут ревью):
* `YOUTUBE_INGEST_SPEC.md` — контракт (12 разделов)
* `CLAUDE_TASKS_youtube_ingest.md` — план на 8 задач (`youtube-1` .. `youtube-8`),
  с готовым промптом для Claude Code и блоком pre-flight вопросов

**LLM Report Ingest** — закрыт (серия `llm-1 … llm-8` + ~14 пост-фиксов).

## Чего ещё не делали (известные хвосты)

Это не TODO-лист, это просто «осознанно отложено». Хвататься без явного
запроса пользователя не нужно.

- **YouTube Ingest** — спека готова, имплементация ждёт. Полный план
  в `CLAUDE_TASKS_youtube_ingest.md`.
- **SnippetResolver v2 (LLM Report Ingest).** На MVP `evidence_snippet`
  = парафраз LLM, помеченный `paraphrase=True` в audit. Дословная
  цитата с открытием URL — за feature-flag, не дефолт.
- **Idempotency на повторный ингест того же файла** заявлена в LLM
  Report spec; проверить, что test_llm_report_e2e реально гоняет два
  прохода и ассертит `0 new sources / 0 new facts` на втором.
- **Adjacent / cross_ref work-items** так и не генерируются автоматически.
- **Audit log diff-вью** — нет UI, только данные.
- **Hygiene refactor:** переименовать `channels/llm_report/` →
  `ingest/` после YouTube Ingest (см. конец `CLAUDE_TASKS_youtube_ingest.md`).

## Открытые вопросы (по YouTube Ingest)

Решения, принятые в этой сессии (НЕ переоткрывать):
- ✓ Transcriber по умолчанию: local-faster-whisper + large-v3-turbo
- ✓ Длинные видео: ffmpeg chunking 60 мин + 5 сек overlap, в MVP

Остался один open вопрос, задан в pre-flight промпта для Claude Code:
1. Embedding для fact-dedup: реальный provider или fallback на string
   similarity (Jaccard/Levenshtein)? Default: string similarity на MVP.

## Следующий разумный шаг (если пользователь скажет «продолжаем»)

1. Закоммитить артефакты дизайна:
   ```
   git add CLAUDE.md NEXT.md YOUTUBE_INGEST_SPEC.md CLAUDE_TASKS_youtube_ingest.md
   git commit -m "docs: session-continuity (CLAUDE.md/NEXT.md) + YouTube Ingest spec"
   ```
2. Запустить Claude Code в этой папке с промптом из
   `CLAUDE_TASKS_youtube_ingest.md` (§Промпт для Claude Code) — он начнёт
   с pre-flight вопросов, потом пойдёт по `youtube-1` .. `youtube-8`.
3. Альтернативно — вместе пройти Task 1 (URL normalization + metadata)
   здесь, в этой сессии, чтобы откалибровать стиль и подход. Это ~30 мин.

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

Цель — чтобы в следующей сессии я по этому файлу + git log за минуту
восстановил картину и продолжил без расспросов.

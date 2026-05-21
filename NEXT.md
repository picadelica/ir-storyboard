# NEXT — где мы остановились

> Снимок оперативного состояния. Обновлять в конце каждой сессии (overwrite,
> не append). Цель — за 30 секунд понять, где находимся.
>
> Стабильная архитектура и инварианты — в `CLAUDE.md`. Сюда — только
> «здесь и сейчас».

---

**Последнее обновление:** 2026-05-21
**Ветка:** `feat/v2`
**Working tree:** clean (untracked: `.claude/settings.local.json`, `12.jpeg`)
**HEAD:** `65fea25 fix: pdf_loader per-page error isolation + pypdf fallback for Claude PDFs`

## Что в фокусе

**LLM Report Ingest — в стабилизации.** Серия `llm-1 … llm-8` закрыта
(loaders → citation → classifier → extractor → snippet → pipeline+merger →
backend endpoints → frontend + e2e). Поверх неё уже прошло ~14 post-fix
коммитов: SQLite thread-safety, requirements, nginx timeouts, prompt
KeyError, max_tokens, parser-fixes под Gemini/Claude PDF, батчинг секций в
один LLM-call, expose `ingest_audit_id` в API, hide `internal://` source_url
от фронта.

Последний коммит — изоляция ошибок per-page в `pdf_loader` с fallback на
`pypdf` для Claude-генерированных PDF.

## Чего ещё не делали (известные хвосты)

Это не TODO-лист, это просто «осознанно отложено». Хвататься без явного
запроса пользователя не нужно.

- **SnippetResolver v2.** На MVP `evidence_snippet` = парафраз LLM,
  помеченный `paraphrase=True` в audit. Дословная цитата с открытием URL —
  за feature-flag, не дефолт. Включать, когда захочется качества.
- **Idempotency на повторный ингест того же файла** заявлена в спеке;
  проверить, что test_llm_report_e2e реально гоняет два прохода и
  ассертит `0 new sources / 0 new facts` на втором.
- **Adjacent / cross_ref work-items** так и не генерируются автоматически.
- **Audit log diff-вью** — нет UI, только данные.

## Открытые вопросы

Пока нет.

## Следующий разумный шаг (если пользователь скажет «продолжаем»)

Без явного запроса — не начинать ничего. Спросить: «что приоритет —
качество (SnippetResolver v2 → дословные цитаты), полнота процесса
(adjacent/cross_ref work-items), наблюдаемость (audit diff UI), или какая-то
новая фича?».

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

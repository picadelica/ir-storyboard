# NEXT — где мы остановились

> Снимок оперативного состояния. Обновлять в конце каждой сессии (overwrite,
> не append). Цель — за 30 секунд понять, где находимся.
>
> Стабильная архитектура и инварианты — в `CLAUDE.md`. Сюда — только
> «здесь и сейчас».

---

**Последнее обновление:** 2026-06-14
**Ветка:** `feat/v2` (мои 2 коммита ребейзнуты поверх audio-ingest серии
параллельной сессии 2026-06-13 — audio file ingest, очистка клиента, плеер/
транскрипт, safety-тесты).
**Working tree:** изменения этой сессии закоммичены и **запушены в origin**.
**Тесты:** `pytest -m "not network"` → **200 passed**.
**Прод:** перекатан 2026-06-13 (audio ingest); после фиксов тестов этой сессии
переката не было — некритично (правки тестов + section-mapping + idempotency).

## Что сделано за сессию 2026-06-14

### 1. Починены 9 «вечных» красных тестов → **200 passed** (`fix:` commit)

Все 9 были в baseline и валились на чистом коде. Корни и фиксы:

- **docx-лоадер** (`ingest/loaders/docx_loader.py`) — экспорт ChatGPT Deep
  Research не имеет блока «Источники»; цитаты `[N]` — инлайн-гиперссылки в теле.
  Добавлен `_extract_inline_citations` (харвест URL прямо с маркеров).
- **stub-экстрактор** (`llm.py::_stub_extract`) — без API-ключа ставил
  `cite_ids=[]`, поэтому `preview.sources` всегда пустой. Теперь вытаскивает
  `[N]` из текста параграфа (`_RE_CITE_MARKER`).
- **идемпотентность коммита** (`ingest/pipeline.py`) — дедуп сравнивал
  `_normalize_fact_text()` с сырым SQL `lower(trim())` → факты с числами в
  скобках дублировались. Нормализую обе стороны в Python. `INSERT OR IGNORE`
  на `ingest_audit` → повторный коммит того же preview идемпотентен.
- **preview-эндпоинт** (`backend/main.py`) — открывал свой `db.connect()` к
  дефолтной БД, игнорируя инъекцию `get_conn` (404 в тестах + побочно ломал
  e2e sqlite). Переведён на `Depends(get_conn)`.
- **section→layer** (`classifiers/section_to_layer.py`) — generic-хинт
  «контекст» (8.1) перебивал «регуляторный и социальный» (8.3). Теперь
  выигрывает самый длинный матчащийся хинт.
- **YouTube preview-тесты** (`tests/test_youtube_api.py`) — эндпоинт стал
  асинхронным (job_id + поллинг), тесты ждали синхронный ответ. Обновлены
  под async-флоу (`_drive_preview` хелпер).

### 2. Интеграция с оркестратором — CI-workflow + документация

- **`test_ir_storyboard`** — новый workflow в Conductor (`git_pull → run_tests
  → notify`). Определение: `conductor-orchestrator/workflows/test_ir_storyboard.json`,
  добавлен в `scripts/register-workflows.sh`. Зарегистрирован через gateway,
  привязан к паспорту (`workflows: [deploy_ir_storyboard, test_ir_storyboard]`).
  `run_tests` гоняет `pytest -m "not network"` в одноразовом контейнере из
  backend-образа (репо ro-mount + копия в /tmp, прод-БД не задета). API-ключи
  заглушены (`-e KEY=`) → детерминированный офлайн stub-режим.
  **Прогон на сервере зелёный** (`passed=true`, exit 0) — провалидировано.
- **`requirements-dev.txt`** — воспроизводимый локальный тест-env (в
  `requirements.txt` не было pytest/pyyaml/fastapi).
- **DEPLOY.md** — новая «Часть 5. Тесты и CI через оркестратор».
- Доп. фикс при валидации CI: `test_e2e_process::_reset` вызывал
  `DELETE FROM work_items` без `init_schema` → падал на свежей БД в контейнере.
  Добавлен `init_schema` (commit `fix: init_schema in test_e2e_process reset`).

> Состояние оркестратор-репы: коммит `test_ir_storyboard` лежит в ветке
> `feat/test-ir-storyboard-ci` (НЕ запушена). Workflow уже зарегистрирован
> вживую через gateway — repo-коммит это source-of-truth, по желанию → push/PR.

## Следующие разумные шаги

1. **Перекат прода** — `dcp up -d --build` (или deploy-workflow). Миграция
   SQLite идемпотентная, без downtime.
2. **Запушить ветку оркестратора** `feat/test-ir-storyboard-ci` (по желанию —
   workflow уже живой на сервере).
3. **Паспорт:** milestones пустые — можно засеять роадмап (по запросу).
   docPercent=40 (после доков по CI можно поднять).
4. **Хвосты из прошлой polish-серии:** YouTube `FactEditForm` rationale-поле
   (требует расширения `FactEdit`); бэкфилл rationale для legacy red фактов.

## Открытое наблюдение

- Воркер оркестратора реализует `git_pull` как `git pull origin <branch>`, а
  онбординг требует `fetch + reset --hard`. Расхождение в репо
  `conductor-orchestrator` (не критично, деплой работает), но стоит выровнять.

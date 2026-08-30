# Восстановление из бэкапа — runbook

> Инструкция для аварии. Читается сверху вниз, команды выполняются как написаны.
> Общий деплой и первичная установка — `DEPLOY.md`; здесь только восстановление.
>
> **Правило номер один: прежде чем что-то восстанавливать, снимите текущее
> состояние.** Даже испорченная база — это данные, а восстановление их затирает.
> Шаг 0 в каждом сценарии именно об этом.

---

## Что где лежит

Прод: сервер `216.57.108.107`, каталог `/opt/ir-storyboard`, контейнеры
`ir-storyboard-backend-1` / `-frontend-1` / `-caddy-1`.

Вся живая информация — **в одном файле** `matrix.db` внутри docker-volume
`storyboard-data`, смонтированного в контейнер как `/app/data`:

```
/app/data/                        ← volume storyboard-data
├── matrix.db                     ← ВСЁ: факты, источники, журнал, пользователи,
│                                    сущности, мониторинг, обзоры, кэш расшифровок
├── backups/
│   ├── <client_id>/*.json        ← пер-клиентские снапшоты (перед clear-data)
│   └── _full/*.db.gz             ← полные снапшоты БД, хранятся последние 20
└── audio_uploads/                ← загруженные аудиофайлы
```

Кэш расшифровок (`youtube_transcripts`, `audio_transcripts`) — таблицы **внутри
`matrix.db`**, отдельно спасать не надо: восстановили базу — вернулись и они,
повторная транскрипция денег не стоит.

### Три бэкапа — и их разная природа

| | Что это | Кем создаётся | Куда |
|---|---|---|---|
| **Ночной, оркестратора** | gzip всей БД (online-backup API) + `tar` файлов volume | оркестратор, workflow `backup_prod`, ежедневно **04:00 UTC** | вне контейнера и вне volume; наружу с сервера — только облаком, см. ниже |
| **Полный снапшот БД** | gzip всего `matrix.db` через online-backup API SQLite (консистентен на живой базе, писателей надолго не блокирует) | `scripts/backup.sh` вручную/по cron; плюс автоматически перед каждым clear-data | `./backups/` в каталоге репозитория (скрипт) и `/app/data/backups/_full/` (автоматический) |
| **Пер-клиентский JSON** | все строки одного клиента, сериализованные в один файл | автоматически перед `DELETE /api/clients/{id}/data` | `/app/data/backups/<client_id>/<ts>.json` |

**Опасное место — их близость к оригиналу.** Два нижних лежат в том же volume, что
и база (или, у скрипта, в каталоге репозитория): потеря volume уносит их вместе с
`matrix.db`. Верхний лежит уже вне volume и переживает пересоздание контейнеров —
но **оркестратор крутится на этом же сервере `216.57.108.107`**, так что от потери
самой машины он тоже не спасает. Настоящий офсайт здесь ровно один — облачная
копия, и она включается отдельно (ниже).

### Ночной бэкап оркестратора

Проверено 2026-08-30 по репозиторию оркестратора: **проект заведён и покрыт.**

- Строка в `deploy/backup/sqlite-targets.txt`:
  `ir-storyboard-backend-1  matrix.db  ir-storyboard` — берётся и БД, и файлы
  volume (`llm_reports`, `audio_uploads`, …) отдельным `tar czf`.
- В манифесте покрытия `deploy/backup/expected-projects.txt` проект помечен
  `active`. Это не декорация: `verify_coverage` в конце каждого прогона роняет
  бэкап, если копии за сегодня нет. То есть «бэкап тихо перестал сниматься»
  здесь не проходит молча.
- Запуск: сервис `corch-cron` дёргает Conductor ежедневно в 04:00 UTC. Вручную —
  `POST $GATEWAY_URL/workflow {"name":"backup_prod","version":1,"input":{"projectId":"conductor-orchestrator"}}`.
- Куда ложится:
  - **на тот же сервер** (bind-mount, переживает пересоздание контейнеров):
    `/opt/conductor-orchestrator/backups/ir-storyboard/ir-storyboard-<ДАТА>-{db.sqlite.gz,files.tar.gz}`,
    ротация 14 дней + воскресные копии в `weekly/` (8 недель);
  - **офсайт — Яндекс.Диск** через `rclone`, `yandex:prod-backups/ir-storyboard`.
    **Включается наличием `secrets/rclone.conf` на сервере** — если его не
    заливали, в логе прогона будет `CLOUD: WARN … ПРОПУЩЕН`, и тогда ВСЕ копии
    системы живут на одной машине. Проверять глазами в логе последнего прогона
    (детали и инструкция по заливке — `docs/backup.md` оркестратора).
  - вторичный ssh-офсайт на `72.56.107.117` — по умолчанию выключен
    (`BACKUP_OFFSITE_FRA=1`), держится как резерв.

### Чего в бэкапе НЕТ

- **`.env`** — ключи `ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `SESSION_SECRET`,
  `IR_ADMIN_TIDS`, `DOMAIN`. В git его нет намеренно. Без него система поднимется,
  но LLM-слой свалится в стабы, а все сессии пользователей станут недействительными
  (при смене `SESSION_SECRET` все просто логинятся заново — не авария).
- **TLS-сертификаты** (volume `caddy-data`) — Caddy перевыпустит сам, восстанавливать
  не нужно.
- **Код** — он в git, ветка `main` = `feat/v2`.

---

## Сценарий A. База испорчена, сервер жив

Самый частый случай: неудачная массовая операция, снесённые факты, сломанный клиент.

**Шаг 0. Снять текущее состояние — до всего остального.**

```bash
ssh root@216.57.108.107
cd /opt/ir-storyboard
docker exec ir-storyboard-backend-1 python3 -c "
import sqlite3
src = sqlite3.connect('/app/data/matrix.db')
dst = sqlite3.connect('/app/data/before-restore.db')
with dst: src.backup(dst)
"
```

**Шаг 1. Выбрать снапшот.**

```bash
docker exec ir-storyboard-backend-1 ls -lt /app/data/backups/_full/   # автоматические
ls -lt /opt/ir-storyboard/backups/                                    # снятые скриптом
```

Смотрите на дату: нужен последний снапшот, сделанный **до** порчи.

**Шаг 2. Проверить, что в снапшоте то, что вы ждёте** — прежде чем им затирать
рабочую базу:

```bash
docker exec ir-storyboard-backend-1 sh -c "
  gunzip -c /app/data/backups/_full/<файл>.db.gz > /tmp/check.db &&
  python3 -c \"
import sqlite3
c = sqlite3.connect('/tmp/check.db')
print('фактов:', c.execute('SELECT COUNT(*) FROM facts').fetchone()[0])
print('клиентов:', c.execute('SELECT COUNT(*) FROM clients').fetchone()[0])
for r in c.execute('SELECT c.client_id, COUNT(*) FROM facts f JOIN cells c ON c.id=f.cell_id GROUP BY 1 ORDER BY 2 DESC LIMIT 10'):
    print(' ', r[0], r[1])
\""
```

**Шаг 3. Перезалить.**

```bash
cd /opt/ir-storyboard
docker compose stop backend                       # чтобы файл не был открыт
docker exec ir-storyboard-backend-1 true 2>/dev/null || \
  docker compose run --rm -T -v storyboard-data:/data backend \
    sh -c "gunzip -c /dev/stdin > /data/matrix.db && chmod 644 /data/matrix.db" \
    < /opt/ir-storyboard/backups/<файл>.db.gz
docker compose start backend
```

Если снапшот лежит **внутри** volume (`/app/data/backups/_full/`), проще без
перекачки наружу:

```bash
docker compose stop backend
docker compose run --rm -T -v storyboard-data:/data backend \
  sh -c "gunzip -c /data/backups/_full/<файл>.db.gz > /data/matrix.db && chmod 644 /data/matrix.db"
docker compose start backend
```

**Шаг 4. Домигрировать схему и проверить.**

Снапшот мог быть снят на более старой схеме. Миграция идемпотентна, гонять её
безопасно и нужно:

```bash
docker exec ir-storyboard-backend-1 python3 -c \
  "from ir_storyboard import db; db.init_schema(db.connect('/app/data/matrix.db'))"
curl -fsS http://172.17.0.1:80/            # health, должен быть 200
```

> **Не пугайтесь старой схемы.** Если проверять базу «голым» `db.connect()` без
> `init_schema`, вы увидите доотмигрированное состояние и решите, что всё сломано.
> В работе схему добирает `get_conn` (`backend/deps.py`) на **каждом** запросе к
> `/api` — новые колонки доезжают при первом же обращении.

> **`401` на `/api` — это норма, а не поломка.** Прод закрыт не Basic Auth (его
> нигде нет), а собственным гейтом приложения: middleware `_auth_gate` в
> `backend/main.py` требует сессионную куку `ir_session`, выданную через
> Telegram-шлюз (`AUTHGW_URL` + `SESSION_SECRET`, подпись проверяется локально).
> Открыты только `/` (health Caddy), `/api/health` и `/api/auth/*`. Поэтому
> `curl -u логин:пароль` бесполезен — проверять живость нужно health'ом, а
> данные смотреть изнутри контейнера или в браузере с логином.

**Шаг 5.** Убедиться глазами в интерфейсе: клиент на месте, счётчики фактов
совпадают с ожиданием, вкладка «Проверка фактов» открывается.

Убедились — удалить страховку шага 0:
`docker exec ir-storyboard-backend-1 rm -f /app/data/before-restore.db`.

---

## Сценарий B. Пострадал один клиент, остальных трогать нельзя

Для этого есть пер-клиентское восстановление — оно затрагивает только своего
клиента и не откатывает работу коллег по другим компаниям.

**Обычный путь — в интерфейсе.** Компания → карандаш (редактирование) → блок
`Danger zone` → список «Бэкапы» → «Восстановить» → «Точно?». Список показывается,
только если бэкапы у клиента есть (их создаёт автоматика перед очисткой данных);
рядом с каждым — дата и сколько в нём фактов и строк.

**Если интерфейс недоступен** — то же самое изнутри контейнера. Ходить в `/api`
curl'ом не выйдет: гейт требует сессионную куку (см. врезку ниже), логина/пароля
у API нет.

```bash
docker exec ir-storyboard-backend-1 python3 - <<'PY'
from pathlib import Path
from ir_storyboard import db, backup

CLIENT = '<client_id>'
BACKUPS = Path('/app/data/backups')

# 1) что есть — сначала посмотреть, потом восстанавливать
for b in backup.list_backups(CLIENT, BACKUPS):
    print(b['id'], b['created_at'], b['counts'])
PY
```

Выбрали `id` — восстанавливаем (`restore_client` работает в одной транзакции и
сам коммитит; ошибка = полный откат):

```bash
docker exec ir-storyboard-backend-1 python3 - <<'PY'
from pathlib import Path
from ir_storyboard import db, backup

CLIENT, BACKUP_ID = '<client_id>', '<id из списка выше>'
conn = db.connect('/app/data/matrix.db'); db.init_schema(conn)
snap = backup.read_backup(CLIENT, BACKUP_ID, Path('/app/data/backups'))
assert snap, 'бэкап не найден'
print(backup.restore_client(conn, CLIENT, snap))
PY
```

**Что при этом происходит — важно понимать до нажатия.** `restore_client` сначала
**вычищает текущие данные клиента** и только потом проигрывает снапшот, причём
дополнительного бэкапа перед этим НЕ делает. Всё, что аналитики собрали по этому
клиенту после снятия снапшота, будет потеряно. Если такая работа была — сначала
снимите полный снапшот (шаг 0 сценария A).

Автоинкрементные id при восстановлении **не сохраняются**: строки вставляются
заново, а внешние ключи (`cells.id` → `facts.cell_id`, `sources.id` →
`facts.source_id`, `plans.id` → `narrative_tracks.plan_id`) перешиваются на новые.
Поэтому прямые ссылки на факт по числовому id, сохранённые где-то снаружи, после
восстановления укажут не туда. Внутри системы всё связно.

---

## Сценарий C. Сервера нет — поднимаем с нуля

**Шаг 1. Найти файл базы.** Без него это не восстановление, а установка с чистого
листа (`DEPLOY.md`). Порядок поиска — от внешней копии к локальным:

```bash
# 1) ОБЛАКО — единственное, что переживает потерю машины
rclone copy yandex:prod-backups/ir-storyboard ./restore --include "*-<ДАТА>-*"

# 2) если машина жива (авария не в железе) — копии оркестратора там же
ls -lt /opt/conductor-orchestrator/backups/ir-storyboard/
ls -lt /opt/conductor-orchestrator/backups/ir-storyboard/weekly/

# 3) и локальные копии самого приложения
ls -lt /opt/ir-storyboard/backups/
docker exec ir-storyboard-backend-1 ls -lt /app/data/backups/_full/
```

Пункты 2 и 3 живут на `216.57.108.107` — если сценарий C настоящий (машины нет),
работает только пункт 1.

Нужны оба файла за дату: `…-db.sqlite.gz` (база) и `…-files.tar.gz` (аудио и
загруженные отчёты). Без второго система поднимется, но исходники прошлых
разборов пропадут.

**Шаг 2. Подготовить машину** — Docker + Docker Compose plugin, открытые 80/443,
DNS на новый IP. Подробности — `DEPLOY.md`, части 2.4–2.6.

**Шаг 3. Код.**

```bash
git clone https://github.com/dechernov-stack/ir-storyboard.git /opt/ir-storyboard
cd /opt/ir-storyboard
```

Ветка по умолчанию (`main`) актуальна и совпадает с `feat/v2`, с которой идёт
деплой.

**Шаг 4. Восстановить `.env`.** Его нет ни в git, ни в бэкапе базы — берите из
менеджера секретов или заводите ключи заново по `.env.example`. Минимум, без
которого система работает неправильно, а не «не работает» (и это хуже):
`ANTHROPIC_API_KEY`, `TAVILY_API_KEY`, `SESSION_SECRET`, `IR_ADMIN_TIDS`,
`AUTHGW_URL`, `DOMAIN`, `ADMIN_EMAIL`.

> Без `ANTHROPIC_API_KEY` система поднимется и будет выглядеть исправной, но весь
> LLM-слой молча уйдёт в детерминистские стабы — разбор материалов будет давать
> мусор. Проверяйте ключи до того, как пускать аналитиков.

**Шаг 5. Поднять стек и залить базу.**

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env up -d --build
docker compose stop backend

# база
gunzip -c ir-storyboard-<ДАТА>-db.sqlite.gz | docker compose run --rm -T \
  -v storyboard-data:/data backend sh -c "cat > /data/matrix.db && chmod 644 /data/matrix.db"

# файлы volume (аудио, загруженные отчёты) — распаковать поверх
docker run --rm -v ir-storyboard_storyboard-data:/data -v "$PWD":/bk alpine \
  sh -c 'cd /data && tar xzf /bk/ir-storyboard-<ДАТА>-files.tar.gz'

docker compose start backend
```

**Шаг 6. Домигрировать и проверить** — как в шаге 4 сценария A, плюс:

```bash
docker compose ps                       # backend, frontend, caddy — все Up
docker compose logs caddy | tail -30    # "certificate obtained successfully"
```

**Шаг 7. Восстановить обвязку**, которой в бэкапе базы нет:

- **вернуть проект в ночной бэкап.** `backup_prod` снимает копию через локальный
  `docker exec ir-storyboard-backend-1` — это работает, только пока приложение и
  оркестратор на одной машине. Если подняли на новой: либо поднимать оркестратор
  рядом, либо заводить снятие по SSH, как сделано для vitalis (узкий ключ с
  `command=` в `authorized_keys`) — шаг в `scripts/backup_prod.sh` оркестратора.
  Плюс поправить серверы в паспорте проекта: расхождение с реестром роняет
  `verify_coverage`, и это правильно — молчащий бэкап хуже красного;
- если включали автообход мониторинга — `MONITORING_INTERVAL_MIN` в `.env`
  (по умолчанию выключен, это осознанно);
- локальный cron `scripts/backup.sh` (см. `DEPLOY.md`, 4.2) — опционален: это
  дубль ночного бэкапа оркестратора на той же машине.

---

## Если бэкапа нет вообще

Быстро проверьте, не остались ли копии в неочевидных местах:

```bash
docker volume ls | grep storyboard                       # volume мог пережить контейнеры
docker exec ir-storyboard-backend-1 ls /app/data/backups/_full/
ls /opt/ir-storyboard/backups/
docker exec ir-storyboard-backend-1 ls /app/data/*.bak-* # ручные страховки прошлых сессий
```

Volume переживает `docker compose down` — уносит его только `down -v` или удаление
вручную. Если volume цел, база цела, даже когда контейнеров нет.

---

## Проверка готовности (делать до аварии, а не после)

Бэкап, который никогда не восстанавливали, бэкапом не является. Раз в квартал:

1. Взять **внешнюю** копию (`/opt/conductor-orchestrator/backups/ir-storyboard/`
   или из облака) и развернуть её **локально**, не на проде:
   ```bash
   gunzip -c ir-storyboard-<ДАТА>-db.sqlite.gz > /tmp/restore-drill.db
   .venv/bin/python -c "from ir_storyboard import db; db.init_schema(db.connect('/tmp/restore-drill.db'))"
   ./scripts/check_migration.sh /tmp/restore-drill.db
   ```
   `check_migration.sh` прогоняет миграцию на копии и проверяет, что факты на месте.
   Учение именно с внешней копии, а не с `_full/` внутри volume: проверяем ту,
   которая переживёт потерю сервера.
2. Посмотреть лог последнего ночного `backup_prod`: строка про облако должна быть
   успешной, а не `CLOUD: WARN … ПРОПУЩЕН`. `WARN` означает, что все копии лежат
   на одном боксе — тогда залить `secrets/rclone.conf` (инструкция — «Настройка
   облака» в `docs/backup.md` оркестратора).
3. Проверить, что `.env` лежит в менеджере секретов и его содержимое актуально.

---

## Что проверено, а что нет

Честный список — здесь догадки опаснее пробелов.

**Проверено 2026-08-30** (по репозиторию оркестратора и коду проекта):

- **Прод заведён в ежедневный бэкап оркестратора.** Строка в
  `deploy/backup/sqlite-targets.txt`, состояние `active` в
  `expected-projects.txt`, отсутствие свежей копии роняет прогон
  (`verify_coverage`). Раньше здесь стояло «не подтверждено» — подтверждено.
- **Никакого Basic Auth на `/api` нет.** `401` даёт собственный гейт приложения
  (`_auth_gate` → кука `ir_session` от Telegram-шлюза). Прошлый вывод «серверный
  `Caddyfile` расходится с репозиторным» был ошибкой диагноза: 401 приняли за
  ответ Caddy. Расхождения нет и возвращать в git нечего — тем более что
  `Caddyfile` монтируется в контейнер прямо из рабочей копии
  (`./Caddyfile:/etc/caddy/Caddyfile:ro`), а деплой делает `reset --hard`, так что
  ручная правка на сервере не пережила бы ближайший деплой в любом случае.

**Не проверено — нужен доступ на сервер:**

- **Реально ли уезжают копии в облако** (есть ли `secrets/rclone.conf` на боксе
  оркестратора). Механика проверена на проде, но факт заливки конфига — нет.
  Пока его нет, «внешний» бэкап внешний только относительно контейнера, но не
  относительно машины. Это главный открытый риск этого документа.
- **Стоит ли на сервере cron с `scripts/backup.sh`.** После заведения ночного
  бэкапа оркестратора это дубль, а не необходимость.
- **Само учение по восстановлению ни разу не проводилось** — ни один из трёх
  сценариев выше не прогонялся на живой копии. У соседних проектов такие учения
  есть (vitalis, medmodel-lab — 2026-08-12), у этого нет.

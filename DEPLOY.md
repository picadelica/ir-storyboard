# Перенос в Git и развёртывание на VPS

Runbook для Claude Code в терминале. Можно скармливать целиком или по частям.

Контекст: проект уже собран в `/Users/dmitriychernov/Documents/Claude/Projects/For Jack/ir-storyboard/`. Бэкенд (FastAPI) и фронт (React + nginx) живут в одном репозитории, разворачиваются через docker-compose. Production-стек добавляет Caddy для HTTPS с автоматическим Let's Encrypt-сертификатом.

---

## Часть 1. Перенос в Git

### 1.1 Проверить локальный проект

```bash
cd "/Users/dmitriychernov/Documents/Claude/Projects/For Jack/ir-storyboard"
ls -la
# должны быть: README.md DEPLOY.md ir_storyboard/ backend/ frontend/
#              schema.sql docker-compose.yml docker-compose.prod.yml
#              Caddyfile .gitignore .env.example scripts/
```

Если чего-то нет — это значит, что v1 не полностью собрался; не продолжать, разобраться.

### 1.2 Инициализировать репозиторий

```bash
git init
git branch -M main
git add .
git status   # ВНИМАНИЕ: проверь что нет .env, data/, frontend/node_modules/, backups/
git commit -m "Initial commit: IR Storyboard MVP

- 8-layer narrative matrix on SQLite
- 4 ingestion channels (offline/online interview, archival, online research)
- 3 cycles (weekly, event, quarterly)
- FastAPI backend + React frontend
- Docker compose with optional Caddy/HTTPS for production"
```

Если `git status` показал ненужные файлы — это баг в `.gitignore`, надо исправить ДО первого коммита.

### 1.3 Создать удалённый репозиторий

Вариант А — GitHub через CLI:
```bash
gh auth status                      # убедиться что залогинен
gh repo create ir-storyboard --private --source=. --remote=origin --push
```

Вариант Б — GitHub вручную:
- Создать пустой private repo `ir-storyboard` на github.com.
- Вернуться в терминал:
```bash
git remote add origin git@github.com:<your-org>/ir-storyboard.git
git push -u origin main
```

Вариант В — самостоятельный Gitea/Forgejo (если IR-агентство хочет держать код у себя):
```bash
git remote add origin git@gitea.your-agency.com:ir/ir-storyboard.git
git push -u origin main
```

### 1.4 Проверить, что в репозитории нет лишнего

```bash
gh repo view --web   # или просто открыть страницу репо
```

В корне должны быть `README.md DEPLOY.md backend/ frontend/ ir_storyboard/ docker-compose.yml ...`. НЕ должно быть `data/`, `node_modules/`, `.env`, `dist/`, `outputs/`, `backups/`, `__pycache__`.

---

## Часть 2. Подготовка VPS

### 2.1 Требования

- Ubuntu 22.04+ или Debian 12+
- 2 vCPU / 2 GB RAM минимум (4 GB рекомендуется)
- 20 GB SSD
- Открытые порты: 22 (SSH), 80 (HTTP), 443 (HTTPS)
- Домен (например `ir.your-agency.com`) с A-записью на IP сервера — ДО запуска Caddy, иначе Let's Encrypt не выдаст сертификат

### 2.2 Первый вход + создать рабочего пользователя

```bash
ssh root@<vps-ip>

# создаём отдельного пользователя для приложения
adduser --disabled-password --gecos "" deploy
usermod -aG sudo deploy

# копируем SSH-ключи root → deploy
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

# разрешить sudo без пароля (опционально, удобно для деплоя)
echo "deploy ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/deploy
chmod 440 /etc/sudoers.d/deploy

# проверить логин
exit
ssh deploy@<vps-ip>     # должно работать без пароля
```

### 2.3 Опционально: запретить root-логин по SSH

```bash
sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```

### 2.4 Установить Docker + Docker Compose plugin

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
# нужно выйти и зайти заново, чтобы группа применилась
exit
ssh deploy@<vps-ip>

# проверить
docker version
docker compose version
docker run --rm hello-world
```

### 2.5 Включить firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80
sudo ufw allow 443
sudo ufw --force enable
sudo ufw status
```

### 2.6 Настроить DNS

В DNS-зоне домена создать **A-запись**: `ir` (или какой выбрали поддомен) → IP сервера. TTL 300.

Подождать распространения и проверить:
```bash
dig +short ir.your-agency.com
# должен вернуться IP VPS
```

Без правильного DNS Caddy не сможет выпустить сертификат и стек подвиснет.

---

## Часть 3. Развёртывание

### 3.1 Клонировать репозиторий

```bash
cd ~
git clone git@github.com:<your-org>/ir-storyboard.git
# или через https если SSH-ключи на VPS не настроены:
# git clone https://github.com/<your-org>/ir-storyboard.git
cd ir-storyboard
```

### 3.2 Настроить .env

```bash
cp .env.example .env
nano .env
```

Заполнить минимум `DOMAIN` и `ADMIN_EMAIL`:
```
DOMAIN=ir.your-agency.com
ADMIN_EMAIL=admin@your-agency.com
```

### 3.3 Поднять production-стек

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env up -d --build
```

Первый запуск ~3–5 минут (сборка фронта в Node, поднятие FastAPI, выпуск TLS-сертификата).

Проверить, что все три контейнера живы:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
# должны быть Up: backend, frontend, caddy
```

Посмотреть логи Caddy на предмет получения сертификата:
```bash
docker compose logs caddy | tail -40
# успех = "certificate obtained successfully" / "served key authentication"
```

### 3.4 Smoke-test

```bash
curl -fsSL https://ir.your-agency.com/api/health
# {"ok":true}

curl -fsS https://ir.your-agency.com/api/layers | head -c 200
# JSON с 8 слоями
```

Открыть в браузере `https://ir.your-agency.com/` — должен открыться UI с пустым состоянием и кнопкой «Загрузить пилот (Accumulator)».

### 3.5 Засеять Accumulator (опционально, для демо)

Через UI: нажать «+ Загрузить пилот (Accumulator)» в сайдбаре.

Или через API:
```bash
curl -X POST https://ir.your-agency.com/api/clients/accumulator/seed-accumulator \
     -H "Content-Type: application/json" -d '{}'
```

---

## Часть 4. Эксплуатация

### 4.1 Алиас docker compose-команды

Чтобы не печатать длинную строку каждый раз:
```bash
# в ~/.bashrc на сервере
alias dcp='docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env'
```
Перелогиниться или `source ~/.bashrc`.

Дальше команды короче: `dcp ps`, `dcp logs -f backend`, и т.д.

### 4.2 Бэкапы

Структура: `scripts/backup.sh` снимает консистентный snapshot SQLite (через online-backup API) внутри контейнера, gzip-ит, кладёт в `./backups/`. Хранит последние 30.

Ручной бэкап:
```bash
cd ~/ir-storyboard
./scripts/backup.sh
# Backup written: backups/storyboard-20260506T093000Z.db.gz (51234 bytes)
```

Cron — раз в сутки в 03:00 UTC:
```bash
crontab -e
```
Добавить:
```cron
0 3 * * * cd /home/deploy/ir-storyboard && ./scripts/backup.sh >> /home/deploy/backup.log 2>&1
```

Желательно также синхронизировать `backups/` куда-то наружу (S3 / rsync на отдельный сервер). Минимум:
```bash
# пример: ежедневный rsync на запасной хост
0 4 * * * rsync -az --delete /home/deploy/ir-storyboard/backups/ backup@offsite.example.com:/srv/ir-storyboard-backups/
```

### 4.3 Восстановление

```bash
ls -1t backups/                                # список снапшотов
./scripts/restore.sh backups/storyboard-20260506T030000Z.db.gz
# подтвердить Enter
```

Скрипт остановит backend, перезальёт `matrix.db` в volume, поднимет backend обратно. Проверить:
```bash
curl -fsS https://ir.your-agency.com/api/clients
```

### 4.4 Обновление до новой версии

```bash
cd ~/ir-storyboard
./scripts/backup.sh                            # сначала бэкап!
./scripts/check_migration.sh                   # проверить безопасность схемы
git pull
dcp up -d --build                              # пересоберёт изменившиеся образы
dcp ps                                         # проверить что всё Up
```

**Про миграции схемы:** все изменения БД реализованы через идемпотентные `ALTER TABLE IF NOT EXISTS` в `ir_storyboard/db.py::init_schema`. Они применяются автоматически при первом запросе к API — без downtime и без Alembic. `check_migration.sh` копирует текущую БД во временный файл, прогоняет `init_schema` и проверяет что все факты на месте.

Если что-то сломалось — откат:
```bash
git log --oneline -10                          # выбрать предыдущий рабочий commit
git checkout <commit-sha>
dcp up -d --build
```

### 4.5 Логи и мониторинг

```bash
dcp logs -f backend         # API
dcp logs -f frontend        # nginx access logs
dcp logs -f caddy           # TLS, HTTP requests, ошибки сертификатов
```

Базовая нагрузка:
```bash
docker stats --no-stream
df -h /                     # место на диске
```

### 4.6 Перевыпуск TLS-сертификата

Caddy продлевает сам автоматически. Если что-то сломалось:
```bash
dcp restart caddy
dcp logs caddy | tail -50
```

Если меняли домен — пересоздать сертификат:
```bash
dcp down
docker volume rm ir-storyboard_caddy-data ir-storyboard_caddy-config
# обновить DOMAIN в .env
dcp up -d --build
```

---

## Чек-лист готовности перед сдачей агентству

Прогнать каждый пункт явно, не пропускать.

**Git:**
- [ ] `.env` НЕ в репозитории (только `.env.example`)
- [ ] `data/`, `node_modules/`, `dist/`, `backups/` в `.gitignore` и не закоммичены
- [ ] `README.md` и `DEPLOY.md` есть в корне
- [ ] Репозиторий приватный

**VPS:**
- [ ] Пользователь `deploy` создан, root-логин выключен
- [ ] Docker + Docker Compose установлены, `docker run hello-world` отрабатывает
- [ ] UFW включён: 22, 80, 443
- [ ] DNS A-запись настроена и распространилась (`dig +short`)

**Развёртывание:**
- [ ] `.env` заполнен (DOMAIN, ADMIN_EMAIL)
- [ ] `dcp ps` показывает три Up контейнера
- [ ] Caddy выпустил сертификат (`certificate obtained` в логах)
- [ ] `curl https://<domain>/api/health` возвращает 200
- [ ] UI открывается в браузере, кнопка пилота работает
- [ ] После загрузки Accumulator: матрица отрисована, циклы запускаются, выходные артефакты появляются

**Эксплуатация:**
- [ ] `./scripts/backup.sh` отработал хотя бы один раз вручную
- [ ] Cron-задача поставлена и проверена (`grep CRON /var/log/syslog` после ближайшего запуска)
- [ ] Опциональный offsite-бэкап настроен
- [ ] Документация передана агентству вместе с домен/SSH-доступом

---

---

## YouTube Ingest — операционные требования

### Новые переменные окружения (.env)

```
# YouTube Ingest
TRANSCRIBER=local-faster-whisper          # дефолт; или openai-whisper-1, deepgram-nova-3
FASTER_WHISPER_MODEL=large-v3-turbo       # или large-v3 (точнее, в 2× медленнее)
FASTER_WHISPER_COMPUTE_TYPE=int8          # int8_float16 для GPU; int8 для CPU
FASTER_WHISPER_DEVICE=auto                # cpu / cuda / auto
FASTER_WHISPER_MODEL_DIR=/data/whisper    # volume mount — модель скачивается при первом запуске
TRANSCRIBE_PARALLEL_CHUNKS=1             # 2+ для параллелизации >2h видео (замерить сначала)
MAX_CHUNK_SEC=3600                        # 60-минутные куски (ffmpeg); менять не нужно
CHUNK_OVERLAP_SEC=5                       # overlap между кусками (s)
OPENAI_API_KEY=                           # опционально — для TRANSCRIBER=openai-whisper-1
DEEPGRAM_API_KEY=                         # опционально — для TRANSCRIBER=deepgram-nova-3
```

### Инфраструктурные требования

**ffmpeg в backend Dockerfile:**
```dockerfile
RUN apt-get update && apt-get install -y ffmpeg
```

**Volume для весов faster-whisper (~1.6 GB) в docker-compose.yml:**
```yaml
services:
  backend:
    volumes:
      - whisper-models:/data/whisper

volumes:
  whisper-models:
```
Модель скачивается lazy при первом ingest-запросе (~60 сек на первый cold start).
После рестарта контейнера веса остаются в volume.

**nginx proxy_read_timeout ≥ 1800s** (уже настроен для LLM ingest).
Worst-case: 2-часовое видео на CPU — ~80 мин wall-clock.

### Операционный профиль (без внешних API)

| Ресурс | Пик | Комментарий |
|--------|-----|-------------|
| CPU    | ~100% | faster-whisper использует все ядра во время транскрипции |
| RAM    | ~4 GB | модель + pipeline |
| Disk   | ~2 GB | модель в volume; до ~50 MB на аудио-файл в /tmp |
| Network | ~30 MB/час | только скачивание аудио (yt-dlp) |
| Стоимость | $0 | только электричество сервера |

### Emergency mode (OpenAI Whisper API)

Если capacity сервера не хватает (CPU < 4 ядер / RAM < 4 GB):
```
TRANSCRIBER=openai-whisper-1
OPENAI_API_KEY=sk-...
```
Стоимость: ~$0.006/мин, ~$0.36/час аудио. Wall-clock: ~5–10 мин.
Данные клиента передаются в OpenAI — учитывать при NDA.

### Проверка после деплоя

```bash
# Проверить что ffmpeg доступен
docker compose exec backend ffmpeg -version | head -1

# Проверить volume
docker volume inspect ir-storyboard_whisper-models

# Тест endpoint (должен вернуть [])
curl -s https://<domain>/api/clients/accumulator/ingest/youtube/history
```

---

## Известные ограничения v1

- Нет авторизации. Доступ к UI и API — у любого, кто знает домен. Если нужно ограничить — поставить Basic Auth в Caddy или базовый IP-allowlist:
  ```
  {$DOMAIN} {
      @allowed remote_ip 1.2.3.0/24 4.5.6.7
      handle @allowed { reverse_proxy frontend:80 }
      respond 403
  }
  ```
- SQLite — single-writer. На объёмах пилота (1–20 клиентов, ~25 ячеек × 30–100 фактов = до 50 000 строк) это нормально. Когда упрётесь в производительность — миграция на Postgres правится в `ir_storyboard/db.py` без изменения остальной логики.
- Нет audit log диффов. История изменений хранится через `captured_at` факта; видно, что когда добавили, но не «было/стало».
- Все аналитики работают в одном пространстве. Конкурентное редактирование одной ячейки — last-write-wins.

Эти ограничения снимаются поверх архитектуры по мере необходимости, не ломая v1.

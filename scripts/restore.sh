#!/usr/bin/env bash
# Restore the SQLite DB from a gzipped backup.
# Usage: ./scripts/restore.sh backups/storyboard-20260506T030000Z.db.gz
#        ./scripts/restore.sh /opt/conductor-orchestrator/backups/ir-storyboard/ir-storyboard-2026-08-30-db.sqlite.gz
# Полный runbook (три сценария аварии, откат одного клиента) — docs/restore.md.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ "${1:-}" = "" ]; then
  echo "Usage: $0 <backup.db.gz>"
  echo
  echo "Доступные копии:"
  echo "  ночные, оркестратора (свежайшие; на этой же машине):"
  ls -1t /opt/conductor-orchestrator/backups/ir-storyboard/*-db.sqlite.gz 2>/dev/null \
    | head -10 | sed 's|^|    |' || true
  echo "  снятые этим репозиторием (scripts/backup.sh):"
  ls -1t backups/storyboard-*.db.gz 2>/dev/null | head -10 | sed 's|^|    |' || true
  echo "  автоматические, внутри volume (снимаются перед очисткой данных клиента):"
  docker compose exec -T backend ls -1t /app/data/backups/_full/ 2>/dev/null \
    | head -10 | sed 's|^|    /app/data/backups/_full/|' || true
  echo
  echo "Копию из volume сначала достать наружу:"
  echo '  docker compose exec -T backend cat /app/data/backups/_full/ФАЙЛ.db.gz > /tmp/ФАЙЛ.db.gz'
  exit 1
fi

BACKUP="$1"
if [ ! -f "$BACKUP" ]; then
  echo "ERROR: $BACKUP not found" >&2
  exit 1
fi

echo "About to restore from: $BACKUP"
echo "This will OVERWRITE the current matrix.db. Press Enter to continue, Ctrl-C to abort."
read -r _

# Stop backend so the DB file is not held open
docker compose stop backend

# Push the decompressed DB into the volume via a one-shot helper container.
#
# Пишем прямо в /app/data — том сервису подставляет сама конфигурация compose
# (storyboard-data:/app/data). Раньше здесь было `-v storyboard-data:/data`; это
# работало (Compose v2 разрешает короткое имя в том проекта, проверено 2026-09-01),
# но монтировало один и тот же том дважды по двум путям и держалось на неочевидном
# правиле разрешения имён. Явный путь надёжнее и читается однозначно.
gunzip -c "$BACKUP" | docker compose run --rm -T backend \
  sh -c "cat > /app/data/matrix.db && chmod 644 /app/data/matrix.db && echo restored"

# Снапшот мог быть снят на более старой схеме — домигрируем, пока backend ещё
# остановлен (миграция идемпотентна; в работе её добирает get_conn на каждом
# запросе к /api, но лучше сразу и без гонки со стартом контейнера).
docker compose run --rm -T backend python -c \
  "from ir_storyboard import db; db.init_schema(db.connect('/app/data/matrix.db')); print('schema ok')"

# Сколько всего доехало — чтобы не идти в интерфейс за первым же вопросом.
docker compose run --rm -T backend python -c \
  "from ir_storyboard import db; c = db.connect('/app/data/matrix.db'); print('фактов:', c.execute('SELECT COUNT(*) FROM facts').fetchone()[0], '| клиентов:', c.execute('SELECT COUNT(*) FROM clients').fetchone()[0])"

# Start backend back up
docker compose start backend

echo
echo "Restore complete."
echo "Здоровье:  curl -fsS http://172.17.0.1:80/"
echo "curl'ом /api не проверять — он закрыт сессионной кукой (Telegram-шлюз),"
echo "логина/пароля нет, 401 там нормальный ответ. Смотреть глазами в интерфейсе."

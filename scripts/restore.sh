#!/usr/bin/env bash
# Restore the SQLite DB from a gzipped backup.
# Usage: ./scripts/restore.sh backups/storyboard-20260506T030000Z.db.gz
set -euo pipefail

if [ "${1:-}" = "" ]; then
  echo "Usage: $0 <backup.db.gz>"
  echo "Available backups:"
  ls -1t backups/storyboard-*.db.gz 2>/dev/null | head -20 || echo "  (none)"
  exit 1
fi

BACKUP="$1"
if [ ! -f "$BACKUP" ]; then
  echo "ERROR: $BACKUP not found" >&2
  exit 1
fi

cd "$(dirname "$0")/.."

echo "About to restore from: $BACKUP"
echo "This will OVERWRITE the current matrix.db. Press Enter to continue, Ctrl-C to abort."
read -r _

# Stop backend so the DB file is not held open
docker compose stop backend

# Push the decompressed DB into the volume via a one-shot helper container.
gunzip -c "$BACKUP" | docker compose run --rm -T -v storyboard-data:/data backend \
  sh -c "cat > /data/matrix.db && chmod 644 /data/matrix.db && echo restored"

# Start backend back up
docker compose start backend

echo "Restore complete. Verify via: curl -fsS http://localhost/api/clients"

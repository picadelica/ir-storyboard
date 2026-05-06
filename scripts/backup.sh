#!/usr/bin/env bash
# Snapshot the SQLite-backed storyboard volume into ./backups/.
# Safe to run while containers are up — uses sqlite3's online .backup
# inside the backend container (atomic, doesn't lock writers for long).
set -euo pipefail

cd "$(dirname "$0")/.."

mkdir -p backups
TS=$(date -u +%Y%m%dT%H%M%SZ)
OUT="backups/storyboard-${TS}.db.gz"

# Run a python sqlite3 .backup() inside the backend container against the live DB.
# This produces a consistent snapshot regardless of in-flight writes
# (sqlite3 online backup API holds a read lock only while pages are copied).
docker compose exec -T backend python -c "
import sqlite3, sys
src = sqlite3.connect('/app/data/matrix.db')
dst = sqlite3.connect('/tmp/snapshot.db')
with dst:
    src.backup(dst)
src.close(); dst.close()
sys.stdout.buffer.write(open('/tmp/snapshot.db','rb').read())
" | gzip -9 > "${OUT}"

# Sanity check
SIZE=$(stat -c %s "${OUT}" 2>/dev/null || stat -f %z "${OUT}")
if [ "${SIZE:-0}" -lt 1024 ]; then
  echo "ERROR: backup file too small (${SIZE} bytes), backup likely failed" >&2
  rm -f "${OUT}"
  exit 1
fi

echo "Backup written: ${OUT} (${SIZE} bytes)"

# Keep only the last 30 backups
ls -1t backups/storyboard-*.db.gz 2>/dev/null | awk 'NR>30' | xargs -r rm --

echo "Retention applied (kept last 30)."

#!/bin/bash
# Migration safety check: copy staging DB, run init_schema, verify Accumulator facts intact.
# Run before each release that changes schema.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_SRC="${1:-$ROOT/data/matrix.db}"
DB_TMP="$(mktemp /tmp/matrix_check_XXXXXX.db)"

if [ ! -f "$DB_SRC" ]; then
  echo "ERROR: source DB not found at $DB_SRC" >&2
  exit 1
fi

echo "→ Copying $DB_SRC → $DB_TMP"
cp "$DB_SRC" "$DB_TMP"

echo "→ Running init_schema on copy..."
python3 - <<PYEOF
import sys
sys.path.insert(0, "$ROOT")
from ir_storyboard import db, matrix
conn = db.connect("$DB_TMP")
db.init_schema(conn)
matrix.seed_layers(conn)

# verify Accumulator facts intact
count = conn.execute(
    "SELECT COUNT(*) FROM facts f JOIN cells c ON c.id=f.cell_id WHERE c.client_id='accumulator'"
).fetchone()[0]
print(f"  Accumulator facts: {count}")
if count == 0:
    print("ERROR: Accumulator facts lost after migration!", file=sys.stderr)
    sys.exit(1)

# verify work_items table exists
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert "work_items" in tables, "work_items table missing"
print("  work_items table: OK")
print("  Migration safe. ✓")
PYEOF

rm -f "$DB_TMP"
echo "Done."

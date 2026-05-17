#!/bin/sh
set -eu

if [ "${MCP_SKIP_BOOTSTRAP:-0}" != "1" ] && [ "${1:-}" = "python3" ] && [ "${2:-}" = "/app/mcp/server.py" ]; then
    structure_count="$(
        python3 - <<'PY'
from storage import ensure_schema, open_db

conn = open_db()
try:
    ensure_schema(conn)
    row = conn.execute("SELECT COUNT(*) AS count FROM sections").fetchone()
    print(int(row["count"]) if row else 0)
finally:
    conn.close()
PY
    )"
    if [ "${structure_count:-0}" = "0" ]; then
        echo "Bootstrapping structure index..." >&2
        python3 /app/parser/indexer.py 1>&2
    fi

    if [ -d /app/docs ]; then
        docs_count="$(
            python3 - <<'PY'
from storage import open_db, ensure_schema

conn = open_db()
try:
    ensure_schema(conn)
    row = conn.execute("SELECT COUNT(*) AS count FROM docs").fetchone()
    print(int(row["count"]) if row else 0)
finally:
    conn.close()
PY
        )"
        if [ "${docs_count:-0}" = "0" ]; then
            echo "Bootstrapping docs index..." >&2
            python3 /app/docs_indexer.py /app/docs --reset 1>&2
        fi
    fi
fi

exec "$@"

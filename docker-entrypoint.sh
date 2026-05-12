#!/bin/sh
set -eu

if [ "${MCP_SKIP_BOOTSTRAP:-0}" != "1" ] && [ "${1:-}" = "python3" ] && [ "${2:-}" = "/app/mcp/server.py" ]; then
    if [ ! -f /app/data/db/index.db ]; then
        echo "Bootstrapping structure index..."
        python3 /app/parser/indexer.py
    fi
fi

exec "$@"

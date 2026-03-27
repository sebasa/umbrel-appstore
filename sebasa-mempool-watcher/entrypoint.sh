#!/bin/bash
set -e

echo "============================================"
echo " Mempool Bitcoin Watcher"
echo " Mempool : ${MEMPOOL_URL:-http://mempool_web_1:3000}"
echo " Web UI  : http://0.0.0.0:7890"
echo " DB      : ${DB_PATH:-/data/watcher.db}"
echo "============================================"

# Start the watcher daemon in background
python /app/watcher.py &
WATCHER_PID=$!

# Start the web UI (gunicorn)
cd /app && gunicorn \
    --bind 0.0.0.0:7890 \
    --workers 2 \
    --timeout 30 \
    --access-logfile - \
    --error-logfile - \
    web.app:app &
WEB_PID=$!

# Exit if either process dies
wait_any() {
    wait -n $WATCHER_PID $WEB_PID
    echo "[ERROR] A process exited unexpectedly. Shutting down..."
    kill $WATCHER_PID $WEB_PID 2>/dev/null || true
    exit 1
}

trap wait_any SIGTERM SIGINT
wait $WATCHER_PID $WEB_PID

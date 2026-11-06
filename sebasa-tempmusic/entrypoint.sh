#!/bin/sh
# yt-dlp y tidaler se rompen seguido: se actualizan en segundo plano en cada arranque.
( pip install -U --no-cache-dir "yt-dlp[default]" tidaler >/tmp/update.log 2>&1 || true ) &
# Un solo worker: el estado de los trabajos vive en memoria.
exec gunicorn -b 0.0.0.0:7893 -w 1 --threads 16 --timeout 0 server:app

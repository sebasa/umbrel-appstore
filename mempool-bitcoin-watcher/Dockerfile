FROM python:3.12-slim

LABEL org.opencontainers.image.title="Mempool Bitcoin Watcher"
LABEL org.opencontainers.image.description="Monitor Bitcoin addresses via WebSocket and fire IPN webhooks"
LABEL org.opencontainers.image.source="https://github.com/sebasa/mempool-bitcoin-watcher"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY watcher.py manage.py ./
COPY web/ ./web/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

RUN mkdir -p /data

VOLUME ["/data"]

ENV PYTHONUNBUFFERED=1

EXPOSE 7890

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7890/api/stats')" || exit 1

CMD ["/entrypoint.sh"]

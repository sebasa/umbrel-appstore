FROM python:3.13-slim

LABEL org.opencontainers.image.title="Temp Music"
LABEL org.opencontainers.image.description="Descarga música con yt-dlp, beatportdl y tidaler; borrado automático a las 24 h"
LABEL org.opencontainers.image.source="https://github.com/sebasa/umbrel-appstore"

ARG TARGETARCH
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates unzip \
 && rm -rf /var/lib/apt/lists/*

# tidaler = fork mantenido de tidal-dl-ng (el paquete original ya no está en PyPI)
RUN pip install --no-cache-dir flask gunicorn pyyaml mutagen "yt-dlp[default]" tidaler

COPY fetch-beatportdl.sh /tmp/fetch-beatportdl.sh
RUN sh /tmp/fetch-beatportdl.sh "${TARGETARCH}" && rm /tmp/fetch-beatportdl.sh

WORKDIR /app
COPY server.py entrypoint.sh ./
COPY static ./static
RUN chmod +x entrypoint.sh && mkdir -p /data

VOLUME ["/data"]
EXPOSE 7893

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -s -o /dev/null http://localhost:7893/login || exit 1

ENTRYPOINT ["./entrypoint.sh"]

# ─────────────────────────────────────────────────────────────
# Stage 1 — compila tu fork sebasa/blockparser 0.12.5 desde fuente
# (edition 2024 requiere Rust 1.85+). Compila para la arch nativa
# del builder, así que en una Pi sale binario ARM64 sin cross-compile.
# ─────────────────────────────────────────────────────────────
FROM rust:1.85-bookworm AS builder

ARG BLOCKPARSER_REPO=https://github.com/sebasa/blockparser.git
ARG BLOCKPARSER_TAG=0.12.5

RUN apt-get update && apt-get install -y --no-install-recommends \
        git pkg-config libssl-dev clang \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 --branch ${BLOCKPARSER_TAG} ${BLOCKPARSER_REPO} . \
    && cargo build --release \
    && strip target/release/rusty-blockparser

# ─────────────────────────────────────────────────────────────
# Stage 2 — runtime: Python + FastAPI + el binario compilado
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

# Binario del parser
COPY --from=builder /build/target/release/rusty-blockparser /usr/local/bin/rusty-blockparser

# App
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/

# /data  -> salidas persistentes (CSVs, copia del index, estado de jobs)
# /bitcoin -> data dir del nodo, montado read-only por docker-compose
ENV BLOCKPARSER_BIN=/usr/local/bin/rusty-blockparser \
    BITCOIN_DIR=/bitcoin \
    DATA_DIR=/data \
    PORT=7899

EXPOSE 7899
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7899"]

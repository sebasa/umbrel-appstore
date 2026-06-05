# Blockparser GUI (para Umbrel)

Interfaz web sobre [`sebasa/blockparser`](https://github.com/sebasa/blockparser) 0.12.5
para exportar datos crudos de tu Bitcoin Node de Umbrel a CSV.

Esta build incluye **solo los callbacks que entran en RAM en una Raspberry Pi de 8 GB
cargada** (`simplestats`, `opreturn`, `sigdump`, `csvdump`). Los de ~18 GB de RAM
(`unspentcsvdump`, `balances`) quedan deshabilitados a propósito.

## Cómo lee el nodo

No usa RPC: lee directamente los `blk*.dat` y el índice del data dir de Bitcoin,
montado read-only en `/bitcoin`. Para no chocar con el lock del LevelDB del índice
que mantiene `bitcoind`, la app arma una "vista" en `/data/_blocks_view` con
symlinks a los `.dat` (inmutables) y una **copia** del subdir `index/`. Así nunca
toca el nodo. La copia puede quedar 1-2 bloques atrás del tip; irrelevante para
exports históricos. Si querés consistencia perfecta hasta el tip, parás el nodo
antes de correr el job.

## Requisitos

- Bitcoin Node **sin pruning** (la app lo detecta y avisa si está pruned).
- Espacio en disco acorde al callback. `csvdump` completo = cientos de GiB:
  **usá siempre `-s/-e` para acotar el rango**.

## Build & test local

```bash
docker build -t blockparser-gui:1.0.0 .
# Probar fuera de Umbrel apuntando a un data dir de Bitcoin real:
docker run --rm -p 3000:3000 \
  -v $PWD/_data:/data \
  -v /ruta/a/bitcoin:/bitcoin:ro \
  blockparser-gui:1.0.0
# http://localhost:3000
```

## Instalar en tu app store

1. Copiá esta carpeta como `blockparser-gui/` en tu repo de apps.
2. En `docker-compose.yml`, confirmá la variable del data dir de Bitcoin
   (`APP_BITCOIN_DATA_DIR`); si tu versión no la expone, apuntá al path real
   `${UMBREL_ROOT}/app-data/bitcoin/data/bitcoin`.
3. Publicá la imagen con su digest multi-arch y reemplazá `build: .` por `image:`.

## Notas

- Un job a la vez (un parseo ya satura I/O/CPU de la Pi).
- Progreso en vivo por SSE parseando el stdout del binario.
- `simplestats` y `opreturn` no generan archivos: su salida queda en el log del job.

"""
Blockparser GUI — backend FastAPI.

Orquesta rusty-blockparser (fork sebasa/blockparser 0.12.5) sobre el data dir
del Bitcoin Node de Umbrel, montado read-only en /bitcoin.

Decisiones de diseño clave:

1) Solo callbacks livianos en RAM (Pi 8 GB cargada):
   simplestats, opreturn, sigdump, csvdump. Los de ~18 GB quedan fuera.

2) Lock del LevelDB del índice: bitcoind mantiene blocks/index abierto con
   lock exclusivo. En vez de tocar el nodo, armamos una "vista" en /data:
   symlinks a los blk*.dat reales (inmutables, read-only) + una COPIA del
   subdir index/. blockparser corre contra esa vista y nunca pelea el lock.
   Trade-off: la copia del índice puede quedar un par de bloques atrás del tip;
   irrelevante para exports históricos. Para consistencia total, parar el nodo.

3) Un job a la vez: un parseo ya satura I/O y CPU de una Pi.
"""

import asyncio
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────
BIN = os.environ.get("BLOCKPARSER_BIN", "/usr/local/bin/rusty-blockparser")
BITCOIN_DIR = Path(os.environ.get("BITCOIN_DIR", "/bitcoin"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
BLOCKS_DIR = BITCOIN_DIR / "blocks"
VIEW_DIR = DATA_DIR / "_blocks_view"          # vista con symlinks + copia del index
OUT_ROOT = DATA_DIR / "exports"               # salidas por job
STATE_FILE = DATA_DIR / "jobs.json"

OUT_ROOT.mkdir(parents=True, exist_ok=True)

# Callbacks habilitados en esta build. RAM aprox. medida por el upstream.
CALLBACKS = {
    "simplestats": {
        "label": "Estadísticas de la cadena",
        "desc": "Resumen: conteos por tipo de script, totales y promedios. No genera archivos (sale por log).",
        "ram_mb": 100, "produces_files": False,
    },
    "opreturn": {
        "label": "Datos OP_RETURN",
        "desc": "Payloads OP_RETURN representables como UTF-8. Salida por log.",
        "ram_mb": 100, "produces_files": False,
    },
    "sigdump": {
        "label": "Firmas ECDSA (sigdump)",
        "desc": "r, s, pubkey, txid, message_hash, block_time desde inputs P2PKH. Para análisis de nonces.",
        "ram_mb": 100, "produces_files": True,
    },
    "csvdump": {
        "label": "Export completo CSV (csvdump)",
        "desc": "blocks/transactions/tx_in/tx_out. ⚠️ Cientos de GiB en disco — usá rango acotado.",
        "ram_mb": 100, "produces_files": True,
    },
}

# ── Estado de jobs (en memoria + persistencia best-effort) ──────────────────
JOBS: dict[str, dict] = {}
_CURRENT_PROC: Optional[asyncio.subprocess.Process] = None
_LOCK = asyncio.Lock()

PROGRESS_RE = re.compile(
    r"Status:\s+(\d+)\s+Blocks processed.*remaining:\s+(\d+).*speed:\s+([\d.]+)"
)
DONE_RE = re.compile(r"Done\. Processed blocks up to height\s+(\d+)")


def _save_state():
    try:
        STATE_FILE.write_text(json.dumps(
            {k: {kk: vv for kk, vv in v.items() if kk != "log_tail"}
             for k, v in JOBS.items()}, default=str))
    except Exception:
        pass


def _load_state():
    if STATE_FILE.exists():
        try:
            for k, v in json.loads(STATE_FILE.read_text()).items():
                v.setdefault("log_tail", [])
                JOBS[k] = v
        except Exception:
            pass


# ── Chequeos del nodo ───────────────────────────────────────────────────────
def node_status() -> dict:
    """Detecta pruning y disponibilidad del data dir."""
    status = {"blocks_dir_ok": BLOCKS_DIR.is_dir(), "pruned": None, "free_gb": None}

    conf = BITCOIN_DIR / "bitcoin.conf"
    if conf.exists():
        try:
            for line in conf.read_text().splitlines():
                line = line.strip()
                if line.startswith("prune="):
                    val = int(line.split("=", 1)[1])
                    status["pruned"] = val > 0
                    status["prune_value"] = val
        except Exception:
            pass

    try:
        usage = shutil.disk_usage(DATA_DIR)
        status["free_gb"] = round(usage.free / 1e9, 1)
    except Exception:
        pass
    return status


def prepare_view() -> Path:
    """
    Arma /data/_blocks_view con:
      - symlinks a cada blk*.dat / rev*.dat de /bitcoin/blocks (read-only, inmutables)
      - copia real del subdir index/ (para no tocar el lock de bitcoind)
    Devuelve el path de la vista, que se pasa a `-d`.
    """
    if VIEW_DIR.exists():
        shutil.rmtree(VIEW_DIR, ignore_errors=True)
    VIEW_DIR.mkdir(parents=True)

    for f in BLOCKS_DIR.glob("*.dat"):
        (VIEW_DIR / f.name).symlink_to(f)

    src_index = BLOCKS_DIR / "index"
    if src_index.is_dir():
        # copytree sigue una snapshot; puede quedar 1-2 bloques atrás del tip.
        # LOCK y LOCK.bak los crea bitcoind; si los copiamos, blockparser falla
        # al intentar parsearlos como archivos LevelDB con número de tabla.
        shutil.copytree(
            src_index, VIEW_DIR / "index",
            ignore=shutil.ignore_patterns("LOCK", "LOCK.bak", "*.bak"),
        )
        # Belt-and-suspenders: remove any non-LevelDB files that slipped through
        # (e.g. LOCK.bak created by bitcoind mid-copy). LevelDB fails on these.
        dest_index = VIEW_DIR / "index"
        for name in ("LOCK", "LOCK.bak"):
            (dest_index / name).unlink(missing_ok=True)
        for p in dest_index.glob("*.bak"):
            p.unlink()
    return VIEW_DIR


# ── Ejecución de un job ──────────────────────────────────────────────────────
class NewJob(BaseModel):
    callback: str
    start: Optional[int] = None
    end: Optional[int] = None


async def run_job(job_id: str):
    global _CURRENT_PROC
    job = JOBS[job_id]
    cb = job["callback"]
    out_dir = OUT_ROOT / job_id
    out_dir.mkdir(parents=True, exist_ok=True)

    job["state"] = "preparing"
    job["log_tail"].append("Preparando vista del blockchain (symlinks + copia del index)…")
    _save_state()

    try:
        view = await asyncio.to_thread(prepare_view)
    except Exception as e:
        job["state"] = "error"
        job["error"] = f"No se pudo preparar la vista: {e}"
        _save_state()
        return

    cmd = [BIN, "-d", str(view), "-c", "bitcoin"]
    if job.get("start") is not None:
        cmd += ["-s", str(job["start"])]
    if job.get("end") is not None:
        cmd += ["-e", str(job["end"])]
    # subcomando + carpeta de salida (los callbacks con archivos la requieren)
    cmd.append(cb)
    if CALLBACKS[cb]["produces_files"]:
        cmd.append(str(out_dir))

    job["state"] = "running"
    job["cmd"] = " ".join(cmd)
    job["started_at"] = time.time()
    _save_state()

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    _CURRENT_PROC = proc

    assert proc.stdout
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").rstrip()
        job["log_tail"] = (job["log_tail"] + [line])[-200:]

        m = PROGRESS_RE.search(line)
        if m:
            done, remaining, speed = int(m[1]), int(m[2]), float(m[3])
            total = done + remaining
            job["progress"] = round(100 * done / total, 2) if total else 0
            job["speed"] = speed
            job["eta_min"] = round(remaining / speed / 60, 1) if speed else None
        if DONE_RE.search(line):
            job["progress"] = 100.0

    rc = await proc.wait()
    _CURRENT_PROC = None
    job["finished_at"] = time.time()

    if rc == 0:
        job["state"] = "done"
        files = []
        if CALLBACKS[cb]["produces_files"]:
            for p in sorted(out_dir.glob("*.csv")):
                files.append({"name": p.name, "size_mb": round(p.stat().st_size / 1e6, 2)})
        job["files"] = files
    elif job.get("state") == "cancelled":
        pass
    else:
        job["state"] = "error"
        job["error"] = f"blockparser terminó con código {rc}. Revisá el log."
    _save_state()


# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Blockparser GUI")
_load_state()


@app.get("/api/meta")
async def meta():
    return {"callbacks": CALLBACKS, "node": node_status()}


@app.get("/api/jobs")
async def list_jobs():
    return JSONResponse([
        {k: v for k, v in j.items() if k != "log_tail"} | {"id": jid}
        for jid, j in sorted(JOBS.items(), key=lambda x: x[1].get("created_at", 0), reverse=True)
    ])


@app.post("/api/jobs")
async def create_job(body: NewJob):
    if body.callback not in CALLBACKS:
        raise HTTPException(400, "Callback no habilitado en esta build.")
    ns = node_status()
    if ns.get("pruned"):
        raise HTTPException(409, "El nodo está en modo pruned; blockparser necesita la cadena completa.")
    if not ns.get("blocks_dir_ok"):
        raise HTTPException(409, "No se encuentra /bitcoin/blocks. Revisá el mount.")

    async with _LOCK:
        if any(j["state"] in ("preparing", "running") for j in JOBS.values()):
            raise HTTPException(409, "Ya hay un job en curso. Esperá a que termine (uno a la vez en la Pi).")
        jid = uuid.uuid4().hex[:8]
        JOBS[jid] = {
            "callback": body.callback, "start": body.start, "end": body.end,
            "state": "queued", "progress": 0.0, "speed": None, "eta_min": None,
            "created_at": time.time(), "log_tail": [], "files": [],
        }
        _save_state()
        asyncio.create_task(run_job(jid))
    return {"id": jid}


@app.post("/api/jobs/{jid}/cancel")
async def cancel_job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "Job inexistente.")
    JOBS[jid]["state"] = "cancelled"
    if _CURRENT_PROC and _CURRENT_PROC.returncode is None:
        _CURRENT_PROC.terminate()
    _save_state()
    return {"ok": True}


@app.get("/api/jobs/{jid}/events")
async def job_events(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "Job inexistente.")

    async def gen():
        last = None
        while True:
            j = JOBS.get(jid, {})
            payload = json.dumps({
                "state": j.get("state"), "progress": j.get("progress"),
                "speed": j.get("speed"), "eta_min": j.get("eta_min"),
                "log": j.get("log_tail", [])[-12:], "files": j.get("files", []),
                "error": j.get("error"),
            })
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if j.get("state") in ("done", "error", "cancelled"):
                break
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/jobs/{jid}/download/{name}")
async def download(jid: str, name: str):
    safe = Path(name).name
    fp = OUT_ROOT / jid / safe
    if not fp.exists():
        raise HTTPException(404, "Archivo inexistente.")
    return FileResponse(fp, filename=safe, media_type="text/csv")


# Frontend estático (montado al final para no pisar /api)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

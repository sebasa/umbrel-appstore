"""Temp Music: descarga música con yt-dlp / beatportdl / tidaler y la borra pasadas TTL_HOURS horas."""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import yaml
from flask import (Flask, abort, after_this_request, jsonify, redirect, request, send_file,
                   send_from_directory, session)

DATA = Path(os.environ.get("DATA_DIR", "/data"))
CONFIG = DATA / "config"
DOWNLOADS = DATA / "downloads"
INCOMING = DATA / "incoming"  # carpeta de trabajo de beatportdl
TTL = int(float(os.environ.get("TTL_HOURS", "24")) * 3600)
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL_JOBS", "2"))
JOB_TIMEOUT = 60 * 60
# Contraseña de acceso: la que Umbrel genera para la app (APP_PASSWORD) o una propia.
ACCESS_PASSWORD = os.environ.get("ACCESS_PASSWORD") or os.environ.get("APP_PASSWORD") or ""

YTDLP_CONF = CONFIG / "yt-dlp.conf"
BP_CONF = CONFIG / "beatportdl-config.yml"
BP_BIN = CONFIG / "beatportdl"  # copia local: beatportdl busca su config junto al binario
BP_BIN_SRC = Path("/opt/beatportdl/beatportdl")
TIDAL_DIR = CONFIG / "tidaler"  # tidaler usa $XDG_CONFIG_HOME/tidaler
TIDAL_CONF = TIDAL_DIR / "settings.json"
TIDAL_TOKEN = TIDAL_DIR / "token.json"
TIDAL_ENV = {**os.environ, "XDG_CONFIG_HOME": str(CONFIG), "HOME": str(DATA / "home"),
             "PYTHONUNBUFFERED": "1", "NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"}

META = "_job.json"
LOG = "_log.txt"
HIDDEN = {META, LOG}
MASK = "********"

DEFAULT_YTDLP = """\
# Config de yt-dlp (una opción por línea). Se aplica a todas las descargas que no son de Beatport/Tidal.
-x
--audio-format mp3
--audio-quality 0
--embed-thumbnail
--embed-metadata
--no-playlist
-o "%(artist,uploader)s - %(title)s.%(ext)s"
"""

DEFAULT_BP = """\
# Credenciales de Beatport (requiere suscripción con streaming)
username: ""
password: ""
quality: lossless        # medium-hls | medium | high | lossless (según tu suscripción)
sort_by_context: false
track_exists: skip
fix_tags: true
show_progress: false
# downloads_directory lo maneja la app (se ignora lo que pongas acá)
"""

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=30 * 24 * 3600, MAX_CONTENT_LENGTH=1024 * 1024)
pool = ThreadPoolExecutor(max_workers=MAX_PARALLEL)
bp_lock = threading.Lock()      # beatportdl comparte carpeta de salida: se serializa
tidal_lock = threading.Lock()   # tidaler lee download_base_path de un único settings.json
jobs_lock = threading.Lock()
running = set()


# ---------- utilidades ----------
def setup():
    for d in (CONFIG, DOWNLOADS, INCOMING, DATA / "home", TIDAL_DIR):
        d.mkdir(parents=True, exist_ok=True)
    if not YTDLP_CONF.exists():
        YTDLP_CONF.write_text(DEFAULT_YTDLP)
    if not BP_CONF.exists():
        BP_CONF.write_text(DEFAULT_BP)
    if BP_BIN_SRC.exists():
        shutil.copy2(BP_BIN_SRC, BP_BIN)
        BP_BIN.chmod(0o755)
    if not TIDAL_CONF.exists() and shutil.which("tidaler"):
        try:  # `tidaler cfg` genera settings.json con todos los valores por defecto
            subprocess.run(["tidaler", "cfg"], env=TIDAL_ENV, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=60)
            cfg = json.loads(TIDAL_CONF.read_text())
            cfg.update(video_download=False, quality_audio="LOSSLESS",
                       path_binary_ffmpeg=shutil.which("ffmpeg") or "")
            TIDAL_CONF.write_text(json.dumps(cfg, indent=2))
        except Exception as e:  # noqa: BLE001
            print("No pude inicializar la config de tidaler:", e, flush=True)
    # Clave de sesión estable entre reinicios
    key_file = CONFIG / ".secret_key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
        key_file.chmod(0o600)
    app.secret_key = key_file.read_text().strip()


def job_dir(job_id):
    if not re.fullmatch(r"[0-9a-f]{12}", job_id or ""):
        abort(404)
    p = DOWNLOADS / job_id
    if not p.is_dir():
        abort(404)
    return p


def read_meta(p):
    try:
        return json.loads((p / META).read_text())
    except Exception:
        return None


def write_meta(p, meta):
    tmp = p / (META + ".tmp")
    tmp.write_text(json.dumps(meta))
    tmp.replace(p / META)


def log(p, text):
    with open(p / LOG, "a", encoding="utf-8", errors="replace") as f:
        f.write(text if text.endswith("\n") else text + "\n")


def list_files(p):
    out = []
    for f in sorted(p.rglob("*")):
        if f.is_file() and f.name not in HIDDEN and not f.name.endswith(".tmp"):
            rel = f.relative_to(p).as_posix()
            out.append({"path": rel, "size": f.stat().st_size})
    return out


def detect_tool(url, choice):
    if choice in ("yt-dlp", "beatportdl", "tidal"):
        return choice
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("beatport.com") or host.endswith("beatsource.com"):
        return "beatportdl"
    if host == "tidal.com" or host.endswith(".tidal.com"):
        return "tidal"
    return "yt-dlp"


def stream(cmd, p, cwd=None, env=None):
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1,
    )
    timer = threading.Timer(JOB_TIMEOUT, proc.kill)
    timer.start()
    try:
        for line in proc.stdout:
            line = ANSI.sub("", line).replace("\r", "\n").strip()
            if line:
                log(p, line)
        return proc.wait()
    finally:
        timer.cancel()


def prepare_bp_config():
    cfg = yaml.safe_load(BP_CONF.read_text()) or {}
    if not isinstance(cfg, dict):
        raise ValueError("beatportdl-config.yml no es un mapa YAML válido")
    if not cfg.get("username") or not cfg.get("password"):
        raise ValueError("Falta username/password de Beatport en Ajustes")
    cfg["downloads_directory"] = str(INCOMING)
    cfg["show_progress"] = False
    BP_CONF.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))


def tidal_logged_in():
    """tidaler crea un token.json vacío ({}) aunque el login falle: hay sesión sólo con access_token."""
    try:
        return bool(json.loads(TIDAL_TOKEN.read_text()).get("access_token"))
    except Exception:
        return False


def prepare_tidal_config(dest):
    if not tidal_logged_in():
        raise ValueError("No hay sesión de Tidal: Ajustes → Iniciar sesión en Tidal")
    cfg = json.loads(TIDAL_CONF.read_text())
    cfg["download_base_path"] = str(dest)
    TIDAL_CONF.write_text(json.dumps(cfg, indent=2))


# ---------- ejecución de trabajos ----------
def run_job(job_id):
    p = DOWNLOADS / job_id
    meta = read_meta(p)
    meta["status"] = "running"
    write_meta(p, meta)
    url, tool = meta["url"], meta["tool"]
    try:
        if tool == "yt-dlp":
            cmd = ["yt-dlp", "--config-locations", str(YTDLP_CONF), "--newline",
                   "--no-colors", "-P", str(p), "--", url]
            log(p, "$ yt-dlp " + url)
            code = stream(cmd, p)
        elif tool == "tidal":
            with tidal_lock:
                prepare_tidal_config(p)
                log(p, "$ tidaler dl " + url)
                code = stream(["tidaler", "dl", url], p, cwd=str(p), env=TIDAL_ENV)
        else:
            with bp_lock:
                prepare_bp_config()
                shutil.rmtree(INCOMING, ignore_errors=True)
                INCOMING.mkdir(parents=True, exist_ok=True)
                log(p, "$ beatportdl " + url)
                code = stream([str(BP_BIN), url], p, cwd=str(CONFIG))
                for item in INCOMING.iterdir():
                    shutil.move(str(item), str(p / item.name))
        files = list_files(p)
        if code != 0:
            meta["status"], meta["error"] = "error", f"Código de salida {code}"
        elif not files:
            meta["status"], meta["error"] = "error", "Terminó sin generar archivos"
        else:
            meta["status"] = "done"
    except Exception as e:  # noqa: BLE001
        log(p, f"ERROR: {e}")
        meta["status"], meta["error"] = "error", str(e)
    meta["finished"] = int(time.time())
    write_meta(p, meta)
    with jobs_lock:
        running.discard(job_id)


def serialize(p):
    meta = read_meta(p)
    if not meta:
        return None
    meta["expires_at"] = meta["created"] + TTL
    meta["files"] = list_files(p)
    return meta


# ---------- limpieza ----------
def cleanup_once():
    now = time.time()
    for p in DOWNLOADS.iterdir():
        if not p.is_dir():
            continue
        with jobs_lock:
            if p.name in running:
                continue
        meta = read_meta(p)
        created = meta["created"] if meta else p.stat().st_mtime
        if now - created >= TTL:
            shutil.rmtree(p, ignore_errors=True)


def cleanup_loop():
    while True:
        try:
            cleanup_once()
        except Exception as e:  # noqa: BLE001
            print("cleanup error:", e, flush=True)
        time.sleep(300)


def recover_interrupted():
    """Trabajos que quedaron 'running' por un reinicio del contenedor."""
    for p in DOWNLOADS.iterdir():
        meta = read_meta(p) if p.is_dir() else None
        if meta and meta.get("status") in ("queued", "running"):
            meta["status"], meta["error"] = "error", "Interrumpido por reinicio"
            write_meta(p, meta)


# ---------- acceso (pensado para exponerla con un túnel de Cloudflare) ----------
LOGIN_HTML = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Temp Music</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f1115;color:#e8eaf0;font:15px system-ui,sans-serif}
form{background:#181b22;border:1px solid #2a2f3a;border-radius:12px;padding:24px;width:min(340px,92vw)}
h1{font-size:18px;margin:0 0 14px}input,button{width:100%;box-sizing:border-box;font:inherit;padding:10px;border-radius:8px;border:1px solid #2a2f3a;background:#0f1115;color:inherit}
button{margin-top:10px;background:#6c8cff;border:0;color:#fff;cursor:pointer}.e{color:#ff6b6b;font-size:13px;margin-top:8px;min-height:16px}</style></head>
<body><form method="post" action="/login"><h1>🎵 Temp Music</h1>
<input type="password" name="password" placeholder="Contraseña" autofocus required>
<button>Entrar</button><div class="e">__ERR__</div></form></body></html>"""

_fails = {}  # ip -> (cantidad, desbloqueo)


def client_ip():
    return (request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr or "?")


def check_password(candidate):
    a = hashlib.sha256(candidate.encode()).digest()
    b = hashlib.sha256(ACCESS_PASSWORD.encode()).digest()
    return hmac.compare_digest(a, b)


@app.before_request
def require_login():
    if request.path == "/login":
        return None
    if not ACCESS_PASSWORD:
        return ("Falta la contraseña de acceso (APP_PASSWORD / ACCESS_PASSWORD). "
                "La app queda bloqueada hasta configurarla.", 503)
    if session.get("ok"):
        return None
    if request.path.startswith(("/api/", "/files/")):
        return jsonify(error="No autenticado"), 401
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    if not ACCESS_PASSWORD:
        return ("Falta la contraseña de acceso (APP_PASSWORD / ACCESS_PASSWORD).", 503)
    err = ""
    if request.method == "POST":
        ip = client_ip()
        count, until = _fails.get(ip, (0, 0))
        if time.time() < until:
            err = "Demasiados intentos, esperá un momento."
        elif check_password(request.form.get("password", "")):
            _fails.pop(ip, None)
            session.clear()
            session.permanent = True
            session["ok"] = True
            return redirect("/")
        else:
            count += 1
            _fails[ip] = (count, time.time() + min(2 ** count, 900) if count >= 3 else 0)
            time.sleep(1)
            err = "Contraseña incorrecta."
    return LOGIN_HTML.replace("__ERR__", err), 401 if err else 200


@app.post("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------- rutas ----------
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.post("/api/jobs")
def create_job():
    body = request.get_json(silent=True) or {}
    urls = [u.strip() for u in re.split(r"[\s,]+", body.get("url", "")) if u.strip()]
    if not urls:
        return jsonify(error="Pegá al menos un link"), 400
    created = []
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return jsonify(error=f"Link inválido: {url}"), 400
    for url in urls:
        job_id = uuid.uuid4().hex[:12]
        p = DOWNLOADS / job_id
        p.mkdir(parents=True)
        meta = {"id": job_id, "url": url, "tool": detect_tool(url, body.get("tool", "auto")),
                "status": "queued", "created": int(time.time())}
        write_meta(p, meta)
        with jobs_lock:
            running.add(job_id)
        pool.submit(run_job, job_id)
        created.append(job_id)
    return jsonify(ids=created), 201


@app.get("/api/jobs")
def list_jobs():
    items = [s for p in DOWNLOADS.iterdir() if p.is_dir() and (s := serialize(p))]
    items.sort(key=lambda j: j["created"], reverse=True)
    return jsonify(jobs=items, ttl_seconds=TTL, now=int(time.time()))


@app.get("/api/jobs/<job_id>/log")
def job_log(job_id):
    p = job_dir(job_id)
    f = p / LOG
    text = f.read_text(errors="replace") if f.exists() else ""
    return jsonify(log=text[-20000:])


@app.delete("/api/jobs/<job_id>")
def delete_job(job_id):
    p = job_dir(job_id)
    with jobs_lock:
        if job_id in running:
            return jsonify(error="El trabajo sigue en curso"), 409
    shutil.rmtree(p, ignore_errors=True)
    return "", 204


@app.get("/files/<job_id>/<path:rel>")
def get_file(job_id, rel):
    p = job_dir(job_id)
    if Path(rel).name in HIDDEN:
        abort(404)
    return send_from_directory(p, rel, as_attachment=True)


@app.get("/api/jobs/<job_id>/zip")
def get_zip(job_id):
    p = job_dir(job_id)
    files = list_files(p)
    if not files:
        abort(404)
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_STORED) as z:
        for f in files:
            z.write(p / f["path"], f["path"])

    @after_this_request
    def _rm(resp):
        resp.call_on_close(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name))
        return resp

    return send_file(tmp.name, as_attachment=True, download_name=f"musica-{job_id}.zip")


# ---------- configuración ----------
CONFIGS = {"yt-dlp": YTDLP_CONF, "beatportdl": BP_CONF, "tidal": TIDAL_CONF}
PW_LINE = re.compile(r"^(\s*password\s*:\s*).*$", re.M)


def mask_secrets(name, text):
    """La contraseña de Beatport nunca sale del servidor una vez guardada."""
    if name == "beatportdl":
        return PW_LINE.sub(lambda m: f'{m.group(1)}"{MASK}"', text)
    return text


def restore_secrets(name, text):
    if name == "beatportdl":
        try:
            new_pw = (yaml.safe_load(text) or {}).get("password")
        except Exception:
            return text
        if new_pw == MASK:
            old_pw = (yaml.safe_load(BP_CONF.read_text()) or {}).get("password", "")
            return PW_LINE.sub(lambda m: f"{m.group(1)}{json.dumps(old_pw)}", text, count=1)
    return text


@app.get("/api/config/<name>")
def get_config(name):
    if name not in CONFIGS:
        abort(404)
    f = CONFIGS[name]
    return jsonify(content=mask_secrets(name, f.read_text() if f.exists() else ""))


@app.put("/api/config/<name>")
def put_config(name):
    if name not in CONFIGS:
        abort(404)
    content = (request.get_json(silent=True) or {}).get("content", "")
    try:
        if name == "beatportdl":
            if not isinstance(yaml.safe_load(content) or {}, dict):
                raise ValueError("debe ser un mapa YAML")
        elif name == "tidal":
            if not isinstance(json.loads(content), dict):
                raise ValueError("debe ser un objeto JSON")
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Formato inválido: {e}"), 400
    CONFIGS[name].write_text(restore_secrets(name, content))
    return jsonify(ok=True)


# ---------- login de Tidal (flujo PKCE: se abre un link y se pega la URL del "Oops") ----------
tidal_login = {"proc": None, "lines": [], "lock": threading.Lock()}


def _read_login(proc, lines):
    for line in proc.stdout:
        lines.append(ANSI.sub("", line).strip())


def _kill_login():
    proc = tidal_login["proc"]
    if proc and proc.poll() is None:
        proc.kill()
    tidal_login["proc"] = None


@app.get("/api/tidal/status")
def tidal_status():
    return jsonify(logged_in=tidal_logged_in())


@app.post("/api/tidal/login/start")
def tidal_login_start():
    with tidal_login["lock"]:
        _kill_login()
        proc = subprocess.Popen(["tidaler", "login"], env=TIDAL_ENV, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        lines = []
        tidal_login.update(proc=proc, lines=lines)
        threading.Thread(target=_read_login, args=(proc, lines), daemon=True).start()
        deadline = time.time() + 25
        while time.time() < deadline:
            url = next((l for l in lines if l.startswith("https://login.tidal.com/")), None)
            if url:
                return jsonify(url=url)
            if proc.poll() is not None:
                time.sleep(0.3)
                return jsonify(logged_in=tidal_logged_in(), output="\n".join(lines)[-500:])
            time.sleep(0.2)
        _kill_login()
        return jsonify(error="No pude obtener el link de login de Tidal"), 502


@app.post("/api/tidal/login/finish")
def tidal_login_finish():
    pasted = ((request.get_json(silent=True) or {}).get("url") or "").strip()
    if not pasted.startswith("https://tidal.com/") or "code=" not in pasted:
        return jsonify(error="Pegá la URL completa de la página 'Oops' (empieza con https://tidal.com/…code=…)"), 400
    with tidal_login["lock"]:
        proc = tidal_login["proc"]
        if not proc or proc.poll() is not None:
            return jsonify(error="Primero tocá «Iniciar sesión en Tidal»"), 409
        proc.stdin.write(pasted + "\n")
        proc.stdin.flush()
        try:
            proc.wait(timeout=45)
        except subprocess.TimeoutExpired:
            _kill_login()
            return jsonify(error="Tidal no respondió a tiempo"), 504
        out = "\n".join(tidal_login["lines"])[-500:]
        tidal_login["proc"] = None
        ok = tidal_logged_in()
        return jsonify(ok=ok, output=out), (200 if ok else 400)


@app.post("/api/tidal/logout")
def tidal_logout():
    subprocess.run(["tidaler", "logout"], env=TIDAL_ENV, stdin=subprocess.DEVNULL,
                   capture_output=True, timeout=60)
    TIDAL_TOKEN.unlink(missing_ok=True)
    return jsonify(ok=True)


@app.post("/api/update-ytdlp")
def update_ytdlp():
    r = subprocess.run(["pip", "install", "-U", "--no-cache-dir", "yt-dlp[default]"],
                       capture_output=True, text=True, timeout=300)
    v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True).stdout.strip()
    return jsonify(ok=r.returncode == 0, version=v, output=r.stdout[-500:] + r.stderr[-500:])


@app.get("/api/info")
def info():
    v = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True).stdout.strip()
    return jsonify(ytdlp=v, ttl_hours=TTL / 3600)


setup()
recover_interrupted()
threading.Thread(target=cleanup_loop, daemon=True).start()

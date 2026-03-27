#!/usr/bin/env python3
"""
Mempool Bitcoin Watcher — track-addresses + categorías
Cada dirección pertenece a una categoría, y cada categoría tiene su propio webhook.
"""
import os
import time
import json
import logging
import sqlite3
import hashlib
import hmac
import threading
import requests
import websocket
from datetime import datetime, timezone

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("mempool-watcher")

# ── Configuración ─────────────────────────────────────────────────────────────
MEMPOOL_URL     = os.getenv("MEMPOOL_URL", "http://umbrel.local:3006").rstrip("/")
WEBHOOK_URL     = os.getenv("WEBHOOK_URL", "")
WEBHOOK_SECRET  = os.getenv("WEBHOOK_SECRET", "")
DB_PATH         = os.getenv("DB_PATH", "/data/watcher.db")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))
RECONNECT_DELAY = int(os.getenv("RECONNECT_DELAY", "10"))
WATCHLIST_SYNC  = int(os.getenv("WATCHLIST_SYNC", "60"))

def get_ws_url() -> str:
    base = MEMPOOL_URL.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/api/v1/ws"

# ── Base de datos ─────────────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS categories (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL UNIQUE,
                webhook_url  TEXT NOT NULL,
                webhook_secret TEXT DEFAULT '',
                description  TEXT DEFAULT '',
                active       INTEGER DEFAULT 1,
                created_at   TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS addresses (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                address      TEXT NOT NULL UNIQUE,
                label        TEXT DEFAULT '',
                category_id  INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                active       INTEGER DEFAULT 1,
                created_at   TEXT DEFAULT (datetime('now')),
                last_match   TEXT
            );
            CREATE TABLE IF NOT EXISTS seen_txs (
                txid        TEXT PRIMARY KEY,
                address     TEXT NOT NULL,
                detected_at TEXT DEFAULT (datetime('now')),
                notified    INTEGER DEFAULT 0,
                retries     INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS webhook_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                txid        TEXT NOT NULL,
                address     TEXT NOT NULL,
                category    TEXT,
                webhook_url TEXT,
                status_code INTEGER,
                success     INTEGER DEFAULT 0,
                payload     TEXT,
                response    TEXT,
                sent_at     TEXT DEFAULT (datetime('now'))
            );
        """)
    log.info("Base de datos lista: %s", DB_PATH)

def load_watchlist() -> dict:
    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                a.address,
                c.id            AS category_id,
                c.name          AS category_name,
                c.webhook_url   AS cat_webhook_url,
                c.webhook_secret AS cat_webhook_secret
            FROM addresses a
            LEFT JOIN categories c ON c.id = a.category_id
            WHERE a.active = 1
              AND (c.id IS NULL OR c.active = 1)
        """).fetchall()
    return {
        r["address"]: {
            "category_id":    r["category_id"],
            "category_name":  r["category_name"] or "sin_categoria",
            "webhook_url":    r["cat_webhook_url"] or WEBHOOK_URL,
            "webhook_secret": r["cat_webhook_secret"] or WEBHOOK_SECRET,
        }
        for r in rows
    }

def _tx_key(txid: str, address: str) -> str:
    return hashlib.md5(f"{txid}:{address}".encode()).hexdigest()

def already_seen(txid: str, address: str) -> bool:
    with get_db() as conn:
        return bool(conn.execute(
            "SELECT 1 FROM seen_txs WHERE txid = ?", (_tx_key(txid, address),)
        ).fetchone())

def mark_seen(txid: str, address: str, notified: bool):
    with get_db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO seen_txs (txid, address, notified)
            VALUES (?, ?, ?)
        """, (_tx_key(txid, address), address, int(notified)))
        conn.execute(
            "UPDATE addresses SET last_match = datetime('now') WHERE address = ?",
            (address,)
        )

# ── Payload IPN ───────────────────────────────────────────────────────────────
def build_payload(address: str, meta: dict, tx: dict, event_type: str) -> dict:
    status = tx.get("status", {})
    received_sats = sum(
        v.get("value", 0) for v in tx.get("vout", [])
        if v.get("scriptpubkey_address") == address
    )
    sent_sats = sum(
        v.get("prevout", {}).get("value", 0) for v in tx.get("vin", [])
        if v.get("prevout", {}).get("scriptpubkey_address") == address
    )
    return {
        "event":         event_type,
        "address":       address,
        "category":      meta["category_name"],
        "txid":          tx["txid"],
        "confirmed":     status.get("confirmed", False),
        "block_height":  status.get("block_height"),
        "block_time":    status.get("block_time"),
        "fee":           tx.get("fee", 0),
        "size":          tx.get("size", 0),
        "weight":        tx.get("weight", 0),
        "received_sats": received_sats,
        "sent_sats":     sent_sats,
        "net_sats":      received_sats - sent_sats,
        "received_btc":  round(received_sats / 1e8, 8),
        "sent_btc":      round(sent_sats / 1e8, 8),
        "net_btc":       round((received_sats - sent_sats) / 1e8, 8),
        "vin_count":     len(tx.get("vin", [])),
        "vout_count":    len(tx.get("vout", [])),
        "mempool_url":   f"{MEMPOOL_URL}/tx/{tx['txid']}",
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }

# ── Webhook ───────────────────────────────────────────────────────────────────
def send_webhook(address: str, meta: dict, txid: str, payload: dict) -> bool:
    url    = meta["webhook_url"]
    secret = meta["webhook_secret"]
    if not url:
        log.warning("Sin webhook para categoría '%s', omitiendo", meta["category_name"])
        return False

    body = json.dumps(payload, ensure_ascii=False).encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent":   "mempool-watcher/3.0",
        "X-Event-Type": payload["event"],
        "X-Address":    address,
        "X-Category":   meta["category_name"],
        "X-TXID":       txid,
    }
    if secret:
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Signature"] = f"sha256={sig}"

    status_code, response_text, success = None, "", False
    try:
        r = requests.post(url, data=body, headers=headers, timeout=REQUEST_TIMEOUT)
        status_code   = r.status_code
        response_text = r.text[:500]
        success       = 200 <= r.status_code < 300
        icon = "✅" if success else "⚠️ "
        log.info("%s Webhook [%d] cat=%-15s txid=%.16s…",
                 icon, r.status_code, meta["category_name"], txid)
    except Exception as e:
        log.error("❌ Error webhook (cat=%s): %s", meta["category_name"], e)

    with get_db() as conn:
        conn.execute("""
            INSERT INTO webhook_log
              (txid, address, category, webhook_url, status_code, success, payload, response)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (txid, address, meta["category_name"], url,
              status_code, int(success), json.dumps(payload), response_text))
    return success

# ── Procesamiento ─────────────────────────────────────────────────────────────
def process_txs(txs: list, watchlist: dict, event_type: str):
    for tx in txs:
        txid = tx.get("txid")
        if not txid:
            continue
        involved = set()
        for vout in tx.get("vout", []):
            addr = vout.get("scriptpubkey_address")
            if addr and addr in watchlist:
                involved.add(addr)
        for vin in tx.get("vin", []):
            addr = vin.get("prevout", {}).get("scriptpubkey_address")
            if addr and addr in watchlist:
                involved.add(addr)
        for address in involved:
            if already_seen(txid, address):
                continue
            meta    = watchlist[address]
            payload = build_payload(address, meta, tx, event_type)
            log.info("🔔 [%-12s] [%-15s] txid=%.16s… net=%.8f BTC",
                     event_type.split("_")[0], meta["category_name"],
                     txid, payload["net_btc"])
            success = send_webhook(address, meta, txid, payload)
            mark_seen(txid, address, success)

# ── WebSocket handler ─────────────────────────────────────────────────────────
class MempoolWatcher:
    def __init__(self):
        self.watchlist: dict  = {}
        self.ws               = None
        self._lock            = threading.Lock()
        self._sync_timer      = None

    def _load_and_push(self):
        new_wl = load_watchlist()
        with self._lock:
            changed        = set(new_wl.keys()) != set(self.watchlist.keys())
            self.watchlist = new_wl
        if not new_wl:
            log.warning("Sin direcciones activas.")
            return
        if self.ws and self.ws.sock and self.ws.sock.connected:
            if changed:
                log.info("Watchlist actualizada: %d dir(s). Re-registrando…", len(new_wl))
                self._send_track(list(new_wl.keys()))

    def _send_track(self, addresses: list):
        try:
            self.ws.send(json.dumps({"track-addresses": addresses}))
            log.info("📡 track-addresses → %d dirección(es)", len(addresses))
        except Exception as e:
            log.error("Error enviando track-addresses: %s", e)

    def _schedule_sync(self):
        self._sync_timer = threading.Timer(WATCHLIST_SYNC, self._sync_tick)
        self._sync_timer.daemon = True
        self._sync_timer.start()

    def _sync_tick(self):
        self._load_and_push()
        self._schedule_sync()

    def on_open(self, ws):
        log.info("🔗 Conectado al WebSocket: %s", get_ws_url())
        self._load_and_push()
        self._schedule_sync()

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        with self._lock:
            wl = self.watchlist.copy()
        if "address-transactions" in data:
            process_txs(data["address-transactions"], wl, "mempool_transaction")
        if "block-transactions" in data:
            process_txs(data["block-transactions"],   wl, "confirmed_transaction")

    def on_error(self, ws, error):
        log.error("❌ Error WebSocket: %s", error)

    def on_close(self, ws, close_status_code, close_msg):
        log.warning("🔌 WebSocket cerrado (code=%s)", close_status_code)
        if self._sync_timer:
            self._sync_timer.cancel()

    def run(self):
        self.ws = websocket.WebSocketApp(
            get_ws_url(),
            on_open    = self.on_open,
            on_message = self.on_message,
            on_error   = self.on_error,
            on_close   = self.on_close,
        )
        self.ws.run_forever(ping_interval=30, ping_timeout=10)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info(" Mempool Bitcoin Watcher v3 (track-addresses + categorías)")
    log.info(" Mempool : %s", MEMPOOL_URL)
    log.info(" WS      : %s", get_ws_url())
    log.info(" Webhook : %s", WEBHOOK_URL or "(por categoría)")
    log.info(" WL sync : cada %ds", WATCHLIST_SYNC)
    log.info("=" * 60)
    init_db()
    watcher = MempoolWatcher()
    while True:
        try:
            watcher.run()
        except KeyboardInterrupt:
            log.info("Detenido por el usuario")
            break
        except Exception as e:
            log.error("Error inesperado: %s", e)
            log.info("⏳ Reconectando en %ds…", RECONNECT_DELAY)
            time.sleep(RECONNECT_DELAY)

if __name__ == "__main__":
    main()

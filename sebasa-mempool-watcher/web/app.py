"""
Mempool Bitcoin Watcher — Web UI / REST API
"""
import os, sqlite3, json
from flask import Flask, jsonify, request, render_template, abort
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DB_PATH     = os.getenv("DB_PATH",     "/data/watcher.db")
MEMPOOL_URL = os.getenv("MEMPOOL_URL", "http://umbrel.local:3006")


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables():
    try:
        with get_db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    webhook_url TEXT NOT NULL,
                    webhook_secret TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS addresses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    address TEXT NOT NULL UNIQUE,
                    label TEXT DEFAULT '',
                    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                    active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    last_match TEXT
                );
                CREATE TABLE IF NOT EXISTS seen_txs (
                    txid TEXT PRIMARY KEY,
                    address TEXT NOT NULL,
                    detected_at TEXT DEFAULT (datetime('now')),
                    notified INTEGER DEFAULT 0,
                    retries INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS webhook_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    txid TEXT NOT NULL,
                    address TEXT NOT NULL,
                    category TEXT,
                    webhook_url TEXT,
                    status_code INTEGER,
                    success INTEGER DEFAULT 0,
                    payload TEXT,
                    response TEXT,
                    sent_at TEXT DEFAULT (datetime('now'))
                );
            """)
    except Exception:
        pass


@app.route("/")
def index():
    return render_template("index.html", mempool_url=MEMPOOL_URL)


@app.route("/api/stats")
def api_stats():
    ensure_tables()
    with get_db() as conn:
        recent = conn.execute("""
            SELECT st.address, st.detected_at, st.notified,
                   c.name as category_name, wl.status_code
            FROM seen_txs st
            LEFT JOIN addresses a ON a.address = st.address
            LEFT JOIN categories c ON c.id = a.category_id
            LEFT JOIN webhook_log wl ON wl.txid = st.txid AND wl.address = st.address
            ORDER BY st.detected_at DESC LIMIT 10
        """).fetchall()
        return jsonify({
            "addresses":       conn.execute("SELECT COUNT(*) FROM addresses WHERE active=1").fetchone()[0],
            "categories":      conn.execute("SELECT COUNT(*) FROM categories WHERE active=1").fetchone()[0],
            "total_txs":       conn.execute("SELECT COUNT(*) FROM seen_txs").fetchone()[0],
            "notified_txs":    conn.execute("SELECT COUNT(*) FROM seen_txs WHERE notified=1").fetchone()[0],
            "failed_txs":      conn.execute("SELECT COUNT(*) FROM seen_txs WHERE notified=0").fetchone()[0],
            "success_webhooks":conn.execute("SELECT COUNT(*) FROM webhook_log WHERE success=1").fetchone()[0],
            "failed_webhooks": conn.execute("SELECT COUNT(*) FROM webhook_log WHERE success=0").fetchone()[0],
            "recent_txs":      [dict(r) for r in recent],
            "mempool_url":     MEMPOOL_URL,
        })


@app.route("/api/categories", methods=["GET"])
def get_categories():
    ensure_tables()
    with get_db() as conn:
        rows = conn.execute("""
            SELECT c.*, COUNT(a.id) as address_count
            FROM categories c
            LEFT JOIN addresses a ON a.category_id = c.id AND a.active = 1
            GROUP BY c.id ORDER BY c.name
        """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/categories", methods=["POST"])
def create_category():
    ensure_tables()
    d = request.json
    if not d.get("name") or not d.get("webhook_url"):
        abort(400, "name and webhook_url are required")
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO categories (name,webhook_url,webhook_secret,description) VALUES (?,?,?,?)",
                (d["name"], d["webhook_url"], d.get("webhook_secret",""), d.get("description",""))
            )
        except sqlite3.IntegrityError:
            abort(409, "Category already exists")
    return jsonify({"ok": True}), 201


@app.route("/api/categories/<int:cat_id>", methods=["PUT"])
def update_category(cat_id):
    d = request.json
    with get_db() as conn:
        conn.execute("""
            UPDATE categories SET
                name           = COALESCE(?, name),
                webhook_url    = COALESCE(?, webhook_url),
                webhook_secret = COALESCE(?, webhook_secret),
                description    = COALESCE(?, description),
                active         = COALESCE(?, active)
            WHERE id = ?
        """, (d.get("name"), d.get("webhook_url"), d.get("webhook_secret"),
              d.get("description"), d.get("active"), cat_id))
    return jsonify({"ok": True})


@app.route("/api/categories/<int:cat_id>", methods=["DELETE"])
def delete_category(cat_id):
    with get_db() as conn:
        conn.execute("UPDATE addresses SET category_id=NULL WHERE category_id=?", (cat_id,))
        conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    return jsonify({"ok": True})


@app.route("/api/addresses", methods=["GET"])
def get_addresses():
    ensure_tables()
    cat = request.args.get("category")
    with get_db() as conn:
        if cat:
            rows = conn.execute("""
                SELECT a.*, c.name as category_name FROM addresses a
                LEFT JOIN categories c ON c.id = a.category_id
                WHERE c.name = ? ORDER BY a.created_at DESC
            """, (cat,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT a.*, c.name as category_name FROM addresses a
                LEFT JOIN categories c ON c.id = a.category_id
                ORDER BY a.created_at DESC
            """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/addresses", methods=["POST"])
def create_address():
    ensure_tables()
    d = request.json
    if not d.get("address"):
        abort(400, "address is required")
    with get_db() as conn:
        cat_id = d.get("category_id") or None
        if not cat_id and d.get("category_name"):
            row = conn.execute("SELECT id FROM categories WHERE name=?", (d["category_name"],)).fetchone()
            if row: cat_id = row["id"]
        try:
            conn.execute(
                "INSERT INTO addresses (address,label,category_id) VALUES (?,?,?)",
                (d["address"], d.get("label",""), cat_id)
            )
        except sqlite3.IntegrityError:
            abort(409, "Address already exists")
    return jsonify({"ok": True}), 201


@app.route("/api/addresses/<path:address>", methods=["PUT"])
def update_address(address):
    d = request.json
    with get_db() as conn:
        conn.execute("""
            UPDATE addresses SET
                label       = COALESCE(?, label),
                category_id = CASE WHEN ? IS NOT NULL THEN ? ELSE category_id END,
                active      = COALESCE(?, active)
            WHERE address = ?
        """, (d.get("label"), d.get("category_id"), d.get("category_id"),
              d.get("active"), address))
    return jsonify({"ok": True})


@app.route("/api/addresses/<path:address>", methods=["DELETE"])
def delete_address(address):
    with get_db() as conn:
        conn.execute("DELETE FROM addresses WHERE address=?", (address,))
    return jsonify({"ok": True})


@app.route("/api/txs")
def get_txs():
    ensure_tables()
    limit = int(request.args.get("limit", 50))
    cat   = request.args.get("category")
    with get_db() as conn:
        if cat:
            rows = conn.execute("""
                SELECT st.*, c.name as category_name, wl.status_code, wl.success as webhook_success
                FROM seen_txs st
                LEFT JOIN addresses a ON a.address = st.address
                LEFT JOIN categories c ON c.id = a.category_id
                LEFT JOIN webhook_log wl ON wl.txid = st.txid AND wl.address = st.address
                WHERE c.name = ? ORDER BY st.detected_at DESC LIMIT ?
            """, (cat, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT st.*, c.name as category_name, wl.status_code, wl.success as webhook_success
                FROM seen_txs st
                LEFT JOIN addresses a ON a.address = st.address
                LEFT JOIN categories c ON c.id = a.category_id
                LEFT JOIN webhook_log wl ON wl.txid = st.txid AND wl.address = st.address
                ORDER BY st.detected_at DESC LIMIT ?
            """, (limit,)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/webhook-log")
def get_webhook_log():
    ensure_tables()
    limit = int(request.args.get("limit", 50))
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM webhook_log ORDER BY sent_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    ensure_tables()
    app.run(host="0.0.0.0", port=7890, debug=False)

#!/usr/bin/env python3
"""
manage.py — CLI para gestionar el Mempool Bitcoin Watcher
Uso: python manage.py <comando> [opciones]
"""
import os
import sys
import sqlite3
import argparse

DB_PATH = os.getenv("DB_PATH", "/data/watcher.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ── Categories ────────────────────────────────────────────────────────────────
def cmd_category(args):
    with get_db() as db:
        if args.action == "list":
            rows = db.execute("""
                SELECT c.*, COUNT(a.id) as addr_count
                FROM categories c LEFT JOIN addresses a ON a.category_id = c.id
                GROUP BY c.id ORDER BY c.name
            """).fetchall()
            if not rows:
                print("Sin categorías.")
                return
            print(f"{'ID':<4} {'Nombre':<20} {'Dirs':<6} {'Activa':<8} {'Webhook'}")
            print("─" * 80)
            for r in rows:
                print(f"{r['id']:<4} {r['name']:<20} {r['addr_count']:<6} {'Sí' if r['active'] else 'No':<8} {r['webhook_url']}")

        elif args.action == "add":
            try:
                db.execute(
                    "INSERT INTO categories (name, webhook_url, webhook_secret, description) VALUES (?,?,?,?)",
                    (args.name, args.webhook, getattr(args, 'secret', '') or '', getattr(args, 'description', '') or '')
                )
                print(f"✅ Categoría '{args.name}' creada.")
            except sqlite3.IntegrityError:
                print(f"❌ Ya existe una categoría con el nombre '{args.name}'")

        elif args.action == "edit":
            updates, params = [], []
            if args.webhook:
                updates.append("webhook_url = ?"); params.append(args.webhook)
            if getattr(args, 'secret', None):
                updates.append("webhook_secret = ?"); params.append(args.secret)
            if not updates:
                print("Nada que actualizar."); return
            params.append(args.name)
            db.execute(f"UPDATE categories SET {', '.join(updates)} WHERE name = ?", params)
            print(f"✅ Categoría '{args.name}' actualizada.")

        elif args.action == "remove":
            if not getattr(args, 'force', False):
                print("Usa --force para confirmar la eliminación.")
                return
            db.execute("UPDATE addresses SET category_id = NULL WHERE category_id = (SELECT id FROM categories WHERE name=?)", (args.name,))
            db.execute("DELETE FROM categories WHERE name = ?", (args.name,))
            print(f"✅ Categoría '{args.name}' eliminada.")

# ── Addresses ─────────────────────────────────────────────────────────────────
def cmd_address(args):
    with get_db() as db:
        if args.action == "list":
            cat_filter = getattr(args, 'category', None)
            query = """
                SELECT a.*, c.name as cat_name FROM addresses a
                LEFT JOIN categories c ON c.id = a.category_id
            """
            params = []
            if cat_filter:
                query += " WHERE c.name = ?"
                params.append(cat_filter)
            query += " ORDER BY c.name, a.created_at DESC"
            rows = db.execute(query, params).fetchall()
            if not rows:
                print("Sin direcciones."); return
            print(f"{'Dirección':<45} {'Label':<20} {'Categoría':<15} {'Activa':<8} {'Última TX'}")
            print("─" * 110)
            for r in rows:
                print(f"{r['address']:<45} {(r['label'] or '—'):<20} {(r['cat_name'] or 'sin cat.'):<15} {'Sí' if r['active'] else 'No':<8} {r['last_match'] or '—'}")

        elif args.action == "add":
            cat_id = None
            if getattr(args, 'category', None):
                row = db.execute("SELECT id FROM categories WHERE name=?", (args.category,)).fetchone()
                if not row:
                    print(f"❌ Categoría '{args.category}' no existe. Créala primero."); return
                cat_id = row["id"]
            try:
                db.execute(
                    "INSERT INTO addresses (address, label, category_id) VALUES (?,?,?)",
                    (args.address, getattr(args, 'label', '') or '', cat_id)
                )
                print(f"✅ Dirección '{args.address}' agregada.")
            except sqlite3.IntegrityError:
                print(f"❌ La dirección '{args.address}' ya existe.")

        elif args.action == "edit":
            updates, params = [], []
            if getattr(args, 'label', None):
                updates.append("label = ?"); params.append(args.label)
            if getattr(args, 'category', None):
                row = db.execute("SELECT id FROM categories WHERE name=?", (args.category,)).fetchone()
                if not row:
                    print(f"❌ Categoría '{args.category}' no existe."); return
                updates.append("category_id = ?"); params.append(row["id"])
            if not updates:
                print("Nada que actualizar."); return
            params.append(args.address)
            db.execute(f"UPDATE addresses SET {', '.join(updates)} WHERE address = ?", params)
            print(f"✅ Dirección '{args.address}' actualizada.")

        elif args.action == "remove":
            db.execute("DELETE FROM addresses WHERE address = ?", (args.address,))
            print(f"✅ Dirección '{args.address}' eliminada.")

        elif args.action == "disable":
            db.execute("UPDATE addresses SET active=0 WHERE address=?", (args.address,))
            print(f"⏸  Dirección '{args.address}' desactivada.")

        elif args.action == "enable":
            db.execute("UPDATE addresses SET active=1 WHERE address=?", (args.address,))
            print(f"▶️  Dirección '{args.address}' activada.")

# ── TXs ───────────────────────────────────────────────────────────────────────
def cmd_txs(args):
    limit = getattr(args, 'limit', 20) or 20
    cat   = getattr(args, 'category', None)
    with get_db() as db:
        query = """
            SELECT st.*, c.name as cat_name FROM seen_txs st
            LEFT JOIN addresses a ON a.address = st.address
            LEFT JOIN categories c ON c.id = a.category_id
        """
        params = []
        if cat:
            query += " WHERE c.name = ?"; params.append(cat)
        query += f" ORDER BY st.detected_at DESC LIMIT {limit}"
        rows = db.execute(query, params).fetchall()
        if not rows:
            print("Sin transacciones detectadas."); return
        print(f"{'TXID (hash)':<36} {'Dirección':<44} {'Cat.':<15} {'Detectada':<22} {'Notif.'}")
        print("─" * 130)
        for r in rows:
            print(f"{r['txid'][:35]:<36} {r['address']:<44} {(r['cat_name'] or '—'):<15} {r['detected_at']:<22} {'✅' if r['notified'] else '❌'}")

# ── Stats ─────────────────────────────────────────────────────────────────────
def cmd_stats(args):
    with get_db() as db:
        print("\n📊 Estadísticas generales")
        print("─" * 40)
        print(f"  Direcciones activas : {db.execute('SELECT COUNT(*) FROM addresses WHERE active=1').fetchone()[0]}")
        print(f"  Categorías activas  : {db.execute('SELECT COUNT(*) FROM categories WHERE active=1').fetchone()[0]}")
        print(f"  TXs detectadas      : {db.execute('SELECT COUNT(*) FROM seen_txs').fetchone()[0]}")
        print(f"  TXs notificadas     : {db.execute('SELECT COUNT(*) FROM seen_txs WHERE notified=1').fetchone()[0]}")
        print(f"  Webhooks exitosos   : {db.execute('SELECT COUNT(*) FROM webhook_log WHERE success=1').fetchone()[0]}")
        print(f"  Webhooks fallidos   : {db.execute('SELECT COUNT(*) FROM webhook_log WHERE success=0').fetchone()[0]}")

        cats = db.execute("""
            SELECT c.name, COUNT(st.txid) as tx_count
            FROM categories c
            LEFT JOIN addresses a ON a.category_id = c.id
            LEFT JOIN seen_txs st ON st.address = a.address
            GROUP BY c.id ORDER BY tx_count DESC
        """).fetchall()
        if cats:
            print("\n📂 TXs por categoría")
            print("─" * 30)
            for c in cats:
                print(f"  {c['name']:<20} {c['tx_count']} TXs")
        print()

# ── CLI setup ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Mempool Bitcoin Watcher — CLI")
    sub = parser.add_subparsers(dest="cmd")

    # category
    p_cat = sub.add_parser("category")
    cat_sub = p_cat.add_subparsers(dest="action")
    cat_sub.add_parser("list")
    p_cat_add = cat_sub.add_parser("add")
    p_cat_add.add_argument("name"); p_cat_add.add_argument("webhook")
    p_cat_add.add_argument("--secret", default=""); p_cat_add.add_argument("--description", default="")
    p_cat_edit = cat_sub.add_parser("edit")
    p_cat_edit.add_argument("name"); p_cat_edit.add_argument("--webhook"); p_cat_edit.add_argument("--secret")
    p_cat_rm = cat_sub.add_parser("remove")
    p_cat_rm.add_argument("name"); p_cat_rm.add_argument("--force", action="store_true")

    # address
    p_addr = sub.add_parser("address")
    addr_sub = p_addr.add_subparsers(dest="action")
    p_addr_list = addr_sub.add_parser("list"); p_addr_list.add_argument("--category")
    p_addr_add = addr_sub.add_parser("add")
    p_addr_add.add_argument("address"); p_addr_add.add_argument("--category"); p_addr_add.add_argument("--label", default="")
    p_addr_edit = addr_sub.add_parser("edit")
    p_addr_edit.add_argument("address"); p_addr_edit.add_argument("--category"); p_addr_edit.add_argument("--label")
    for a in ("remove", "disable", "enable"):
        p = addr_sub.add_parser(a); p.add_argument("address")

    # txs
    p_txs = sub.add_parser("txs")
    p_txs.add_argument("--limit", type=int, default=20); p_txs.add_argument("--category")

    # stats
    sub.add_parser("stats")

    args = parser.parse_args()
    if args.cmd == "category": cmd_category(args)
    elif args.cmd == "address": cmd_address(args)
    elif args.cmd == "txs":     cmd_txs(args)
    elif args.cmd == "stats":   cmd_stats(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()

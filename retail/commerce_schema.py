"""Additive storefront migration; the business database is backed up first."""

from datetime import datetime
from pathlib import Path
import sqlite3
import config
from .database import reading, transaction, one, add_columns


def migrate_commerce():
    with reading() as conn:
        if one(conn, "SELECT version FROM schema_migrations WHERE version=7"):
            return
        folder = Path(config.SQLITE_PATH).parent / "backups"
        folder.mkdir(exist_ok=True)
        target = sqlite3.connect(
            folder
            / ("before-v7-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".db")
        )
        try:
            conn.backup(target)
        finally:
            target.close()
    with transaction() as conn:
        add_columns(
            conn,
            "products",
            {
                "category": "TEXT NOT NULL DEFAULT 'Thiết yếu'",
                "storage_kind": "TEXT NOT NULL DEFAULT 'DRY'",
                "description": "TEXT NOT NULL DEFAULT ''",
                "image_path": "TEXT NOT NULL DEFAULT ''",
                "online_enabled": "INTEGER NOT NULL DEFAULT 1",
            },
        )
        add_columns(
            conn,
            "stock_batches",
            {
                "sell_until": "TEXT",
                "quality_status": "TEXT NOT NULL DEFAULT 'SELLABLE'",
            },
        )
        add_columns(conn, "orders", {"shipping_fee": "INTEGER NOT NULL DEFAULT 0"})
        schema = """
CREATE TABLE shop_accounts(id INTEGER PRIMARY KEY, phone TEXT NOT NULL UNIQUE, name TEXT NOT NULL, password_hash TEXT NOT NULL, customer_id INTEGER NOT NULL UNIQUE REFERENCES customers(id), active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE shop_sessions(token_hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES shop_accounts(id), csrf TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE shop_settings(id INTEGER PRIMARY KEY CHECK(id=1), store_name TEXT NOT NULL DEFAULT 'Tạp hóa 360', bank_bin TEXT NOT NULL DEFAULT '', bank_account TEXT NOT NULL DEFAULT '', bank_name TEXT NOT NULL DEFAULT '', delivery_note TEXT NOT NULL DEFAULT 'Tiệm xác nhận giờ giao sau khi nhận đơn.', accepting_orders INTEGER NOT NULL DEFAULT 1);
INSERT INTO shop_settings(id) VALUES(1);
CREATE TABLE delivery_zones(id INTEGER PRIMARY KEY, name TEXT NOT NULL, fee INTEGER NOT NULL CHECK(fee>=0), minimum_order INTEGER NOT NULL DEFAULT 0, eta TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE shop_banners(id INTEGER PRIMARY KEY, title TEXT NOT NULL, subtitle TEXT NOT NULL DEFAULT '', theme TEXT NOT NULL DEFAULT 'GREEN', image_path TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '', starts_at TEXT, ends_at TEXT, active INTEGER NOT NULL DEFAULT 1, position INTEGER NOT NULL DEFAULT 0);
CREATE TABLE timed_sales(id INTEGER PRIMARY KEY, name TEXT NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id), batch_id INTEGER REFERENCES stock_batches(id), price INTEGER NOT NULL CHECK(price>=0), max_units INTEGER NOT NULL CHECK(max_units>0), starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE online_orders(id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, account_id INTEGER NOT NULL REFERENCES shop_accounts(id), token_hash TEXT NOT NULL UNIQUE, request_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', payment_method TEXT NOT NULL, paid INTEGER NOT NULL DEFAULT 0, payment_reference TEXT NOT NULL DEFAULT '', refund_due INTEGER NOT NULL DEFAULT 0, refund_paid INTEGER NOT NULL DEFAULT 0, refund_reference TEXT NOT NULL DEFAULT '', receiver TEXT NOT NULL, phone TEXT NOT NULL, address TEXT NOT NULL, zone_id INTEGER NOT NULL REFERENCES delivery_zones(id), shipping_fee INTEGER NOT NULL, goods_total INTEGER NOT NULL, points_used INTEGER NOT NULL DEFAULT 0, points_earned INTEGER NOT NULL DEFAULT 0, substitution TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1, approved INTEGER NOT NULL DEFAULT 1, sale_order_id INTEGER REFERENCES orders(id), rescue_campaign_id INTEGER REFERENCES rescue_campaigns(id), rescue_sets INTEGER NOT NULL DEFAULT 0, shipper_id INTEGER REFERENCES users(id), expires_at TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE online_items(id INTEGER PRIMARY KEY, online_order_id INTEGER NOT NULL REFERENCES online_orders(id), product_id INTEGER NOT NULL REFERENCES products(id), product_name TEXT NOT NULL, unit TEXT NOT NULL, storage_kind TEXT NOT NULL, quantity INTEGER NOT NULL, price INTEGER NOT NULL, total INTEGER NOT NULL, sale_id INTEGER REFERENCES timed_sales(id), accepted INTEGER, rejected_handling TEXT NOT NULL DEFAULT '', allocations TEXT NOT NULL DEFAULT '[]');
CREATE INDEX online_item_order ON online_items(online_order_id);
CREATE TABLE online_events(id INTEGER PRIMARY KEY, online_order_id INTEGER NOT NULL REFERENCES online_orders(id), status TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE shop_points_ledger(id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES shop_accounts(id), online_order_id INTEGER REFERENCES online_orders(id), amount INTEGER NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
"""
        for statement in schema.split(";"):
            if statement.strip():
                conn.execute(statement)
        add_columns(conn, "online_items", {"points_part": "INTEGER NOT NULL DEFAULT 0"})
        add_columns(
            conn, "order_items", {"timed_sale_id": "INTEGER REFERENCES timed_sales(id)"}
        )
        conn.execute("INSERT INTO schema_migrations(version) VALUES(7)")

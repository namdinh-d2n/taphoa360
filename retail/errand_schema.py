# Additive migration for the personal-shopping workflow.
from datetime import datetime
from pathlib import Path
import sqlite3
import config
from .database import one, reading, transaction


def migrate_errands():
    with reading() as conn:
        if one(conn, "SELECT version FROM schema_migrations WHERE version=12"):
            return
        folder = Path(config.SQLITE_PATH).parent / "backups"
        folder.mkdir(exist_ok=True)
        target = sqlite3.connect(
            folder
            / ("before-v12-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".db")
        )
        try:
            conn.backup(target)
        finally:
            target.close()
    with transaction() as conn:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute("INSERT INTO schema_migrations(version) VALUES (12)")


SCHEMA = """
CREATE TABLE IF NOT EXISTS errand_settings(id INTEGER PRIMARY KEY CHECK(id=1), service_fee INTEGER NOT NULL DEFAULT 15000, complaint_hours INTEGER NOT NULL DEFAULT 24, policy TEXT NOT NULL DEFAULT 'Báo ngay khi hàng thiếu hoặc chất lượng không đạt. Giữ ảnh và bao bì để cửa hàng đối chiếu. Hàng trả về được kiểm tra riêng, không tự đưa lại lên kệ.');
INSERT OR IGNORE INTO errand_settings(id) VALUES(1);
CREATE TABLE IF NOT EXISTS errand_orders(id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, account_id INTEGER NOT NULL REFERENCES shop_accounts(id), request_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'REQUESTED', version INTEGER NOT NULL DEFAULT 1, receiver TEXT NOT NULL, phone TEXT NOT NULL, address TEXT NOT NULL, zone_id INTEGER NOT NULL REFERENCES delivery_zones(id), delivery_window TEXT NOT NULL, budget INTEGER NOT NULL, preferences TEXT NOT NULL, service_fee INTEGER NOT NULL, shipping_fee INTEGER NOT NULL, complaint_hours INTEGER NOT NULL, policy TEXT NOT NULL, estimate INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0, credit INTEGER NOT NULL DEFAULT 0, shopper_id INTEGER REFERENCES users(id), shipper_id INTEGER REFERENCES users(id), review_deadline TEXT, received INTEGER NOT NULL DEFAULT 0, delivered_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS errand_customer ON errand_orders(account_id,id);
CREATE TABLE IF NOT EXISTS errand_items(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES errand_orders(id), requested_name TEXT NOT NULL, requested_qty REAL NOT NULL, requested_unit TEXT NOT NULL, criteria TEXT NOT NULL, selected_name TEXT NOT NULL DEFAULT '', quantity REAL NOT NULL DEFAULT 0, unit TEXT NOT NULL DEFAULT '', unit_price INTEGER NOT NULL DEFAULT 0, subtotal INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'EXTERNAL', product_id INTEGER REFERENCES products(id), vendor TEXT NOT NULL DEFAULT '', quality TEXT NOT NULL DEFAULT '', photo TEXT NOT NULL DEFAULT '', skipped INTEGER NOT NULL DEFAULT 0, proposal TEXT, decision TEXT NOT NULL DEFAULT 'NONE');
CREATE TABLE IF NOT EXISTS errand_events(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES errand_orders(id), actor TEXT NOT NULL, message TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS errand_money(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES errand_orders(id), kind TEXT NOT NULL CHECK(kind IN ('RECEIVE','REFUND','EXPENSE')), amount INTEGER NOT NULL CHECK(amount>0), method TEXT NOT NULL CHECK(method IN ('CASH','TRANSFER')), reference TEXT NOT NULL UNIQUE, recipient TEXT NOT NULL, reason TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id), payment_id INTEGER NOT NULL REFERENCES payments(id), request_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS errand_allocations(id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES errand_items(id), batch_id INTEGER NOT NULL REFERENCES stock_batches(id), quantity REAL NOT NULL, cost_price INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS errand_complaints(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES errand_orders(id), item_id INTEGER REFERENCES errand_items(id), reason TEXT NOT NULL, photo TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'OPEN', resolution TEXT NOT NULL DEFAULT '', credit INTEGER NOT NULL DEFAULT 0, reply TEXT NOT NULL DEFAULT '', handler_id INTEGER REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS errand_photos(name TEXT PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES errand_orders(id));
"""


def migrate_errand_locations():
    from .database import add_columns
    from .locations import provinces

    with reading() as conn:
        if one(conn, "SELECT version FROM schema_migrations WHERE version=13"):
            return
        folder = Path(config.SQLITE_PATH).parent / "backups"
        folder.mkdir(exist_ok=True)
        target = sqlite3.connect(
            folder
            / ("before-v13-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".db")
        )
        try:
            conn.backup(target)
        finally:
            target.close()
    with transaction() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS errand_branches (
            id INTEGER PRIMARY KEY, province_code INTEGER NOT NULL, province_name TEXT NOT NULL,
            name TEXT NOT NULL, address TEXT NOT NULL, zone_id INTEGER REFERENCES delivery_zones(id), fee INTEGER NOT NULL DEFAULT 12000 CHECK(fee>=0),
            active INTEGER NOT NULL DEFAULT 1, is_demo INTEGER NOT NULL DEFAULT 1,
            UNIQUE(province_code,name))""")
        add_columns(
            conn,
            "errand_orders",
            {
                "province_code": "INTEGER",
                "province_name": "TEXT NOT NULL DEFAULT ''",
                "branch_id": "INTEGER REFERENCES errand_branches(id)",
                "branch_name": "TEXT NOT NULL DEFAULT ''",
                "payment_method": "TEXT NOT NULL DEFAULT 'TRANSFER'",
            },
        )
        demo_provinces = provinces()["provinces"] if not config.PRODUCTION else []
        for province in demo_provinces:
            code, name = province["code"], province["name"]
            for index in range(1, 3 if code in {1, 79} else 2):
                conn.execute(
                    """INSERT OR IGNORE INTO errand_branches(province_code,province_name,name,address,zone_id)
                    VALUES(?,?,?,?,?)""",
                    (
                        code,
                        name,
                        f"Tạp hóa 360 · {name} · Điểm {index}",
                        f"Điểm phục vụ {index} tại {name} (địa điểm demo)",
                        None,
                    ),
                )
        conn.execute("INSERT INTO schema_migrations(version) VALUES(13)")

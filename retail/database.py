"""Versioned, additive SQLite migrations and atomic business transactions."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
import threading

import config

LOCK = threading.RLock()
SCHEMA_VERSION = 4


def connect():
    conn = sqlite3.connect(config.SQLITE_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=20000')
    return conn


@contextmanager
def transaction():
    with LOCK:
        conn = connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@contextmanager
def reading():
    with LOCK:
        conn = connect()
        try:
            yield conn
        finally:
            conn.close()


def rows(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def one(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def add_columns(conn, table, definitions):
    existing = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
    for name, definition in definitions.items():
        if name not in existing:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')


def _migrate_v3():
    if config.DB_TYPE != 'sqlite':
        raise RuntimeError('Retail v3 requires DB_TYPE=sqlite. MySQL migration is not supported.')
    Path(config.SQLITE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with reading() as conn:
        existing = one(conn, "SELECT name FROM sqlite_master WHERE name='products'")
    if not existing:
        import db
        db._init_sqlite_schema(seed_demo=config.SEED_DEMO)
    with reading() as conn:
        migrated = one(conn, "SELECT name FROM sqlite_master WHERE name='schema_migrations'")
        if migrated and one(conn, 'SELECT version FROM schema_migrations WHERE version=3'):
            return
        backup_dir = Path(config.SQLITE_PATH).parent / 'backups'
        backup_dir.mkdir(exist_ok=True)
        target = sqlite3.connect(backup_dir / ('before-v3-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.db'))
        try:
            conn.backup(target)
        finally:
            target.close()
    with transaction() as conn:
        statements = SCHEMA.split(';')
        for statement in statements:
            if statement.strip():
                conn.execute(statement)
        add_columns(conn, 'products', {'barcode': "TEXT DEFAULT ''", 'cost_price': 'INTEGER DEFAULT 0', 'min_stock': 'REAL DEFAULT 5', 'active': 'INTEGER DEFAULT 1', 'promo_price': 'INTEGER', 'promo_until': 'TEXT'})
        add_columns(conn, 'orders', {'customer_id': 'INTEGER REFERENCES customers(id)', 'cashier_id': 'INTEGER REFERENCES users(id)', 'shipper_user_id': 'INTEGER REFERENCES users(id)', 'gross_amount': 'INTEGER DEFAULT 0', 'discount': 'INTEGER DEFAULT 0', 'points_redeemed': 'INTEGER DEFAULT 0', 'points_earned': 'INTEGER DEFAULT 0', 'managed': 'INTEGER DEFAULT 0', 'idempotency_key': 'TEXT', 'request_hash': 'TEXT', 'fulfillment': "TEXT DEFAULT 'PICKUP'"})
        add_columns(conn, 'order_items', {'product_id': 'INTEGER REFERENCES products(id)', 'cost_price': 'REAL DEFAULT 0', 'returned_qty': 'REAL DEFAULT 0', 'net_subtotal': 'INTEGER DEFAULT 0'})
        add_columns(conn, 'employees', {'salary_mode': "TEXT DEFAULT 'MONTHLY'", 'working_days': 'INTEGER DEFAULT 26'})
        add_columns(conn, 'attendance', {'check_in_at': 'TEXT', 'check_out_at': 'TEXT', 'hours_worked': 'REAL DEFAULT 0', 'late_minutes': 'INTEGER DEFAULT 0'})
        add_columns(conn, 'payroll', {'calculated_at': 'TEXT'})
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS orders_idempotency ON orders(idempotency_key) WHERE idempotency_key IS NOT NULL')
        conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS products_barcode ON products(barcode) WHERE barcode != \'\'')
        conn.execute('CREATE INDEX IF NOT EXISTS batch_fefo ON stock_batches(product_id,expires_on,received_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS order_items_order ON order_items(order_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS movement_product ON stock_movements(product_id,id)')
        conn.execute('CREATE INDEX IF NOT EXISTS attendance_employee ON attendance(employee_id,work_date)')
        for product in rows(conn, 'SELECT * FROM products'):
            qty = max(0, product['stock'] or 0)
            conn.execute('UPDATE products SET stock=? WHERE id=?', (qty, product['id']))
            if qty:
                batch_id = conn.execute('INSERT INTO stock_batches(product_id,lot_code,remaining,cost_price) VALUES (?,?,?,?)', (product['id'], 'OPENING', qty, product['cost_price'])).lastrowid
                conn.execute("INSERT INTO stock_movements(product_id,batch_id,quantity,kind,reference,note) VALUES (?,?,?,'OPENING','migration','Tồn đầu kỳ khi nâng cấp')", (product['id'], batch_id, qty))
        conn.execute('UPDATE orders SET gross_amount=total_amount WHERE managed=0')
        conn.execute('UPDATE order_items SET net_subtotal=subtotal')
        conn.execute('UPDATE order_items SET product_id=(SELECT id FROM products WHERE products.product_name=order_items.product_name ORDER BY id LIMIT 1) WHERE product_id IS NULL')
        conn.execute("INSERT INTO schema_migrations(version) VALUES (3)")


def migrate():
    _migrate_v3()
    # Only one application process is supported (backup/restore uses a process lock).
    with reading() as conn:
        conn.execute('PRAGMA journal_mode=' + config.SQLITE_JOURNAL_MODE)
    with reading() as conn:
        if one(conn, 'SELECT version FROM schema_migrations WHERE version=4'):
            return
        backup_dir = Path(config.SQLITE_PATH).parent / 'backups'
        backup_dir.mkdir(exist_ok=True)
        target = sqlite3.connect(backup_dir / ('before-v4-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.db'))
        try:
            conn.backup(target)
        finally:
            target.close()
    with transaction() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE,
            name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('owner','cashier','inventory','shipper')),
            status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','APPROVED','REJECTED')),
            created_at TEXT DEFAULT (datetime('now','localtime')), reviewed_at TEXT,
            reviewed_by INTEGER REFERENCES users(id), review_note TEXT DEFAULT '',
            user_id INTEGER REFERENCES users(id)
        )''')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS pending_registration_username ON registrations(username) WHERE status='PENDING'")
        conn.execute('INSERT INTO schema_migrations(version) VALUES (4)')


SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','cashier','inventory','shipper')), employee_id INTEGER REFERENCES employees(id), active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY, failures INTEGER NOT NULL, locked_until REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), action TEXT NOT NULL, entity TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT '', address TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT '', customer_group TEXT DEFAULT 'RETAIL', points INTEGER DEFAULT 0 CHECK(points>=0));
CREATE TABLE IF NOT EXISTS stock_batches(id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), lot_code TEXT NOT NULL, expires_on TEXT, remaining REAL NOT NULL CHECK(remaining>=0), cost_price INTEGER NOT NULL CHECK(cost_price>=0), received_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS stock_movements(id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), batch_id INTEGER REFERENCES stock_batches(id), quantity REAL NOT NULL, kind TEXT NOT NULL, reference TEXT DEFAULT '', note TEXT DEFAULT '', user_id INTEGER REFERENCES users(id), created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS purchase_receipts(id INTEGER PRIMARY KEY, supplier_id INTEGER NOT NULL REFERENCES suppliers(id), total INTEGER NOT NULL, paid INTEGER NOT NULL, note TEXT DEFAULT '', user_id INTEGER REFERENCES users(id), created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS purchase_items(id INTEGER PRIMARY KEY, receipt_id INTEGER REFERENCES purchase_receipts(id), product_id INTEGER REFERENCES products(id), batch_id INTEGER REFERENCES stock_batches(id), quantity REAL NOT NULL, cost_price INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS cash_shifts(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), opening_cash INTEGER NOT NULL, expected_cash INTEGER, counted_cash INTEGER, difference INTEGER, note TEXT DEFAULT '', opened_at TEXT DEFAULT (datetime('now','localtime')), closed_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_cash_shift ON cash_shifts(user_id) WHERE closed_at IS NULL;
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id), amount INTEGER NOT NULL, method TEXT NOT NULL CHECK(method IN ('CASH','TRANSFER','DEBT')), kind TEXT NOT NULL, cash_shift_id INTEGER REFERENCES cash_shifts(id), reference TEXT DEFAULT '', user_id INTEGER REFERENCES users(id), created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS account_entries(id INTEGER PRIMARY KEY, party_type TEXT NOT NULL CHECK(party_type IN ('CUSTOMER','SUPPLIER')), party_id INTEGER NOT NULL, amount INTEGER NOT NULL, reference TEXT NOT NULL, note TEXT DEFAULT '', user_id INTEGER REFERENCES users(id), created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS order_allocations(id INTEGER PRIMARY KEY, order_item_id INTEGER NOT NULL REFERENCES order_items(id), batch_id INTEGER NOT NULL REFERENCES stock_batches(id), quantity REAL NOT NULL, returned_qty REAL DEFAULT 0, cost_price INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS returns(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), amount INTEGER NOT NULL, reason TEXT NOT NULL, user_id INTEGER REFERENCES users(id), created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS return_items(id INTEGER PRIMARY KEY, return_id INTEGER NOT NULL REFERENCES returns(id), order_item_id INTEGER NOT NULL REFERENCES order_items(id), quantity REAL NOT NULL, amount INTEGER NOT NULL, restock INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS order_events(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id), status TEXT NOT NULL, user_id INTEGER REFERENCES users(id), note TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS hr_requests(id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id), kind TEXT NOT NULL CHECK(kind IN ('LEAVE','SWAP')), work_date TEXT NOT NULL, target_employee_id INTEGER REFERENCES employees(id), reason TEXT NOT NULL, status TEXT DEFAULT 'PENDING', reviewed_by INTEGER REFERENCES users(id));
'''

"""
Database connection module for Tạp hóa 360.
Supports MySQL (PyMySQL) with automatic fallback to local SQLite (taphoa360.db)
if the remote MySQL server is unreachable.
"""

import os
import sqlite3
from datetime import datetime
import pymysql
import pymysql.cursors

# Remote/Local MySQL Configurations
MYSQL_HOST = os.getenv("DB_HOST", "sql204.infinityfree.com")
MYSQL_USER = os.getenv("DB_USER", "if0_43333923")
MYSQL_PASS = os.getenv("DB_PASS", "taphoa360")
MYSQL_NAME = os.getenv("DB_NAME", "if0_43333923_taphoa360_db")
MYSQL_PORT = int(os.getenv("DB_PORT", "3306"))

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "taphoa360.db")

_db_type = None  # 'mysql' or 'sqlite'


def _test_mysql():
    try:
        conn = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASS,
            database=MYSQL_NAME,
            port=MYSQL_PORT,
            connect_timeout=3,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor
        )
        conn.close()
        return True
    except Exception:
        # Check local MySQL on 127.0.0.1
        try:
            conn = pymysql.connect(
                host="127.0.0.1",
                user="root",
                password="",
                database=MYSQL_NAME,
                port=3306,
                connect_timeout=2,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            conn.close()
            return "local"
        except Exception:
            return False


def get_db_type():
    global _db_type
    if _db_type is None:
        mysql_status = _test_mysql()
        if mysql_status == "local":
            _db_type = "mysql_local"
            print("[DB] Using MySQL Local (127.0.0.1:3306)")
        elif mysql_status is True:
            _db_type = "mysql"
            print(f"[DB] Using MySQL Remote ({MYSQL_HOST})")
        else:
            _db_type = "sqlite"
            print(f"[DB] MySQL unavailable. Using SQLite fallback: {SQLITE_PATH}")
            _init_sqlite_schema()
    return _db_type


def get_connection():
    db_type = get_db_type()
    if db_type == "mysql":
        return pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASS,
            database=MYSQL_NAME,
            port=MYSQL_PORT,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
    elif db_type == "mysql_local":
        return pymysql.connect(
            host="127.0.0.1",
            user="root",
            password="",
            database=MYSQL_NAME,
            port=3306,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def _format_sql_for_engine(sql, db_type):
    """Normalize SQL syntax: converts ? to %s for MySQL if needed."""
    if "mysql" in db_type:
        return sql.replace("?", "%s")
    return sql


def query_all(sql, params=None):
    """Execute SELECT query and return list of dictionaries."""
    db_type = get_db_type()
    sql = _format_sql_for_engine(sql, db_type)
    conn = get_connection()
    try:
        if "mysql" in db_type:
            with conn.cursor() as cursor:
                cursor.execute(sql, params or ())
                return cursor.fetchall()
        else:
            cursor = conn.cursor()
            cursor.execute(sql, params or ())
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    finally:
        conn.close()


def query_one(sql, params=None):
    """Execute SELECT query and return a single dictionary or None."""
    db_type = get_db_type()
    sql = _format_sql_for_engine(sql, db_type)
    conn = get_connection()
    try:
        if "mysql" in db_type:
            with conn.cursor() as cursor:
                cursor.execute(sql, params or ())
                return cursor.fetchone()
        else:
            cursor = conn.cursor()
            cursor.execute(sql, params or ())
            row = cursor.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def execute(sql, params=None):
    """Execute INSERT/UPDATE/DELETE and return lastrowid."""
    db_type = get_db_type()
    sql = _format_sql_for_engine(sql, db_type)
    conn = get_connection()
    try:
        if "mysql" in db_type:
            with conn.cursor() as cursor:
                cursor.execute(sql, params or ())
                conn.commit()
                return cursor.lastrowid
        else:
            cursor = conn.cursor()
            cursor.execute(sql, params or ())
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


def _init_sqlite_schema():
    """Initializes SQLite schema and seed sample data if tables don't exist."""
    conn = sqlite3.connect(SQLITE_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_code TEXT NOT NULL,
        created_by TEXT DEFAULT 'Thu ngân',
        total_amount REAL DEFAULT 0,
        payment_method TEXT DEFAULT 'Tiền mặt',
        apartment TEXT DEFAULT '',
        status TEXT DEFAULT 'PENDING',
        customer_note TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        product_name TEXT NOT NULL,
        shelf_location TEXT DEFAULT '',
        quantity REAL DEFAULT 1,
        price REAL DEFAULT 0,
        subtotal REAL DEFAULT 0,
        is_picked INTEGER DEFAULT 0,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        sku TEXT NOT NULL,
        stock REAL DEFAULT 0,
        unit TEXT DEFAULT 'cái',
        shelf_location TEXT DEFAULT '',
        zone_code TEXT DEFAULT 'B1',
        price REAL DEFAULT 150000
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_suggestions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        suggestion_type TEXT DEFAULT 'EXPIRING',
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        status TEXT DEFAULT 'PENDING',
        created_at TEXT DEFAULT (datetime('now', 'localtime'))
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shippers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        status TEXT DEFAULT 'PHÂN CÔNG',
        note TEXT DEFAULT ''
    );
    """)

    conn.commit()

    # Seed data if products is empty
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO products (product_name, sku, stock, unit, shelf_location, zone_code, price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            ("Sữa tươi không đường 1L", "SKU-SUA-01", 12, "lốc", "Kệ B2 · Tầng 2 · Ô B2-04", "B2", 36000),
            ("Bánh mì sandwich bơ tỏi", "SKU-BM-02", 25, "gói", "Kệ A1 · Tầng 1 · Ô A1-02", "A1", 22000),
            ("Nước ngọt Coca-Cola 320ml", "SKU-COCA-03", 48, "lon", "Kệ B1 · Tầng 3 · Ô B1-12", "B1", 11000),
            ("Mì Hảo Hảo tôm chua cay", "SKU-MI-04", 60, "gói", "Kệ A1 · Tầng 2 · Ô A1-05", "A1", 4500),
            ("Sữa chua Vinamilk có đường", "SKU-SC-05", 20, "lốc", "Kệ B2 · Tầng 1 · Ô B2-01", "B2", 28000),
            ("Bia Heineken Sleek lon 330ml", "SKU-BIA-06", 30, "lon", "Kệ B1 · Tầng 2 · Ô B1-08", "B1", 21000)
        ])

    cursor.execute("SELECT COUNT(*) FROM ai_suggestions")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO ai_suggestions (suggestion_type, title, description, status)
            VALUES (?, ?, ?, ?)
        """, [
            ("EXPIRING", "Xả hàng sữa chua cận date 5 ngày", "Tồn kho còn 20 lốc sữa chua có hạn sử dụng cận ngày. Đề xuất giảm 20% hoặc tặng kèm bánh mì.", "PENDING"),
            ("COMBO", "Combo tiệc gia đình cuối tuần", "Gợi ý gói Combo Mì Hảo Hảo + Coca-Cola + Snack tiết kiệm 15% kích thích doanh số.", "PENDING")
        ])

    cursor.execute("SELECT COUNT(*) FROM shippers")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO shippers (name, status, note)
            VALUES (?, ?, ?)
        """, [
            ("Anh Khoa", "ĐANG GIAO", "Đang giao: Căn hộ A2-1508"),
            ("Chị Mai", "PHÂN CÔNG", "Sẵn sàng nhận đơn tiếp theo")
        ])

    cursor.execute("SELECT COUNT(*) FROM orders")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO orders (order_code, created_by, total_amount, payment_method, apartment, status, customer_note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now', '-10 minutes'))
        """, ("DH-20261104-201500", "Thu ngân 01", 158000, "Tiền mặt", "P.702 Tòa Landmark", "PROCESSING", "Giao trước 21h tối"))
        order_id = cursor.lastrowid
        cursor.executemany("""
            INSERT INTO order_items (order_id, product_name, shelf_location, quantity, price, subtotal, is_picked)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            (order_id, "Sữa tươi không đường 1L", "Kệ B2 · Tầng 2 · Ô B2-04", 2, 36000, 72000, 1),
            (order_id, "Bánh mì sandwich bơ tỏi", "Kệ A1 · Tầng 1 · Ô A1-02", 2, 22000, 44000, 0),
            (order_id, "Nước ngọt Coca-Cola 320ml", "Kệ B1 · Tầng 3 · Ô B1-12", 3, 14000, 42000, 0)
        ])

    # ---- HR MODULE TABLES ----
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role TEXT DEFAULT 'Thu ngân',
        phone TEXT DEFAULT '',
        email TEXT DEFAULT '',
        base_salary REAL DEFAULT 5000000,
        hourly_rate REAL DEFAULT 30000,
        avatar_initials TEXT DEFAULT 'NV',
        status TEXT DEFAULT 'ACTIVE',
        join_date TEXT DEFAULT (date('now', 'localtime'))
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        color TEXT DEFAULT 'emerald',
        label TEXT DEFAULT ''
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS shift_schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        shift_id INTEGER NOT NULL,
        work_date TEXT NOT NULL,
        FOREIGN KEY (employee_id) REFERENCES employees(id),
        FOREIGN KEY (shift_id) REFERENCES shifts(id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        work_date TEXT NOT NULL,
        check_in TEXT DEFAULT NULL,
        check_out TEXT DEFAULT NULL,
        status TEXT DEFAULT 'ABSENT',
        gps_location TEXT DEFAULT '',
        note TEXT DEFAULT '',
        FOREIGN KEY (employee_id) REFERENCES employees(id)
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payroll (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        month INTEGER NOT NULL,
        year INTEGER NOT NULL,
        days_worked INTEGER DEFAULT 0,
        hours_worked REAL DEFAULT 0,
        base_salary REAL DEFAULT 0,
        bonus REAL DEFAULT 0,
        deduction REAL DEFAULT 0,
        total REAL DEFAULT 0,
        status TEXT DEFAULT 'DRAFT',
        FOREIGN KEY (employee_id) REFERENCES employees(id)
    );
    """)

    conn.commit()

    # Seed HR data
    cursor.execute("SELECT COUNT(*) FROM employees")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO employees (name, role, phone, base_salary, hourly_rate, avatar_initials, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            ("Lan Nguyen", "Chu tiem", "0901 234 567", 12000000, 50000, "LN", "ACTIVE"),
            ("Minh Tran", "Thu ngan", "0912 345 678", 7000000, 35000, "MT", "ACTIVE"),
            ("Huy Pham", "Kiem kho", "0923 456 789", 6500000, 32000, "HP", "ACTIVE"),
            ("Thien Le", "Thu ngan", "0934 567 890", 7000000, 35000, "TL", "ACTIVE"),
            ("Khoa Vo", "Tai xe giao hang", "0945 678 901", 6000000, 30000, "KV", "ACTIVE"),
        ])

    cursor.execute("SELECT COUNT(*) FROM shifts")
    if cursor.fetchone()[0] == 0:
        cursor.executemany("""
            INSERT INTO shifts (name, start_time, end_time, color, label)
            VALUES (?, ?, ?, ?, ?)
        """, [
            ("SANG", "06:00", "14:00", "emerald", "SANG"),
            ("CHIEU", "14:00", "22:00", "blue", "CHIEU"),
            ("TOI", "22:00", "06:00", "purple", "TOI"),
            ("NGHI", "", "", "slate", "NGHI"),
        ])

    cursor.execute("SELECT COUNT(*) FROM shift_schedule")
    if cursor.fetchone()[0] == 0:
        from datetime import date, timedelta
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        # Sample week schedule: employee_id, shift_id, day offset
        schedule_data = [
            # Lan Nguyen (id=1) - shift SANG(1) Mon,Wed,Fri; CHIEU(2) Tue,Thu
            (1, 1, 0), (1, 2, 1), (1, 1, 2), (1, 2, 3), (1, 1, 4), (1, 4, 5), (1, 4, 6),
            # Minh Tran (id=2)
            (2, 1, 0), (2, 1, 1), (2, 2, 2), (2, 1, 3), (2, 2, 4), (2, 1, 5), (2, 4, 6),
            # Huy Pham (id=3)
            (3, 2, 0), (3, 2, 1), (3, 1, 2), (3, 2, 3), (3, 2, 4), (3, 4, 5), (3, 1, 6),
            # Thien Le (id=4)
            (4, 3, 0), (4, 3, 1), (4, 3, 2), (4, 4, 3), (4, 3, 4), (4, 3, 5), (4, 4, 6),
            # Khoa Vo (id=5)
            (5, 1, 0), (5, 2, 1), (5, 4, 2), (5, 1, 3), (5, 2, 4), (5, 1, 5), (5, 2, 6),
        ]
        for emp_id, shift_id, day_offset in schedule_data:
            work_date = (monday + timedelta(days=day_offset)).isoformat()
            cursor.execute(
                "INSERT INTO shift_schedule (employee_id, shift_id, work_date) VALUES (?, ?, ?)",
                (emp_id, shift_id, work_date)
            )

    cursor.execute("SELECT COUNT(*) FROM attendance")
    if cursor.fetchone()[0] == 0:
        from datetime import date as dt_date
        today_str = dt_date.today().isoformat()
        cursor.executemany("""
            INSERT INTO attendance (employee_id, work_date, check_in, check_out, status, gps_location)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            (1, today_str, "06:03", "14:05", "DUNG_GIO", "10.7769,106.7009"),
            (2, today_str, "06:17", None,    "DI_TRE",   "10.7781,106.7015"),
            (3, today_str, "14:01", "22:00", "DUNG_GIO", "10.7769,106.7009"),
            (4, today_str, None,    None,    "VANG",     ""),
            (5, today_str, "06:00", "14:02", "DUNG_GIO", "10.7769,106.7009"),
        ])

    cursor.execute("SELECT COUNT(*) FROM payroll")
    if cursor.fetchone()[0] == 0:
        from datetime import date as dt_date2
        m = dt_date2.today().month
        y = dt_date2.today().year
        cursor.executemany("""
            INSERT INTO payroll (employee_id, month, year, days_worked, hours_worked, base_salary, bonus, deduction, total, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (1, m, y, 24, 192, 12000000, 1500000, 350000, 13150000, "DRAFT"),
            (2, m, y, 26, 208,  7000000,  500000, 150000,  7350000, "DRAFT"),
            (3, m, y, 25, 200,  6500000,  300000, 100000,  6700000, "DRAFT"),
            (4, m, y, 22, 176,  7000000,       0, 350000,  6650000, "DRAFT"),
            (5, m, y, 23, 184,  6000000,  200000,       0,  6200000, "DRAFT"),
        ])

    conn.commit()
    conn.close()
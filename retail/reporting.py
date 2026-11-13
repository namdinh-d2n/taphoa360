from datetime import date, datetime
from pathlib import Path
import re
import secrets
import sqlite3
import config
from .database import reading, transaction, connect, rows, one, LOCK, SCHEMA_VERSION
from .common import day, fail, audit


def report(conn, start, end):
    start, end = day(start), day(end)
    if start > end or (date.fromisoformat(end) - date.fromisoformat(start)).days > 366:
        fail('Khoảng báo cáo tối đa 366 ngày và ngày bắt đầu không vượt ngày kết thúc')
    sold = one(conn, 'SELECT COALESCE(SUM(total_amount),0) AS amount,COUNT(*) AS count FROM orders WHERE date(created_at) BETWEEN ? AND ?', (start, end))
    refunded = one(conn, 'SELECT COALESCE(SUM(amount),0) AS amount,COUNT(*) AS count FROM returns WHERE date(created_at) BETWEEN ? AND ?', (start, end))
    costs = one(conn, "SELECT COALESCE(SUM(-m.quantity*b.cost_price),0) AS n FROM stock_movements m JOIN stock_batches b ON m.batch_id=b.id WHERE m.kind IN ('SALE','RETURN','CANCEL') AND date(m.created_at) BETWEEN ? AND ?", (start, end))['n']
    daily = rows(conn, '''SELECT day,SUM(amount) AS revenue FROM (
        SELECT date(created_at) AS day,total_amount AS amount FROM orders WHERE date(created_at) BETWEEN ? AND ?
        UNION ALL SELECT date(created_at),-amount FROM returns WHERE date(created_at) BETWEEN ? AND ?)
        GROUP BY day ORDER BY day''', (start, end, start, end))
    top = rows(conn, '''SELECT p.product_name,p.sku,SUM(-m.quantity) AS quantity FROM stock_movements m
        JOIN products p ON p.id=m.product_id WHERE m.kind IN ('SALE','RETURN','CANCEL') AND date(m.created_at) BETWEEN ? AND ?
        GROUP BY p.id ORDER BY quantity DESC LIMIT 20''', (start, end))
    methods = rows(conn, 'SELECT method,kind,SUM(amount) AS amount FROM payments WHERE date(created_at) BETWEEN ? AND ? GROUP BY method,kind', (start, end))
    missing_cost = one(conn, "SELECT COUNT(*) AS n FROM stock_movements m JOIN stock_batches b ON m.batch_id=b.id WHERE m.kind='SALE' AND b.cost_price=0 AND date(m.created_at) BETWEEN ? AND ?", (start, end))['n']
    old_orders = one(conn, 'SELECT COUNT(*) AS n FROM orders WHERE managed=0 AND date(created_at) BETWEEN ? AND ?', (start, end))['n']
    shifts = rows(conn, '''SELECT s.*,u.name AS cashier,
        COALESCE((SELECT SUM(amount) FROM payments p WHERE p.cash_shift_id=s.id AND kind IN ('SALE','REFUND')),0) AS net_sales,
        COALESCE((SELECT SUM(amount) FROM payments p WHERE p.cash_shift_id=s.id AND method='TRANSFER'),0) AS transfer_net
        FROM cash_shifts s JOIN users u ON s.user_id=u.id
        WHERE date(opened_at) BETWEEN ? AND ? ORDER BY s.id DESC''', (start, end))
    statuses = rows(conn, 'SELECT status,COUNT(*) AS count FROM orders WHERE date(created_at) BETWEEN ? AND ? GROUP BY status', (start, end))
    total_inventory = one(conn, 'SELECT COALESCE(SUM(remaining*cost_price),0) AS n FROM stock_batches')['n']
    return {'start': start, 'end': end, 'sales': sold['amount'], 'order_count': sold['count'], 'refunds': refunded['amount'], 'return_count': refunded['count'], 'net_revenue': sold['amount'] - refunded['amount'], 'cost_of_goods': round(costs), 'gross_profit': round(sold['amount'] - refunded['amount'] - costs), 'missing_cost_entries': missing_cost + old_orders, 'inventory_value': round(total_inventory), 'daily': daily, 'top_products': top, 'payments': methods, 'cash_shifts': shifts, 'statuses': statuses}


def backup_directory():
    path = Path(config.SQLITE_PATH).parent / 'backups'
    path.mkdir(exist_ok=True)
    return path


def backup_file(name):
    if not re.fullmatch(r'[a-zA-Z0-9_-]+\.db', name):
        fail('Tên bản sao lưu không hợp lệ')
    path = backup_directory() / name
    if not path.is_file() or path.is_symlink():
        fail('Không tìm thấy bản sao lưu', 404)
    return path


def make_backup(user, prefix='snapshot'):
    with LOCK:
        name = prefix + '-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3) + '.db'
        with reading() as conn:
            destination = sqlite3.connect(backup_directory() / name)
            try:
                conn.backup(destination)
            finally:
                destination.close()
        with transaction() as conn:
            audit(conn, user, 'BACKUP', name, {})
        return {'success': True, 'name': name}


def list_backups():
    return [{'name': path.name, 'size': path.stat().st_size, 'created_at': datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec='seconds')} for path in sorted(backup_directory().glob('*.db'), reverse=True) if not path.is_symlink()]


def restore_backup(user, name, confirmation):
    if confirmation != 'KHOI PHUC':
        fail('Cần nhập KHOI PHUC để xác nhận thay thế dữ liệu hiện tại')
    path = backup_file(name)
    with LOCK:
        source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            if source.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                fail('Bản sao lưu không toàn vẹn')
            try:
                version = source.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
                owners = source.execute("SELECT COUNT(*) FROM users WHERE role='owner' AND active=1").fetchone()[0]
                # Legacy imported rows can contain old foreign-key errors; reject these for restore.
                bad_keys = source.execute('PRAGMA foreign_key_check').fetchall()
            except sqlite3.DatabaseError:
                fail('Bản sao lưu không phải database Retail v3')
            if version != SCHEMA_VERSION or not owners or bad_keys:
                fail('Bản sao lưu cần đúng phiên bản, có chủ tiệm và toàn vẹn khóa ngoại')
            with reading() as current:
                for table in rows(current, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
                    name_in_schema = table['name']
                    # Names originate from this application's schema, never request data.
                    required_columns = {r['name'] for r in current.execute(f'PRAGMA table_info("{name_in_schema}")')}
                    restored_columns = {r[1] for r in source.execute(f'PRAGMA table_info("{name_in_schema}")')}
                    if not required_columns.issubset(restored_columns):
                        fail('Bản sao lưu thiếu bảng/cột cần thiết: ' + name_in_schema)
            safety = make_backup(user, 'before-restore')['name']
            target = connect()
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        with transaction() as conn:
            conn.execute('DELETE FROM sessions')
            audit(conn, None, 'RESTORE', name, {'requested_by': user['username'], 'safety_backup': safety})
    return {'success': True, 'safety_backup': safety, 'login_required': True}

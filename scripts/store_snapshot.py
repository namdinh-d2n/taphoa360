"""Export a sanitized store snapshot and restore it into a NEW local review database."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TABLES = (
    'products', 'suppliers', 'supplier_products', 'customers', 'employees',
    'users', 'shop_accounts', 'shippers', 'shifts', 'shift_schedule',
    'attendance', 'payroll', 'hr_requests', 'stock_batches', 'stock_movements',
    'purchase_receipts', 'purchase_items', 'cash_shifts', 'orders',
    'order_items', 'order_allocations', 'returns', 'return_items',
    'order_events', 'account_entries', 'delivery_zones', 'shop_settings',
    'shop_banners', 'timed_sales', 'rescue_campaigns', 'online_orders',
    'online_items', 'online_events', 'online_invoices', 'payments',
    'shop_points_ledger', 'online_cash_handovers',
)
EXCLUDED = ('errand_branches', 'errand_photos','errand_allocations','errand_events','errand_money','errand_complaints','errand_items','errand_orders', 'password_reset_otps', 'password_resets', 'sessions', 'shop_sessions', 'login_attempts', 'registrations',
            'audit_log', 'online_finance_keys', 'ai_suggestions')
REMOVED_COLUMNS = {
    'users': {'password_hash', 'email'},
    'shop_accounts': {'password_hash'},
    'online_orders': {'token_hash', 'request_key', 'request_hash', 'bank_snapshot'},
    'orders': {'request_hash'},
    'online_invoices': {'snapshot'},
}


def static_image(value):
    value = str(value or '')
    path = Path(value.lstrip('/'))
    return value if value.startswith('/static/') and '..' not in path.parts and (ROOT / path).is_file() else ''


def sanitize(table, original):
    row = {k: v for k, v in original.items() if k not in REMOVED_COLUMNS.get(table, set())}
    ident = row.get('id', 0)
    # Free-form operational notes, locations and references can contain personal data.
    for key in ('note', 'online_note', 'reason', 'review_note', 'gps_location', 'payment_note'):
        if key in row:
            row[key] = ''
    if table == 'users':
        row.update(username=f"archive_{row['role']}_{ident}", name=f'Nhan vien demo {ident}', active=0)
    elif table == 'shop_accounts':
        row.update(name=f'Khach demo {ident}', phone=f'DEMO-{ident:08d}', active=0)
    elif table == 'customers':
        row.update(name=f'Khach demo {ident}', phone='', customer_group='RETAIL')
    elif table == 'employees':
        row.update(name=f'Nhan vien demo {ident}', phone='', email='', avatar_initials='NV')
    elif table == 'suppliers':
        if not row['is_sample']:
            row['name'] = f'Nha cung cap demo {ident}'
        row.update(phone='', address='', note='Du lieu da an thong tin rieng; can nhap lai thong tin doi tac that.')
    elif table == 'shippers':
        row['name'] = f'Nhan vien giao demo {ident}'
    elif table == 'shifts':
        row['name'] = f'Ca demo {ident}'
        row['label'] = f'Ca {ident}'
    elif table == 'products':
        row['image_path'] = static_image(row['image_path'])
        row['description'] = 'Du lieu review da an thong tin rieng. Quy cach: ' + str(row['unit']) + '.'
        if not str(row['reference_source']).startswith('https://www.bachhoaxanh.com/'):
            row['reference_source'] = ''
    elif table == 'stock_batches':
        row['lot_code'] = f'DEMO-LOT-{ident}'
    elif table == 'stock_movements':
        row['reference'] = f'DEMO-MOVEMENT-{ident}'
    elif table == 'account_entries':
        if not re.fullmatch(r'(ORDER|PURCHASE|RETURN):[0-9]+', str(row['reference'])):
            row['reference'] = f'DEMO-ENTRY-{ident}'
    elif table == 'orders':
        row.update(order_code=f'DEMO-ORDER-{ident:08d}', created_by=f"Nhan vien demo {row.get('cashier_id') or 0}",
                   apartment='Dia chi giao demo' if row['fulfillment'] == 'DELIVERY' else '',
                   customer_note='', idempotency_key=f'demo-order-{ident}')
    elif table == 'order_items':
        row['shelf_location'] = ''
    elif table == 'online_orders':
        row.update(code=f'DEMO-WEB-{ident:08d}', receiver=f"Khach demo {row['account_id']}", phone='',
                   address='Dia chi giao demo da an thong tin', address_mode='MANUAL', province_code=None,
                   ward_code=None, address_line='', payment_reference=f'DEMO-PAY-{ident}' if row['payment_reference'] else '',
                   refund_reference=f'DEMO-REFUND-{ident}' if row['refund_reference'] else '')
    elif table == 'payments':
        row['reference'] = (f"DEMO-WEB-{row['online_order_id']:08d}:PAY-{ident}" if row['online_order_id']
                            else f'DEMO-PAYMENT-{ident}')
    elif table == 'shop_settings':
        row.update(store_name='Tap hoa 360 - Du lieu review', bank_bin='', bank_account='', bank_name='',
                   delivery_note='Du lieu demo; khong giao hang hay chuyen tien that.',
                   online_cashier_id=None, online_dispatcher_id=None)
    elif table == 'delivery_zones':
        row.update(name=f'Khu giao demo {ident}', eta='Thoi gian giao minh hoa')
    elif table == 'shop_banners':
        row.update(title=f'Uu dai demo {ident}', subtitle='', image_path=static_image(row['image_path']))
    elif table == 'timed_sales':
        row['name'] = f'Chuong trinh demo {ident}'
    elif table == 'rescue_campaigns':
        row['name'] = f'Combo dung som demo {ident}'
    elif table == 'online_cash_handovers':
        row['reference'] = f'DEMO-HANDOVER-{ident}'
    return row


def export_snapshot(source):
    import config
    source = Path(source).resolve()
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        version = conn.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
        from retail.database import SCHEMA_VERSION
        if version != SCHEMA_VERSION:
            raise ValueError(f'Source schema {version} differs from application schema {SCHEMA_VERSION}.')
        tables = {table: [sanitize(table, dict(row)) for row in conn.execute('SELECT * FROM "' + table + '" ORDER BY rowid')]
                  for table in TABLES}
    return {
        'format': 'taphoa360-sanitized-store', 'format_version': 1, 'schema_version': version,
        'exported_at': datetime.now(timezone(timedelta(hours=7))).isoformat(timespec='seconds'),
        'privacy': {'personal_data': 'anonymized', 'authentication': 'omitted; archived accounts disabled',
                    'bank_details': 'omitted', 'excluded_tables': list(EXCLUDED),
                    'restore_policy': 'new local database only; new owner chooses their password'},
        'counts': {table: len(records) for table, records in tables.items()}, 'tables': tables,
    }


def validate_snapshot(snapshot):
    from retail.database import SCHEMA_VERSION
    if snapshot.get('format') != 'taphoa360-sanitized-store' or snapshot.get('format_version') != 1:
        raise ValueError('Unsupported snapshot format.')
    # Newer schemas add private recovery/errand data excluded from sanitized snapshots.
    if snapshot.get('schema_version') not in {9, 10, 11, 12, SCHEMA_VERSION}:
        raise ValueError('Snapshot needs a compatible application schema.')
    if set(snapshot.get('tables', {})) != set(TABLES):
        raise ValueError('Unexpected or missing snapshot tables.')
    for table, records in snapshot['tables'].items():
        if not isinstance(records, list) or snapshot['counts'].get(table) != len(records):
            raise ValueError('Invalid count for ' + table)
        for record in records:
            if not isinstance(record, dict) or REMOVED_COLUMNS.get(table, set()).intersection(record):
                raise ValueError('Snapshot includes an unsupported credential field in ' + table)
            if any(key in record for key in ('csrf', 'password', 'api_token', 'access_token')):
                raise ValueError('Snapshot includes credentials.')
            if table in {'users', 'shop_accounts'} and record.get('active') != 0:
                raise ValueError('Historical accounts must be disabled.')
            if table == 'shop_settings' and any(record.get(key) for key in ('bank_bin', 'bank_account', 'bank_name')):
                raise ValueError('Bank configuration must be blank.')


def restore_snapshot(snapshot, target, username, name, password):
    import config
    import db
    from retail.auth import password_hash
    from retail.database import migrate
    validate_snapshot(snapshot)
    if config.APP_ENV == 'production':
        raise ValueError('Review snapshots cannot be imported in production mode.')
    if not re.fullmatch(r'[a-z0-9_.-]{3,64}', username) or not name.strip() or len(name) > 100:
        raise ValueError('Invalid new owner name or username.')
    hashed = password_hash(password)
    target = Path(target).resolve()
    if target.exists():
        raise FileExistsError('Refusing to overwrite an existing database: ' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    previous = config.SQLITE_PATH, db.SQLITE_PATH, config.SEED_DEMO, config.SQLITE_JOURNAL_MODE
    try:
        config.SQLITE_PATH = db.SQLITE_PATH = str(target)
        config.SEED_DEMO = False
        config.SQLITE_JOURNAL_MODE = 'DELETE'
        migrate()
        with closing(sqlite3.connect(target)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('PRAGMA defer_foreign_keys=ON')
            # A newly migrated database contains only defaults, never another shop's data.
            for table in (*TABLES, *EXCLUDED):
                conn.execute('DELETE FROM "' + table + '"')
            for table in TABLES:
                available = {row['name'] for row in conn.execute('PRAGMA table_info("' + table + '")')}
                for source in snapshot['tables'][table]:
                    row = dict(source)
                    ident = row.get('id', 0)
                    if table in {'users', 'shop_accounts'}:
                        row['password_hash'] = '!disabled-archived-account'
                    elif table == 'orders':
                        row['request_hash'] = hashlib.sha256(f'demo-order-{ident}'.encode()).hexdigest()
                    elif table == 'online_orders':
                        row.update(token_hash=hashlib.sha256(f'disabled-demo-tracking-{ident}'.encode()).hexdigest(),
                                   request_key=f'demo-web-{ident}', request_hash=hashlib.sha256(f'demo-web-{ident}'.encode()).hexdigest(),
                                   bank_snapshot='')
                    elif table == 'online_invoices':
                        row['snapshot'] = '{}'
                    if not set(row).issubset(available):
                        raise ValueError('Unexpected columns in ' + table)
                    columns = list(row)
                    statement = ('INSERT INTO "' + table + '" (' + ','.join('"' + c + '"' for c in columns) + ') VALUES ('
                                 + ','.join('?' for _ in columns) + ')')
                    conn.execute(statement, [row[column] for column in columns])
            if conn.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
                raise ValueError('New owner username conflicts with an archived name.')
            owner_id = conn.execute("INSERT INTO users(username,name,password_hash,role,active) VALUES(?,?,?,'owner',1)",
                                    (username, name.strip(), hashed)).lastrowid
            from retail.commerce import detail
            for invoice in conn.execute('SELECT id,online_order_id FROM online_invoices').fetchall():
                order = dict(conn.execute('SELECT * FROM online_orders WHERE id=?', (invoice['online_order_id'],)).fetchone())
                document = detail(conn, order, True)
                document.pop('bank', None)
                conn.execute('UPDATE online_invoices SET snapshot=? WHERE id=?',
                             (json.dumps(document, ensure_ascii=False), invoice['id']))
            bad = conn.execute('PRAGMA foreign_key_check').fetchall()
            if bad:
                raise ValueError('Snapshot contains invalid foreign keys: ' + str([tuple(row) for row in bad]))
            conn.commit()
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Restored database failed integrity check.')
            return {'database': str(target), 'owner_id': owner_id, 'counts': snapshot['counts']}
    finally:
        config.SQLITE_PATH, db.SQLITE_PATH, config.SEED_DEMO, config.SQLITE_JOURNAL_MODE = previous


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export')
    export.add_argument('--source')
    export.add_argument('--output', default=str(ROOT / 'data' / 'store-snapshot.json'))
    restore = commands.add_parser('restore')
    restore.add_argument('--input', default=str(ROOT / 'data' / 'store-snapshot.json'))
    restore.add_argument('--database', default=str(ROOT / '.local' / 'review-demo.db'))
    restore.add_argument('--username', default='review_owner')
    restore.add_argument('--name', default='Chu tiem demo')
    restore.add_argument('--apply', action='store_true', help='Create a new database after prompting for a new owner password')
    args = parser.parse_args()
    import config
    if args.command == 'export':
        result = export_snapshot(args.source or config.SQLITE_PATH)
        validate_snapshot(result)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(str(output))
        print(json.dumps(result['counts'], ensure_ascii=False))
        return
    snapshot = json.loads(Path(args.input).read_text(encoding='utf-8'))
    validate_snapshot(snapshot)
    print(json.dumps(snapshot['counts'], ensure_ascii=False))
    if not args.apply:
        print('Preview only. Use --apply to create a NEW local review database; existing databases are never overwritten.')
        return
    password = getpass.getpass('New owner password (10+ characters): ')
    if password != getpass.getpass('Confirm new password: '):
        raise SystemExit('Passwords do not match.')
    result = restore_snapshot(snapshot, args.database, args.username, args.name, password)
    print('Created', result['database'], 'with new owner', args.username)
    print('For this shell, set SQLITE_PATH to that path before running start_local.py; use a separate port if the shop is running.')


if __name__ == '__main__':
    main()

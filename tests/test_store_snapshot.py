"""Sanitized snapshots preserve business figures but cannot reuse live identities."""
from copy import deepcopy
from contextlib import closing
from pathlib import Path
import json
import secrets
import sqlite3
import tempfile
import unittest

import config
from scripts.store_snapshot import export_snapshot, restore_snapshot, validate_snapshot, EXCLUDED, TABLES
from retail.auth import verify


class StoreSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads((config.BASE_DIR / 'data' / 'store-snapshot.json').read_text(encoding='utf-8-sig'))

    def test_snapshot_has_business_data_and_no_credentials_or_bank_configuration(self):
        validate_snapshot(self.snapshot)
        self.assertEqual(self.snapshot['counts']['products'], 526)
        self.assertEqual(self.snapshot['counts']['suppliers'], 17)
        self.assertTrue(self.snapshot['tables']['stock_batches'])
        self.assertFalse(set(EXCLUDED).intersection(self.snapshot['tables']))
        for table, records in self.snapshot['tables'].items():
            for row in records:
                self.assertNotIn('password_hash', row)
                self.assertNotIn('token_hash', row)
                self.assertNotIn('bank_snapshot', row)
                if table in {'users', 'shop_accounts'}:
                    self.assertEqual(row['active'], 0)
                if table in {'customers', 'employees', 'suppliers', 'online_orders'}:
                    self.assertEqual(row.get('phone', ''), '')
        setting = self.snapshot['tables']['shop_settings'][0]
        self.assertEqual([setting[k] for k in ['bank_bin', 'bank_account', 'bank_name']], ['', '', ''])

    def test_restore_has_valid_foreign_keys_exact_stock_and_only_new_owner_can_login(self):
        with tempfile.TemporaryDirectory(prefix='taphoa-snapshot-test-') as folder:
            target = Path(folder) / 'review.db'
            password = secrets.token_urlsafe(24)
            restore_snapshot(self.snapshot, target, 'review_owner', 'Owner for test', password)
            with closing(sqlite3.connect(target)) as conn:
                conn.row_factory = sqlite3.Row
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(), [])
                for table in TABLES:
                    expected = self.snapshot['counts'][table] + (1 if table == 'users' else 0)
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0], expected, table)
                for table in EXCLUDED:
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0], 0, table)
                expected_stock = [(p['id'], p['price'], p['cost_price'], p['stock']) for p in self.snapshot['tables']['products']]
                actual_stock = [tuple(p) for p in conn.execute('SELECT id,price,cost_price,stock FROM products ORDER BY id')]
                self.assertEqual(actual_stock, expected_stock)
                active = conn.execute('SELECT * FROM users WHERE active=1').fetchall()
                self.assertEqual(len(active), 1)
                self.assertEqual(active[0]['username'], 'review_owner')
                self.assertTrue(verify(password, active[0]['password_hash']))
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM shop_accounts WHERE active=1').fetchone()[0], 0)
            # Exporting the restored store cannot re-export even the new owner's hash.
            roundtrip = export_snapshot(target)
            validate_snapshot(roundtrip)
            self.assertTrue(all('password_hash' not in row for row in roundtrip['tables']['users']))

    def test_restore_never_overwrites_existing_database(self):
        with tempfile.TemporaryDirectory(prefix='taphoa-snapshot-existing-') as folder:
            target = Path(folder) / 'existing.db'
            target.write_bytes(b'keep my database')
            with self.assertRaises(FileExistsError):
                restore_snapshot(self.snapshot, target, 'review_owner', 'Owner for test', secrets.token_urlsafe(24))
            self.assertEqual(target.read_bytes(), b'keep my database')

    def test_snapshot_validation_rejects_embedded_credentials(self):
        for table, field in [('users', 'password_hash'), ('shop_accounts', 'password_hash'), ('online_orders', 'token_hash')]:
            invalid = deepcopy(self.snapshot)
            invalid['tables'][table][0][field] = 'do-not-import'
            with self.assertRaises(ValueError):
                validate_snapshot(invalid)
        invalid = deepcopy(self.snapshot)
        invalid['tables']['shop_settings'][0]['bank_account'] = 'not-allowed'
        with self.assertRaises(ValueError):
            validate_snapshot(invalid)


if __name__ == '__main__':
    unittest.main()

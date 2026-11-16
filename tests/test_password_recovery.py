"""Email OTP recovery tests: isolated databases and mocked SMTP, no real mail."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import re
import smtplib
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import config
import db
from app import app
from retail.auth import verify
from retail.database import reading, transaction, one, rows, migrate, SCHEMA_VERSION
from scripts.store_snapshot import export_snapshot


class PasswordRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='taphoa-recovery-')
        self.settings = patch.multiple(config, SQLITE_PATH=str(Path(self.folder.name) / 'shop.db'),
            SEED_DEMO=False, PRODUCTION=False, SMTP_HOST='smtp.example.test', SMTP_PORT=587,
            SMTP_SECURITY='starttls', SMTP_USERNAME='sender@example.test', SMTP_PASSWORD='test-only-secret',
            SMTP_FROM='sender@example.test')
        self.settings.start()
        self.old_db = db.SQLITE_PATH
        db.SQLITE_PATH = config.SQLITE_PATH
        self.smtp = patch('retail.password_recovery.smtplib.SMTP').start()
        self.addCleanup(patch.stopall)
        self.server = self.smtp.return_value.__enter__.return_value
        self.client = TestClient(app)
        self.client.__enter__()
        self.post('/api/setup', {'username':'owner', 'name':'Owner', 'password':'old-password-123', 'email':'Owner@Example.test'})
        self.login()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.settings.stop()
        db.SQLITE_PATH = self.old_db
        self.folder.cleanup()

    def post(self, url, data, expected=200, **kwargs):
        response = self.client.post(url, json=data, **kwargs)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def login(self):
        result = self.post('/api/login', {'username':'owner', 'password':'old-password-123'})
        self.client.headers['X-CSRF-Token'] = result['csrf']
        return result

    def allow_resend(self):
        # Simulate passing the 60-second cooldown, preserving hourly limits.
        with transaction() as conn:
            conn.execute("DELETE FROM login_attempts WHERE key LIKE 'password-reset:cooldown:%'")

    def request_otp(self):
        result = self.post('/api/forgot-password', {'email':' OWNER@EXAMPLE.TEST '})
        message = self.server.send_message.call_args.args[0]
        otp = re.search(r'Mã OTP của bạn: ([0-9]{6})', message.get_content())[1]
        return result['challenge_id'], otp, result

    def verify_otp(self, challenge, otp, expected=200):
        return self.post('/api/verify-reset-otp', {'challenge_id':challenge, 'otp':otp}, expected)

    def grant(self):
        challenge, otp, _ = self.request_otp()
        return self.verify_otp(challenge, otp)['reset_token']

    def reset(self, token, expected=200):
        return self.post('/api/reset-password', {'token':token, 'password':'new-password-456', 'confirm_password':'new-password-456'}, expected)

    def test_smtp_tls_sends_six_digit_otp_and_database_contains_no_raw_secrets(self):
        challenge, otp, result = self.request_otp()
        self.assertNotIn('otp', result)
        self.assertNotIn('reset_token', result)
        self.assertEqual(result['expires_in'], 600)
        self.assertEqual(result['resend_after'], 60)
        self.smtp.assert_called_once_with(host='smtp.example.test', port=587, timeout=10)
        self.server.starttls.assert_called_once()
        self.server.login.assert_called_once_with('sender@example.test', 'test-only-secret')
        message = self.server.send_message.call_args.args[0]
        self.assertEqual(message['To'], 'owner@example.test')
        self.assertIn('10 phút', message.get_content())
        self.assertNotIn('/reset-password', message.get_content())
        self.assertNotIn(challenge, message.get_content())
        with reading() as conn:
            entry = one(conn, 'SELECT * FROM password_reset_otps')
            self.assertEqual(entry['challenge_hash'], hashlib.sha256(challenge.encode()).hexdigest())
            self.assertNotEqual(entry['otp_hash'], otp)
            self.assertNotIn(challenge, str(entry))
            self.assertAlmostEqual(entry['expires_at'] - entry['created_at'], 600)
            self.assertEqual(rows(conn, 'SELECT * FROM password_resets'), [])
            self.assertTrue(verify('old-password-123', one(conn, 'SELECT * FROM users')['password_hash']))

    def test_password_change_requires_successful_otp_verification(self):
        challenge, otp, _ = self.request_otp()
        self.reset(challenge, 400)
        self.post('/api/reset-password', {'otp':otp, 'password':'new-password-456', 'confirm_password':'new-password-456'}, 400)
        self.reset(self.verify_otp(challenge, otp)['reset_token'])

    def test_reset_revokes_sessions_all_codes_grants_and_old_password(self):
        token = self.grant()
        self.allow_resend()
        other_challenge, other_otp, _ = self.request_otp()
        other_token = self.verify_otp(other_challenge, other_otp)['reset_token']
        self.reset(token)
        self.assertEqual(self.client.get('/api/session').status_code, 401)
        self.reset(token, 400)
        self.reset(other_token, 400)
        self.verify_otp(other_challenge, other_otp, 400)
        self.post('/api/login', {'username':'owner', 'password':'old-password-123'}, 401)
        self.post('/api/login', {'username':'owner', 'password':'new-password-456'})
        with reading() as conn:
            self.assertEqual(rows(conn, 'SELECT * FROM password_resets'), [])
            self.assertEqual(rows(conn, 'SELECT * FROM password_reset_otps'), [])
            self.assertIsNotNone(one(conn, "SELECT id FROM audit_log WHERE action='RESET_PASSWORD_EMAIL'"))

    def test_unknown_disabled_and_known_email_have_same_response_shape_and_message(self):
        _, _, known = self.request_otp()
        unknown = self.post('/api/forgot-password', {'email':'unknown@example.test'})
        self.assertNotEqual(known['challenge_id'], unknown['challenge_id'])
        self.allow_resend()
        with transaction() as conn:
            conn.execute('UPDATE users SET active=0')
        disabled = self.post('/api/forgot-password', {'email':'owner@example.test'})
        for result in (unknown, disabled):
            self.assertRegex(result['challenge_id'], r'^[A-Za-z0-9_-]{43}$')
            self.assertEqual({k:v for k,v in known.items() if k!='challenge_id'}, {k:v for k,v in result.items() if k!='challenge_id'})
            self.verify_otp(result['challenge_id'], '123456', 400)
        self.assertEqual(self.server.send_message.call_count, 1)

    def test_expired_invalid_disabled_otp_cannot_issue_reset_grant(self):
        challenge, otp, _ = self.request_otp()
        with transaction() as conn:
            conn.execute('UPDATE password_reset_otps SET expires_at=?', (time.time() - 1,))
        self.verify_otp(challenge, otp, 400)
        self.verify_otp('x'*43, otp, 400)
        self.verify_otp('invalid', otp, 400)
        self.allow_resend()
        challenge, otp, _ = self.request_otp()
        with transaction() as conn:
            conn.execute('UPDATE users SET active=0')
        self.verify_otp(challenge, otp, 400)
        with reading() as conn:
            self.assertEqual(rows(conn, 'SELECT * FROM password_resets'), [])

    def test_expired_reset_grant_requires_new_otp(self):
        token = self.grant()
        with transaction() as conn:
            grant = one(conn, 'SELECT * FROM password_resets')
            self.assertEqual(grant['expires_at'] - grant['created_at'], 300)
            conn.execute('UPDATE password_resets SET expires_at=?', (time.time() - 1,))
        self.reset(token, 400)

    def test_five_incorrect_otp_attempts_lock_code_and_are_persisted(self):
        challenge, otp, _ = self.request_otp()
        wrong = '999999' if otp!='999999' else '111111'
        for attempt in range(5):
            self.verify_otp(challenge, wrong, 400)
            with reading() as conn:
                self.assertEqual(one(conn, 'SELECT attempts FROM password_reset_otps')['attempts'], attempt+1)
        self.verify_otp(challenge, otp, 400)
        with reading() as conn:
            self.assertEqual(rows(conn, 'SELECT * FROM password_resets'), [])

    def test_resend_invalidates_previous_challenge_and_preserves_leading_zeroes(self):
        with patch('retail.password_recovery.secrets.randbelow', side_effect=[123,456]):
            first, first_otp, _ = self.request_otp()
            self.assertEqual(first_otp, '000123')
            self.post('/api/forgot-password', {'email':'owner@example.test'}, 429)
            self.allow_resend()
            second, second_otp, _ = self.request_otp()
            self.assertEqual(second_otp, '000456')
        self.verify_otp(first, first_otp, 400)
        self.verify_otp(second, first_otp, 400)
        self.reset(self.verify_otp(second, second_otp)['reset_token'])

    def test_otp_verification_only_succeeds_once_under_concurrency(self):
        challenge, otp, _ = self.request_otp()
        payload = {'challenge_id':challenge, 'otp':otp}
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _:self.client.post('/api/verify-reset-otp', json=payload).status_code, range(2)))
        self.assertEqual(sorted(statuses), [200,400])
        self.verify_otp(challenge, otp, 400)
        with reading() as conn:
            self.assertEqual(len(rows(conn, 'SELECT * FROM password_resets')), 1)
            self.assertEqual(rows(conn, 'SELECT * FROM password_reset_otps'), [])

    def test_password_validation_does_not_consume_verified_grant(self):
        token = self.grant()
        for password, confirm in [('short','short'), ('x'*201,'x'*201), ('long-password-123','different')]:
            self.post('/api/reset-password', {'token':token, 'password':password, 'confirm_password':confirm}, 400)
        self.reset(token)

    def test_changed_email_invalidates_otp_and_admin_password_change_invalidates_grant(self):
        challenge, otp, _ = self.request_otp()
        self.post('/api/account-email', {'email':'new@example.test', 'current_password':'wrong'}, 403)
        self.post('/api/account-email', {'email':'new@example.test', 'current_password':'old-password-123'})
        self.verify_otp(challenge, otp, 400)
        self.post('/api/account-email', {'email':'owner@example.test', 'current_password':'old-password-123'})
        self.allow_resend()
        token = self.grant()
        response = self.client.patch('/api/v1/users/1', json={'password':'different-password-789'})
        self.assertEqual(response.status_code, 200, response.text)
        self.reset(token, 400)

    def test_regular_password_change_revokes_recovery(self):
        token = self.grant()
        self.post('/api/password', {'current_password':'old-password-123', 'password':'different-password-789'})
        self.reset(token, 400)

    def test_fingerprint_checks_changes_outside_api(self):
        challenge, otp, _ = self.request_otp()
        with transaction() as conn:
            conn.execute("UPDATE users SET email='changed@example.test'")
        self.verify_otp(challenge, otp, 400)

    def test_hourly_request_throttle_for_unknown_email_and_ip(self):
        for _ in range(5):
            self.allow_resend()
            self.post('/api/forgot-password', {'email':'unknown@example.test'})
        self.allow_resend()
        self.post('/api/forgot-password', {'email':'UNKNOWN@example.test'}, 429)
        for i in range(15):
            self.post('/api/forgot-password', {'email':f'unknown{i}@example.test'})
        self.post('/api/forgot-password', {'email':'other@example.test'}, 429)
        self.server.send_message.assert_not_called()

    def test_cross_origin_csrf_and_malformed_input_rejected(self):
        evil = {'Origin':'https://evil.example'}
        self.post('/api/forgot-password', {'email':'owner@example.test'}, 403, headers=evil)
        challenge, otp, _ = self.request_otp()
        self.post('/api/verify-reset-otp', {'challenge_id':challenge,'otp':otp}, 403, headers=evil)
        token = self.verify_otp(challenge,otp)['reset_token']
        self.post('/api/reset-password', {'token':token, 'password':'new-password-456', 'confirm_password':'new-password-456'}, 403, headers=evil)
        self.post('/api/account-email', {'email':'new@example.test', 'current_password':'old-password-123'}, 403, headers={'X-CSRF-Token':''})
        for email in ['bad', 'a..b@example.test', 'a@example', 'a@example.test\r\nBcc: other@example.test', [], '']:
            self.post('/api/forgot-password', {'email':email}, 400)
        self.reset(token)

    def test_missing_smtp_and_delivery_failure_never_expose_otp(self):
        with patch.object(config, 'SMTP_HOST', ''):
            self.post('/api/forgot-password', {'email':'owner@example.test'}, 503)
            self.post('/api/forgot-password', {'email':'unknown@example.test'}, 503)
        self.smtp.side_effect = smtplib.SMTPAuthenticationError(535, b'test secret must not be logged')
        with self.assertLogs('taphoa', level='WARNING') as logs:
            result = self.post('/api/forgot-password', {'email':'owner@example.test'})
        self.assertTrue(result['success'])
        self.assertNotIn('secret must not be logged', str(logs.output))
        with reading() as conn:
            self.assertEqual(rows(conn, 'SELECT * FROM password_reset_otps'), [])

    def test_ssl_transport_sends_otp_without_reset_link(self):
        with patch.object(config, 'SMTP_SECURITY', 'ssl'), patch('retail.password_recovery.smtplib.SMTP_SSL') as secure:
            self.post('/api/forgot-password', {'email':'owner@example.test'}, headers={'Host':'localhost'})
            server = secure.return_value.__enter__.return_value
            server.starttls.assert_not_called()
            content = server.send_message.call_args.args[0].get_content()
            self.assertRegex(content, r'Mã OTP của bạn: [0-9]{6}')
            self.assertNotIn('http', content)

    def test_concurrent_use_of_verified_grant_only_changes_password_once(self):
        token = self.grant()
        payload = {'token':token, 'password':'new-password-456', 'confirm_password':'new-password-456'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _:self.client.post('/api/reset-password',json=payload).status_code, range(2)))
        self.assertEqual(sorted(statuses), [200,400])

    def test_email_unique_and_registration_approval_carries_email(self):
        self.post('/api/v1/users', {'username':'duplicate','name':'Duplicate','password':'old-password-123','role':'cashier','email':'OWNER@example.test'},409)
        registration = self.post('/api/register', {'username':'cashier','name':'Cashier','password':'old-password-123','confirm_password':'old-password-123','role':'cashier','email':'cashier@example.test'},201)
        self.post(f"/api/v1/registrations/{registration['registration_id']}/review", {'status':'APPROVED'})
        users = self.client.get('/api/v1/users').json()
        self.assertEqual(users[1]['email'], 'cashier@example.test')
        self.post('/api/login', {'username':'cashier','password':'old-password-123'})
        self.assertEqual(self.client.get('/api/v1/users').status_code,403)
        self.assertEqual(self.client.get('/api/session').json()['email'],'cashier@example.test')

    def test_restore_and_sanitized_export_remove_recovery_secrets(self):
        token = self.grant()
        self.allow_resend()
        challenge, otp, _ = self.request_otp()
        backup = self.post('/api/v1/backups', {})['name']
        snapshot = export_snapshot(config.SQLITE_PATH)
        self.assertNotIn('password_resets', snapshot['tables'])
        self.assertNotIn('password_reset_otps', snapshot['tables'])
        self.assertNotIn('email', snapshot['tables']['users'][0])
        self.post('/api/v1/backups/' + backup + '/restore', {'confirmation':'KHOI PHUC'})
        self.reset(token,400)
        self.verify_otp(challenge,otp,400)
        self.assertEqual(self.client.get('/api/session').status_code,401)

    def test_schema_11_migration_revokes_legacy_links_preserves_data_and_is_idempotent(self):
        token = self.grant()
        with transaction() as conn:
            conn.execute('DROP TABLE password_reset_otps')
            conn.execute('DELETE FROM schema_migrations WHERE version=11')
            tables = ['products','stock_batches','stock_movements','orders','users']
            before = {table:rows(conn,'SELECT * FROM ' + table) for table in tables}
        migrate()
        migrate()
        self.reset(token,400)
        with reading() as conn:
            for table in tables:
                self.assertEqual(rows(conn,'SELECT * FROM ' + table),before[table])
            self.assertEqual(one(conn,'SELECT MAX(version) AS n FROM schema_migrations')['n'],SCHEMA_VERSION)
            self.assertEqual(rows(conn,'PRAGMA foreign_key_check'),[])
        self.assertTrue(list((Path(config.SQLITE_PATH).parent/'backups').glob('before-v11-*.db')))

    def test_schema_10_email_migration_preserves_v9_accounts(self):
        with transaction() as conn:
            conn.execute('DROP TABLE password_reset_otps')
            conn.execute('DROP TABLE password_resets')
            conn.execute('DROP INDEX users_recovery_email')
            conn.execute('ALTER TABLE users DROP COLUMN email')
            conn.execute('ALTER TABLE registrations DROP COLUMN email')
            conn.execute('DELETE FROM schema_migrations WHERE version>=10')
            before = rows(conn,'SELECT * FROM users')
        migrate()
        migrate()
        with reading() as conn:
            actual = rows(conn,'SELECT * FROM users')
            for account in actual:
                self.assertEqual(account.pop('email'),'')
            self.assertEqual(before,actual)
            self.assertEqual(rows(conn,'PRAGMA foreign_key_check'),[])

    def test_pages_show_three_steps_and_numeric_otp_input(self):
        self.assertIn('Quên mật khẩu?',self.client.get('/login/owner').text)
        page = self.client.get('/forgot-password')
        self.assertIn('name="email"',page.text)
        self.assertIn('autocomplete="one-time-code"',page.text)
        self.assertIn('name="confirm_password"',page.text)
        self.assertIn('Xác thực OTP',page.text)
        self.assertEqual(page.headers['Cache-Control'],'no-store')
        self.assertIn('name="email"',self.client.get('/register/owner').text)


if __name__ == '__main__':
    unittest.main()

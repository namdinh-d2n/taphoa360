# Email recovery: a one-time email code followed by a short-lived reset grant.
from contextlib import closing
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
import hashlib
import hmac
import logging
from pathlib import Path
import re
import secrets
import smtplib
import sqlite3
import ssl
import time

from fastapi import APIRouter, BackgroundTasks, Depends, Request
import config
from .common import audit, fail, validate_payload
from .database import add_columns, one, reading, transaction

router = APIRouter(dependencies=[Depends(validate_payload)])
OTP_TTL = 600
RESET_TTL = 300
RESEND_AFTER = 60
MAX_OTP_ATTEMPTS = 5
MESSAGE = 'Nếu email đã liên kết với tài khoản đang hoạt động, mã OTP đã được gửi. Vui lòng kiểm tra cả thư rác.'
INVALID_OTP = 'Mã OTP không đúng, đã hết hạn hoặc đã được xác thực. Mỗi mã chỉ được thử tối đa 5 lần.'
INVALID_GRANT = 'Phiên đặt lại mật khẩu không hợp lệ hoặc đã hết hạn. Vui lòng xác thực OTP lại.'


def normalize_email(value=None):
    if value is None or value == '':
        return ''
    if not isinstance(value, str):
        fail('Email không hợp lệ')
    value = value.strip().lower()
    if not value:
        return ''
    parts = value.split('@')
    if len(parts) != 2 or len(value) > 254:
        fail('Email không hợp lệ')
    local, domain = parts
    if (not 1 <= len(local) <= 64 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
            or local.startswith('.') or local.endswith('.') or '..' in local
            or '.' not in domain or len(domain) > 253
            or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in domain.split('.'))):
        fail('Email không hợp lệ')
    return value


def ensure_email_available(conn, email, user_id=0):
    if email and one(conn, 'SELECT id FROM users WHERE email=? COLLATE NOCASE AND id!=?', (email, user_id)):
        fail('Email đã được liên kết với tài khoản khác', 409)


def invalidate_resets(conn, user_id):
    conn.execute('DELETE FROM password_resets WHERE user_id=?', (user_id,))
    conn.execute('DELETE FROM password_reset_otps WHERE user_id=?', (user_id,))


def migrate_recovery():
    with reading() as conn:
        if one(conn, 'SELECT version FROM schema_migrations WHERE version=10'):
            return
        folder = Path(config.SQLITE_PATH).parent / 'backups'
        folder.mkdir(exist_ok=True)
        backup = sqlite3.connect(folder / ('before-v10-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.db'))
        try:
            conn.backup(backup)
        finally:
            backup.close()
    with transaction() as conn:
        add_columns(conn, 'users', {'email': "TEXT NOT NULL DEFAULT ''"})
        add_columns(conn, 'registrations', {'email': "TEXT NOT NULL DEFAULT ''"})
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_recovery_email ON users(email COLLATE NOCASE) WHERE email!=''")
        conn.execute('''CREATE TABLE IF NOT EXISTS password_resets (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            email TEXT NOT NULL, password_fingerprint TEXT NOT NULL,
            created_at REAL NOT NULL, expires_at REAL NOT NULL)''')
        conn.execute('CREATE INDEX IF NOT EXISTS password_resets_user ON password_resets(user_id)')
        conn.execute('INSERT INTO schema_migrations(version) VALUES (10)')


def migrate_recovery_otp():
    with reading() as conn:
        if one(conn, 'SELECT version FROM schema_migrations WHERE version=11'):
            return
        folder = Path(config.SQLITE_PATH).parent / 'backups'
        folder.mkdir(exist_ok=True)
        backup = sqlite3.connect(folder / ('before-v11-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.db'))
        try:
            conn.backup(backup)
        finally:
            backup.close()
    with transaction() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS password_reset_otps (
            challenge_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            email TEXT NOT NULL, password_fingerprint TEXT NOT NULL, otp_hash TEXT NOT NULL,
            created_at REAL NOT NULL, expires_at REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 5))""")
        conn.execute('CREATE INDEX IF NOT EXISTS password_reset_otps_user ON password_reset_otps(user_id)')
        # Existing email-link tokens cannot bypass the new OTP verification step.
        conn.execute('DELETE FROM password_resets')
        conn.execute('INSERT INTO schema_migrations(version) VALUES (11)')


def fingerprint(account):
    return hashlib.sha256((account['password_hash'] + '\0' + account['email']).encode()).hexdigest()


def configured():
    return bool(config.SMTP_HOST and config.SMTP_FROM
                and bool(config.SMTP_USERNAME) == bool(config.SMTP_PASSWORD))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def otp_digest(challenge, otp):
    # The random client challenge is not stored raw, preventing offline code guessing
    # from the database alone as well as separating equal codes across requests.
    return hmac.new(challenge.encode(), otp.encode(), hashlib.sha256).hexdigest()


def throttle(request, email):
    address = request.client.host if request.client else ''
    limits = [('ip', address, 20), ('email', email, 5)]
    stamp = time.time()
    # Unknown addresses consume the same allowances and cooldown as known addresses.
    with transaction() as conn:
        cooldown_key = 'password-reset:cooldown:' + digest(email)
        cooldown = one(conn, 'SELECT * FROM login_attempts WHERE key=?', (cooldown_key,))
        if cooldown and cooldown['locked_until'] > stamp:
            fail('Vui lòng đợi 60 giây giữa hai lần gửi mã OTP.', 429)
        for kind, value, maximum in limits:
            key = 'password-reset:' + kind + ':' + digest(value)
            attempt = one(conn, 'SELECT * FROM login_attempts WHERE key=?', (key,))
            if attempt and attempt['locked_until'] > stamp and attempt['failures'] >= maximum:
                fail('Đã gửi quá nhiều yêu cầu. Vui lòng thử lại sau một giờ.', 429)
        for kind, value, maximum in limits:
            key = 'password-reset:' + kind + ':' + digest(value)
            attempt = one(conn, 'SELECT * FROM login_attempts WHERE key=?', (key,))
            count = attempt['failures'] + 1 if attempt and attempt['locked_until'] > stamp else 1
            until = attempt['locked_until'] if attempt and attempt['locked_until'] > stamp else stamp + 3600
            conn.execute('INSERT OR REPLACE INTO login_attempts(key,failures,locked_until) VALUES (?,?,?)', (key, count, until))
        conn.execute('INSERT OR REPLACE INTO login_attempts(key,failures,locked_until) VALUES (?,1,?)', (cooldown_key, stamp + RESEND_AFTER))


def send_recovery_otp(email, username, otp, challenge, database_path):
    message = EmailMessage()
    message['Subject'] = 'Mã OTP khôi phục mật khẩu Tạp hóa 360'
    message['From'] = formataddr(('Tạp hóa 360', config.SMTP_FROM))
    message['To'] = email
    message.set_content(f'Xin chào {username},\n\nBạn đã yêu cầu khôi phục mật khẩu Tạp hóa 360.\n\nMã OTP của bạn: {otp}\n\nMã có hiệu lực 10 phút, chỉ dùng được một lần và tối đa 5 lần nhập sai.\nQuay lại trang khôi phục, nhập mã OTP và xác thực trước khi đặt mật khẩu mới.\nKhông chia sẻ mã này với người khác. Nếu bạn không yêu cầu, hãy bỏ qua email này.\n')
    context = ssl.create_default_context()
    try:
        smtp_class = smtplib.SMTP_SSL if config.SMTP_SECURITY == 'ssl' else smtplib.SMTP
        options = {'host': config.SMTP_HOST, 'port': config.SMTP_PORT, 'timeout': 10}
        if config.SMTP_SECURITY == 'ssl':
            options['context'] = context
        with smtp_class(**options) as server:
            if config.SMTP_SECURITY == 'starttls':
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
            if config.SMTP_USERNAME:
                server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.send_message(message)
    except (OSError, smtplib.SMTPException):
        logging.getLogger('taphoa').warning('Không gửi được email khôi phục; kiểm tra kết nối và cấu hình SMTP.')
        # Keep codes, challenges and SMTP errors out of logs. Clean only this request.
        with closing(sqlite3.connect(database_path, timeout=20)) as conn:
            with conn:
                conn.execute('DELETE FROM password_reset_otps WHERE challenge_hash=?', (digest(challenge),))


@router.post('/api/forgot-password')
def forgot_password(data: dict, request: Request, background: BackgroundTasks):
    from .auth import same_origin
    same_origin(request)
    email = normalize_email(data.get('email'))
    if not email:
        fail('Vui lòng nhập email khôi phục')
    if not configured():
        fail('Chức năng gửi email chưa sẵn sàng. Vui lòng liên hệ chủ tiệm để cấu hình gửi thư.', 503)
    throttle(request, email)
    # Return an indistinguishable opaque challenge even for an unknown/disabled account.
    challenge = secrets.token_urlsafe(32)
    with transaction() as conn:
        stamp = time.time()
        conn.execute('DELETE FROM password_reset_otps WHERE expires_at<=?', (stamp,))
        conn.execute('DELETE FROM password_resets WHERE expires_at<=?', (stamp,))
        account = one(conn, 'SELECT * FROM users WHERE email=? COLLATE NOCASE AND active=1', (email,))
        if account:
            otp = f'{secrets.randbelow(1_000_000):06d}'
            conn.execute('DELETE FROM password_reset_otps WHERE user_id=?', (account['id'],))
            conn.execute("""INSERT INTO password_reset_otps
                (challenge_hash,user_id,email,password_fingerprint,otp_hash,created_at,expires_at)
                VALUES (?,?,?,?,?,?,?)""",
                (digest(challenge), account['id'], email, fingerprint(account), otp_digest(challenge, otp), stamp, stamp + OTP_TTL))
            background.add_task(send_recovery_otp, email, account['username'], otp, challenge, config.SQLITE_PATH)
    return {'success': True, 'message': MESSAGE, 'challenge_id': challenge,
            'expires_in': OTP_TTL, 'resend_after': RESEND_AFTER}


@router.post('/api/verify-reset-otp')
def verify_reset_otp(data: dict, request: Request):
    from .auth import same_origin
    same_origin(request)
    challenge, otp = data.get('challenge_id'), data.get('otp')
    if not isinstance(challenge, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', challenge):
        fail(INVALID_OTP)
    if not isinstance(otp, str) or not re.fullmatch(r'[0-9]{6}', otp):
        fail('Vui lòng nhập mã OTP gồm đúng 6 chữ số')
    grant = None
    with transaction() as conn:
        stamp = time.time()
        pending = one(conn, 'SELECT * FROM password_reset_otps WHERE challenge_hash=?', (digest(challenge),))
        account = one(conn, 'SELECT * FROM users WHERE id=? AND active=1', (pending['user_id'],)) if pending else None
        if (account and pending['expires_at'] > stamp and pending['attempts'] < MAX_OTP_ATTEMPTS
                and pending['email'] == account['email']
                and hmac.compare_digest(pending['password_fingerprint'], fingerprint(account))):
            if hmac.compare_digest(pending['otp_hash'], otp_digest(challenge, otp)):
                grant = secrets.token_urlsafe(32)
                conn.execute('DELETE FROM password_reset_otps WHERE challenge_hash=?', (digest(challenge),))
                conn.execute('INSERT INTO password_resets VALUES (?,?,?,?,?,?)',
                    (digest(grant), account['id'], account['email'], fingerprint(account), stamp, stamp + RESET_TTL))
            else:
                conn.execute('UPDATE password_reset_otps SET attempts=attempts+1 WHERE challenge_hash=?', (digest(challenge),))
    # Raise after commit so incorrect guesses cannot roll back the attempt counter.
    if not grant:
        fail(INVALID_OTP)
    return {'success': True, 'reset_token': grant, 'expires_in': RESET_TTL,
            'message': 'Đã xác thực OTP. Bạn có thể đặt mật khẩu mới.'}


@router.post('/api/reset-password')
def reset_password(data: dict, request: Request):
    from .auth import password_hash, same_origin
    same_origin(request)
    token = data.get('token')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        fail(INVALID_GRANT)
    if not isinstance(data.get('password'), str) or data['password'] != data.get('confirm_password'):
        fail('Mật khẩu xác nhận không khớp')
    if not 10 <= len(data['password']) <= 200:
        fail('Mật khẩu cần từ 10 đến 200 ký tự')
    with transaction() as conn:
        reset = one(conn, 'SELECT * FROM password_resets WHERE token_hash=? AND expires_at>?', (digest(token), time.time()))
        account = one(conn, 'SELECT * FROM users WHERE id=? AND active=1', (reset['user_id'],)) if reset else None
        if (not account or reset['email'] != account['email']
                or not hmac.compare_digest(reset['password_fingerprint'], fingerprint(account))):
            fail(INVALID_GRANT)
        hashed = password_hash(data['password'])
        conn.execute('UPDATE users SET password_hash=? WHERE id=?', (hashed, account['id']))
        conn.execute('DELETE FROM sessions WHERE user_id=?', (account['id'],))
        invalidate_resets(conn, account['id'])
        client = request.client.host if request.client else ''
        login_key = digest(account['username'] + '|' + client)
        conn.execute('DELETE FROM login_attempts WHERE key=?', (login_key,))
        audit(conn, account, 'RESET_PASSWORD_EMAIL', account['id'], {})
    return {'success': True, 'message': 'Đã đặt lại mật khẩu. Vui lòng đăng nhập bằng mật khẩu mới.'}

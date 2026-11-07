import hashlib
import hmac
import re
import secrets
import time
import config
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request, Response
from .database import reading, transaction, one, rows
from .common import fail, required, audit, record, now, validate_payload
from .access import home_for

router = APIRouter(dependencies=[Depends(validate_payload)])
ROLES = {'owner', 'cashier', 'inventory', 'shipper'}


def password_hash(password):
    if not isinstance(password, str) or not 10 <= len(password) <= 200:
        fail('Mật khẩu cần từ 10 đến 200 ký tự')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def verify(password, stored):
    try:
        _, rounds, salt, expected = stored.split('$')
        actual = hashlib.pbkdf2_hmac('sha256', str(password).encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def same_origin(request):
    origin = request.headers.get('origin')
    parsed = urlparse(origin) if origin else None
    expected = urlparse(config.PUBLIC_ORIGIN) if config.PUBLIC_ORIGIN else request.url
    if parsed and (parsed.scheme != expected.scheme or parsed.netloc != expected.netloc):
        fail('Nguồn yêu cầu không được phép', 403)


def current_user(request: Request):
    bearer = request.headers.get('authorization', '')
    token = bearer[7:] if bearer.startswith('Bearer ') else request.cookies.get('taphoa_session', '')
    with reading() as conn:
        user = one(conn, '''SELECT u.id,u.username,u.name,u.role,u.employee_id,s.csrf FROM sessions s
            JOIN users u ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1''', (hashlib.sha256(token.encode()).hexdigest(), time.time()))
    if not user:
        fail('Vui lòng đăng nhập', 401)
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        same_origin(request)
        if not bearer.startswith('Bearer ') and not hmac.compare_digest(request.headers.get('x-csrf-token', '').encode(), user['csrf'].encode()):
            fail('Phiên thao tác không hợp lệ. Hãy tải lại trang.', 403)
    return user


def require(*roles):
    def dependency(user=Depends(current_user)):
        if user['role'] not in {'owner', *roles}:
            fail('Bạn không có quyền thực hiện thao tác này', 403)
        return user
    return dependency


def validate_account(data):
    username = required(data, 'username', 'Tên đăng nhập', 64).lower()
    if not re.fullmatch(r'[a-z0-9_.-]{3,64}', username):
        fail('Tên đăng nhập gồm 3–64 ký tự chữ thường, số, dấu chấm, gạch ngang hoặc gạch dưới')
    return username, required(data, 'name', 'Họ tên', 100), password_hash(data.get('password'))


@router.get('/api/setup-status')
def setup_status():
    with reading() as conn:
        return {'required': not one(conn, 'SELECT id FROM users LIMIT 1')}


@router.post('/api/setup')
def setup(data: dict, request: Request):
    same_origin(request)
    if config.SETUP_TOKEN and not hmac.compare_digest(str(data.get('setup_token', '')).encode(), config.SETUP_TOKEN.encode()):
        fail('Mã thiết lập cửa hàng không đúng', 403)
    username, name, hashed = validate_account(data)
    with transaction() as conn:
        if one(conn, 'SELECT id FROM users LIMIT 1'):
            fail('Hệ thống đã có tài khoản chủ tiệm', 409)
        ident = conn.execute("INSERT INTO users(username,name,password_hash,role) VALUES (?,?,?,'owner')", (username, name, hashed)).lastrowid
        audit(conn, {'id': ident}, 'SETUP', 'users', {'username': username})
    return {'success': True}


@router.post('/api/register', status_code=201)
def register(data: dict, request: Request):
    same_origin(request)
    role = data.get('role')
    if not isinstance(role, str) or role not in ROLES:
        fail('Vui lòng chọn vai trò hợp lệ')
    if not isinstance(data.get('password'), str) or data.get('password') != data.get('confirm_password'):
        fail('Mật khẩu xác nhận không khớp')
    phone = str(data.get('phone') or '').strip()
    if len(phone) > 30 or (phone and not re.fullmatch(r'[+0-9 ()\-]{7,30}', phone)):
        fail('Số điện thoại không hợp lệ')
    # Separate rate-limit transaction so rejected attempts also consume the allowance.
    key = 'registration:' + hashlib.sha256((request.client.host if request.client else '').encode()).hexdigest()
    with transaction() as conn:
        attempt = one(conn, 'SELECT * FROM login_attempts WHERE key=?', (key,))
        if attempt and attempt['locked_until'] > time.time() and attempt['failures'] >= 10:
            fail('Đã gửi quá nhiều yêu cầu đăng ký. Vui lòng thử lại sau một giờ.', 429)
        count = attempt['failures'] + 1 if attempt and attempt['locked_until'] > time.time() else 1
        expires = attempt['locked_until'] if attempt and attempt['locked_until'] > time.time() else time.time() + 3600
        conn.execute('INSERT OR REPLACE INTO login_attempts(key,failures,locked_until) VALUES (?,?,?)', (key, count, expires))
    username, name, hashed = validate_account(data)
    with transaction() as conn:
        if not one(conn, "SELECT id FROM users WHERE role='owner' AND active=1"):
            fail('Cửa hàng chưa được thiết lập. Hãy tạo tài khoản chủ tiệm đầu tiên tại trang thiết lập.', 409)
        if one(conn, 'SELECT id FROM users WHERE username=?', (username,)) or one(conn, "SELECT id FROM registrations WHERE username=? AND status='PENDING'", (username,)):
            fail('Tên đăng nhập đã được sử dụng hoặc đang chờ duyệt', 409)
        ident = conn.execute('INSERT INTO registrations(username,name,phone,password_hash,role) VALUES (?,?,?,?,?)', (username, name, phone, hashed, role)).lastrowid
        audit(conn, None, 'REGISTER_REQUEST', ident, {'username': username, 'role': role})
    return {'success': True, 'registration_id': ident, 'status': 'PENDING', 'role': role,
            'message': 'Đã gửi đăng ký. Bạn có thể đăng nhập sau khi chủ tiệm duyệt tài khoản.'}


@router.get('/api/v1/registrations')
def registrations(user=Depends(require())):
    with reading() as conn:
        return rows(conn, '''SELECT r.id,r.username,r.name,r.phone,r.role,r.status,r.created_at,
            r.reviewed_at,r.review_note,r.user_id,u.name AS reviewer FROM registrations r
            LEFT JOIN users u ON r.reviewed_by=u.id ORDER BY r.status='PENDING' DESC,r.id DESC LIMIT 200''')


@router.post('/api/v1/registrations/{ident}/review')
def review_registration(ident: int, data: dict, user=Depends(require())):
    status = data.get('status')
    if status not in ('APPROVED', 'REJECTED'):
        fail('Trạng thái duyệt không hợp lệ')
    note = str(data.get('note') or '').strip()
    if len(note) > 500 or (status == 'REJECTED' and not note):
        fail('Cần lý do từ chối, tối đa 500 ký tự')
    with transaction() as conn:
        registration = record(conn, 'registrations', ident)
        if registration['status'] != 'PENDING':
            fail('Đăng ký này đã được xử lý', 409)
        user_id = None
        if status == 'APPROVED':
            if one(conn, 'SELECT id FROM users WHERE username=?', (registration['username'],)):
                fail('Tên đăng nhập đã tồn tại. Hãy từ chối đăng ký này.', 409)
            employee_id = data.get('employee_id') or None
            if employee_id:
                employee = record(conn, 'employees', employee_id)
                if employee['status'] != 'ACTIVE' or one(conn, 'SELECT id FROM users WHERE employee_id=?', (employee_id,)):
                    fail('Hồ sơ nhân viên đã ngừng hoạt động hoặc đã liên kết tài khoản khác', 409)
            else:
                roles = {'owner':'Chu tiem', 'cashier':'Thu ngan', 'inventory':'Kiem kho', 'shipper':'Tai xe giao hang'}
                initials = ''.join(word[0].upper() for word in registration['name'].split()[:2])
                employee_id = conn.execute('''INSERT INTO employees(name,role,phone,base_salary,hourly_rate,avatar_initials,status)
                    VALUES (?,?,?,0,0,?,'ACTIVE')''', (registration['name'], roles[registration['role']], registration['phone'], initials)).lastrowid
            user_id = conn.execute('INSERT INTO users(username,name,password_hash,role,employee_id) VALUES (?,?,?,?,?)', (registration['username'], registration['name'], registration['password_hash'], registration['role'], employee_id)).lastrowid
        conn.execute("UPDATE registrations SET status=?,reviewed_by=?,reviewed_at=?,review_note=?,user_id=?,password_hash='' WHERE id=?", (status, user['id'], now(), note, user_id, ident))
        audit(conn, user, 'REVIEW_REGISTRATION', ident, {'status': status, 'role': registration['role'], 'user_id': user_id, 'note': note})
    return {'success': True, 'status': status, 'user_id': user_id}


@router.post('/api/login')
def login(data: dict, request: Request, response: Response):
    same_origin(request)
    selected_role = data.get('role')
    if selected_role is not None and (not isinstance(selected_role, str) or selected_role not in ROLES):
        fail('Vai trò đăng nhập không hợp lệ')
    username = str(data.get('username', '')).strip().lower()[:64]
    password = str(data.get('password', ''))[:200]
    key = hashlib.sha256((username + '|' + (request.client.host if request.client else '')).encode()).hexdigest()
    valid = False
    with transaction() as conn:
        attempt = one(conn, 'SELECT * FROM login_attempts WHERE key=?', (key,))
        if attempt and attempt['locked_until'] > time.time():
            fail('Thử đăng nhập quá nhiều lần. Vui lòng đợi 5 phút.', 429)
        user = one(conn, 'SELECT * FROM users WHERE username=?', (username,))
        pending = one(conn, "SELECT password_hash FROM registrations WHERE username=? AND status='PENDING'", (username,)) if not user else None
        stored = user['password_hash'] if user else pending['password_hash'] if pending else 'pbkdf2_sha256$600000$00000000000000000000000000000000$' + '0' * 64
        password_matches = verify(password, stored)
        if password_matches and pending:
            fail('Tài khoản đang chờ chủ tiệm duyệt đăng ký. Vui lòng quay lại sau khi được duyệt.', 403)
        if password_matches and user and not user['active']:
            fail('Tài khoản đã bị khóa. Vui lòng liên hệ chủ tiệm.', 403)
        valid = password_matches and user is not None and user['active']
        if not valid:
            count = (attempt['failures'] if attempt and attempt['locked_until'] == 0 else 0) + 1
            conn.execute('INSERT OR REPLACE INTO login_attempts(key,failures,locked_until) VALUES (?,?,?)', (key, count, time.time() + 300 if count >= 5 else 0))
        else:
            if selected_role is not None and selected_role != user['role']:
                fail('Tài khoản không thuộc vai trò đã chọn. Hãy chọn đúng trang đăng nhập.', 403)
            conn.execute('DELETE FROM login_attempts WHERE key=?', (key,))
            conn.execute('DELETE FROM sessions WHERE expires_at<?', (time.time(),))
            token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            conn.execute('INSERT INTO sessions VALUES (?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user['id'], csrf, time.time() + 28800))
            audit(conn, user, 'LOGIN', user['id'], {})
    if not valid:
        fail('Tên đăng nhập hoặc mật khẩu chưa đúng', 401)
    response.set_cookie('taphoa_session', token, httponly=True, secure=config.COOKIE_SECURE or request.url.scheme == 'https', samesite='lax', max_age=28800)
    return {'success': True, 'csrf': csrf, 'token': token, 'role': user['role'], 'redirect_url': home_for(user['role'])}


@router.get('/api/session')
def session(user=Depends(current_user)):
    return user


@router.post('/api/password')
def change_password(data: dict, user=Depends(current_user)):
    with transaction() as conn:
        account = record(conn, 'users', user['id'])
        if not verify(data.get('current_password', ''), account['password_hash']):
            fail('Mật khẩu hiện tại không đúng', 403)
        hashed = password_hash(data.get('password'))
        conn.execute('UPDATE users SET password_hash=? WHERE id=?', (hashed, user['id']))
        conn.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
        audit(conn, user, 'CHANGE_PASSWORD', user['id'], {})
    return {'success': True}


@router.post('/api/logout')
def logout(request: Request, response: Response, user=Depends(current_user)):
    with transaction() as conn:
        conn.execute('DELETE FROM sessions WHERE user_id=? AND csrf=?', (user['id'], user['csrf']))
    response.delete_cookie('taphoa_session')
    return {'success': True}


@router.get('/api/v1/users')
def users(user=Depends(require())):
    with reading() as conn:
        return rows(conn, 'SELECT id,username,name,role,employee_id,active FROM users ORDER BY id')


@router.post('/api/v1/users')
def create_user(data: dict, user=Depends(require())):
    username, name, hashed = validate_account(data)
    role = data.get('role', 'cashier')
    if role not in ROLES:
        fail('Vai trò không hợp lệ')
    with transaction() as conn:
        if one(conn, 'SELECT id FROM users WHERE username=?', (username,)) or one(conn, "SELECT id FROM registrations WHERE username=? AND status='PENDING'", (username,)):
            fail('Tên đăng nhập đã tồn tại hoặc đang chờ duyệt đăng ký', 409)
        employee = data.get('employee_id') or None
        if employee:
            profile = record(conn, 'employees', employee)
            if profile['status'] != 'ACTIVE' or one(conn, 'SELECT id FROM users WHERE employee_id=?', (employee,)):
                fail('Hồ sơ nhân viên đã ngừng hoạt động hoặc đã liên kết tài khoản khác', 409)
        ident = conn.execute('INSERT INTO users(username,name,password_hash,role,employee_id) VALUES (?,?,?,?,?)', (username, name, hashed, role, employee)).lastrowid
        audit(conn, user, 'CREATE_USER', ident, {'username': username, 'role': role})
    return {'id': ident, 'success': True}


@router.patch('/api/v1/users/{ident}')
def update_user(ident: int, data: dict, user=Depends(require())):
    with transaction() as conn:
        account = record(conn, 'users', ident)
        role = data.get('role', account['role'])
        active = 1 if data.get('active', account['active']) else 0
        if role not in ROLES:
            fail('Vai trò không hợp lệ')
        if account['role'] == 'owner' and (role != 'owner' or not active):
            if not one(conn, "SELECT id FROM users WHERE role='owner' AND active=1 AND id!=?", (ident,)):
                fail('Phải giữ ít nhất một chủ tiệm đang hoạt động')
        employee = data.get('employee_id', account['employee_id']) or None
        if employee:
            profile = record(conn, 'employees', employee)
            if profile['status'] != 'ACTIVE' or one(conn, 'SELECT id FROM users WHERE employee_id=? AND id!=?', (employee, ident)):
                fail('Hồ sơ nhân viên đã ngừng hoạt động hoặc đã liên kết tài khoản khác', 409)
        hashed = password_hash(data['password']) if data.get('password') else account['password_hash']
        conn.execute('UPDATE users SET role=?,active=?,employee_id=?,password_hash=? WHERE id=?', (role, active, employee, hashed, ident))
        conn.execute('DELETE FROM sessions WHERE user_id=?', (ident,))
        audit(conn, user, 'UPDATE_USER', ident, {'role': role, 'active': active})
    return {'success': True}

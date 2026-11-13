from datetime import date, datetime, timedelta
import calendar
from .database import rows, one
from .common import fail, required, number, money, rounded, day, audit, record, now


def save_employee(conn, user, data, ident=None):
    values = {**(record(conn, 'employees', ident) if ident else {}), **data}
    name = required(values, 'name', 'Họ tên', 100)
    mode = values.get('salary_mode', 'MONTHLY')
    status = values.get('status', 'ACTIVE')
    if mode not in {'MONTHLY', 'HOURLY'} or status not in {'ACTIVE', 'INACTIVE'}:
        fail('Loại lương hoặc trạng thái không hợp lệ')
    working_days = number(values.get('working_days', 26), 'Ngày công chuẩn', minimum=1, integer=True)
    if working_days > 31:
        fail('Ngày công chuẩn tối đa 31')
    fields = (name, str(values.get('role', 'Thu ngan'))[:60], str(values.get('phone', ''))[:30], money(values.get('base_salary', 0)), money(values.get('hourly_rate', 0)), ''.join(w[0] for w in name.split()[:2]).upper(), status, mode, working_days)
    if ident:
        conn.execute('UPDATE employees SET name=?,role=?,phone=?,base_salary=?,hourly_rate=?,avatar_initials=?,status=?,salary_mode=?,working_days=? WHERE id=?', (*fields, ident))
    else:
        ident = conn.execute('INSERT INTO employees(name,role,phone,base_salary,hourly_rate,avatar_initials,status,salary_mode,working_days) VALUES (?,?,?,?,?,?,?,?,?)', fields).lastrowid
    audit(conn, user, 'SAVE_EMPLOYEE', ident, {'name': name, 'salary_mode': mode})
    return {'success': True, 'id': ident}


def save_shift(conn, user, data, ident=None):
    merged = {**(record(conn, 'shifts', ident) if ident else {}), **data}
    name = required(merged, 'name', 'Tên ca', 50)
    try:
        start = datetime.strptime(merged['start_time'], '%H:%M').strftime('%H:%M')
        end = datetime.strptime(merged['end_time'], '%H:%M').strftime('%H:%M')
    except (ValueError, KeyError, TypeError):
        fail('Giờ ca phải theo dạng HH:MM')
    if start == end:
        fail('Giờ bắt đầu và kết thúc phải khác nhau')
    if ident:
        previous = record(conn, 'shifts', ident)
        if (previous['start_time'], previous['end_time']) != (start, end) and one(conn, 'SELECT id FROM shift_schedule WHERE shift_id=?', (ident,)):
            fail('Ca đã có lịch phân công. Hãy tạo ca mới để giữ lịch sử giờ làm.', 409)
        conn.execute('UPDATE shifts SET name=?,start_time=?,end_time=? WHERE id=?', (name, start, end, ident))
    else:
        ident = conn.execute('INSERT INTO shifts(name,start_time,end_time) VALUES (?,?,?)', (name, start, end)).lastrowid
    audit(conn, user, 'SAVE_SHIFT', ident, {'start': start, 'end': end})
    return {'success': True, 'id': ident}


def payroll_locked(conn, employee_id, work_date):
    d = date.fromisoformat(work_date)
    if one(conn, "SELECT id FROM payroll WHERE employee_id=? AND month=? AND year=? AND status='APPROVED'", (employee_id, d.month, d.year)):
        fail('Bảng lương tháng này đã duyệt; không thể sửa công hoặc lịch ca', 409)


def validate_schedule(conn, employee_id, shift, work_date):
    if not shift['start_time']:
        return
    start = datetime.fromisoformat(work_date + 'T' + shift['start_time'])
    end = datetime.fromisoformat(work_date + 'T' + shift['end_time'])
    if end <= start:
        end += timedelta(days=1)
    adjacent = rows(conn, '''SELECT s.*,sc.work_date FROM shift_schedule sc JOIN shifts s ON sc.shift_id=s.id
        WHERE employee_id=? AND work_date!=? AND work_date BETWEEN ? AND ? AND s.start_time!='' ''',
        (employee_id, work_date, (start.date()-timedelta(days=1)).isoformat(), (start.date()+timedelta(days=1)).isoformat()))
    for scheduled in adjacent:
        other_start = datetime.fromisoformat(scheduled['work_date'] + 'T' + scheduled['start_time'])
        other_end = datetime.fromisoformat(scheduled['work_date'] + 'T' + scheduled['end_time'])
        if other_end <= other_start:
            other_end += timedelta(days=1)
        if start < other_end and other_start < end:
            fail('Ca mới bị trùng giờ với ca qua đêm hoặc ca ngày kế bên', 409)


def assign_shift(conn, user, data):
    employee = record(conn, 'employees', data.get('employee_id'))
    shift = record(conn, 'shifts', data.get('shift_id'))
    work_date = day(data.get('work_date'))
    if employee['status'] != 'ACTIVE':
        fail('Nhân viên đã ngừng hoạt động')
    payroll_locked(conn, employee['id'], work_date)
    if one(conn, 'SELECT id FROM attendance WHERE employee_id=? AND work_date=? AND check_in IS NOT NULL', (employee['id'], work_date)):
        fail('Không thay ca đã có chấm công', 409)
    validate_schedule(conn, employee['id'], shift, work_date)
    conn.execute('DELETE FROM shift_schedule WHERE employee_id=? AND work_date=?', (employee['id'], work_date))
    conn.execute('INSERT INTO shift_schedule(employee_id,shift_id,work_date) VALUES (?,?,?)', (employee['id'], shift['id'], work_date))
    audit(conn, user, 'ASSIGN_SHIFT', employee['id'], {'date': work_date, 'shift': shift['id']})
    return {'success': True}


def employee_scope(user, requested=None):
    if user['role'] == 'owner':
        if not requested:
            fail('Chọn nhân viên')
        return requested
    if not user['employee_id'] or (requested and int(requested) != user['employee_id']):
        fail('Tài khoản cần được liên kết với hồ sơ nhân viên của bạn', 403)
    return user['employee_id']


def clock(conn, user, data):
    employee_id = employee_scope(user, data.get('employee_id'))
    employee = record(conn, 'employees', employee_id)
    if employee['status'] != 'ACTIVE':
        fail('Nhân viên đã nghỉ việc')
    action = data.get('action', 'IN')
    current = datetime.now()
    if action == 'OUT':
        entry = one(conn, '''SELECT * FROM attendance WHERE employee_id=? AND check_in_at IS NOT NULL AND check_out_at IS NULL ORDER BY id DESC LIMIT 1''', (employee_id,))
        if not entry:
            fail('Chưa có lần vào ca đang mở', 409)
        payroll_locked(conn, employee_id, entry['work_date'])
        hours = (current - datetime.fromisoformat(entry['check_in_at'])).total_seconds() / 3600
        if not 0 <= hours <= 24:
            fail('Ca vượt 24 giờ; chủ tiệm cần chỉnh công trước khi chốt')
        conn.execute('UPDATE attendance SET check_out=?,check_out_at=?,hours_worked=? WHERE id=?', (current.strftime('%H:%M'), now(), round(hours, 4), entry['id']))
        audit(conn, user, 'CLOCK_OUT', entry['id'], {'hours': hours})
    elif action == 'IN':
        if one(conn, 'SELECT id FROM attendance WHERE employee_id=? AND check_in_at IS NOT NULL AND check_out_at IS NULL', (employee_id,)):
            fail('Bạn đang có ca chưa chấm ra', 409)
        candidates = rows(conn, '''SELECT s.*,sc.work_date FROM shift_schedule sc JOIN shifts s ON s.id=sc.shift_id
            WHERE employee_id=? AND work_date IN (?,?) AND s.start_time!='' ORDER BY work_date''', (employee_id, (current.date() - timedelta(days=1)).isoformat(), current.date().isoformat()))
        chosen = None
        for sched in candidates:
            start = datetime.fromisoformat(sched['work_date'] + 'T' + sched['start_time'])
            end = datetime.fromisoformat(sched['work_date'] + 'T' + sched['end_time'])
            if end <= start:
                end += timedelta(days=1)
            if start - timedelta(hours=2) <= current <= end:
                chosen = (sched, start)
                break
        if not chosen:
            fail('Chưa có ca phù hợp thời điểm hiện tại; liên hệ chủ tiệm để xếp ca')
        sched, start = chosen
        payroll_locked(conn, employee_id, sched['work_date'])
        old = one(conn, 'SELECT * FROM attendance WHERE employee_id=? AND work_date=?', (employee_id, sched['work_date']))
        if old and (old['check_in'] or old['check_in_at']):
            fail('Ngày này đã có chấm công', 409)
        late = max(0, int((current - start).total_seconds() // 60))
        status = 'DI_TRE' if late > 5 else 'DUNG_GIO'
        gps = str(data.get('gps_location', ''))[:100]
        if old:
            conn.execute('DELETE FROM attendance WHERE id=?', (old['id'],))
        ident = conn.execute('INSERT INTO attendance(employee_id,work_date,check_in,check_in_at,status,gps_location,late_minutes) VALUES (?,?,?,?,?,?,?)', (employee_id, sched['work_date'], current.strftime('%H:%M'), now(), status, gps, late)).lastrowid
        audit(conn, user, 'CLOCK_IN', ident, {'late_minutes': late, 'gps': gps})
    else:
        fail('Chọn vào ca hoặc ra ca')
    return {'success': True}


def correct_attendance(conn, user, data):
    employee = record(conn, 'employees', data.get('employee_id'))
    work_date = day(data.get('work_date'))
    payroll_locked(conn, employee['id'], work_date)
    reason = required(data, 'note', 'Lý do chỉnh công')
    try:
        start = datetime.fromisoformat(str(data['check_in_at']))
        end = datetime.fromisoformat(str(data['check_out_at']))
    except (ValueError, KeyError):
        fail('Cần thời điểm vào và ra hợp lệ')
    if start.tzinfo or end.tzinfo:
        fail('Sử dụng giờ địa phương, không thêm múi giờ')
    hours = (end - start).total_seconds() / 3600
    if start.date().isoformat() != work_date or not 0 < hours <= 24 or end > datetime.now():
        fail('Giờ công không hợp lệ: tối đa 24 giờ và không nằm trong tương lai')
    sched = one(conn, 'SELECT s.* FROM shift_schedule sc JOIN shifts s ON sc.shift_id=s.id WHERE employee_id=? AND work_date=?', (employee['id'], work_date))
    late = max(0, int((start - datetime.fromisoformat(work_date + 'T' + sched['start_time'])).total_seconds() // 60)) if sched and sched['start_time'] else 0
    conn.execute('DELETE FROM attendance WHERE employee_id=? AND work_date=?', (employee['id'], work_date))
    conn.execute('INSERT INTO attendance(employee_id,work_date,check_in,check_out,check_in_at,check_out_at,hours_worked,status,note,late_minutes) VALUES (?,?,?,?,?,?,?,?,?,?)', (employee['id'], work_date, start.strftime('%H:%M'), end.strftime('%H:%M'), start.isoformat(), end.isoformat(), round(hours, 4), 'DI_TRE' if late > 5 else 'DUNG_GIO', reason, late))
    audit(conn, user, 'CORRECT_ATTENDANCE', employee['id'], {'date': work_date, 'hours': hours, 'reason': reason})
    return {'success': True}


def hr_request(conn, user, data):
    employee_id = employee_scope(user, data.get('employee_id'))
    record(conn, 'employees', employee_id)
    kind = data.get('kind')
    work_date = day(data.get('work_date'))
    if kind not in {'LEAVE', 'SWAP'} or work_date < date.today().isoformat():
        fail('Loại yêu cầu hoặc ngày không hợp lệ')
    reason = required(data, 'reason', 'Lý do')
    target = data.get('target_employee_id') or None
    if kind == 'SWAP':
        if not target or int(target) == int(employee_id):
            fail('Chọn nhân viên khác để đổi ca')
        record(conn, 'employees', target)
    if one(conn, "SELECT id FROM hr_requests WHERE employee_id=? AND work_date=? AND status='PENDING'", (employee_id, work_date)):
        fail('Đã có yêu cầu đang chờ cho ngày này', 409)
    ident = conn.execute('INSERT INTO hr_requests(employee_id,kind,work_date,target_employee_id,reason) VALUES (?,?,?,?,?)', (employee_id, kind, work_date, target, reason)).lastrowid
    audit(conn, user, 'HR_REQUEST', ident, {'kind': kind, 'date': work_date})
    return {'success': True, 'id': ident}


def review_request(conn, user, ident, data):
    req = record(conn, 'hr_requests', ident)
    target = data.get('status')
    if req['status'] != 'PENDING' or target not in {'APPROVED', 'REJECTED'}:
        fail('Yêu cầu không còn chờ duyệt hoặc trạng thái không hợp lệ', 409)
    if target == 'APPROVED':
        if req['work_date'] < date.today().isoformat():
            fail('Không duyệt thay đổi lịch trong quá khứ')
        for employee_id in [req['employee_id']] + ([req['target_employee_id']] if req['kind'] == 'SWAP' else []):
            payroll_locked(conn, employee_id, req['work_date'])
            if one(conn, 'SELECT id FROM attendance WHERE employee_id=? AND work_date=? AND check_in IS NOT NULL', (employee_id, req['work_date'])):
                fail('Không đổi lịch đã có chấm công')
        original = one(conn, 'SELECT * FROM shift_schedule WHERE employee_id=? AND work_date=?', (req['employee_id'], req['work_date']))
        if not original:
            fail('Nhân viên chưa có lịch ca ngày này')
        if req['kind'] == 'LEAVE':
            conn.execute('DELETE FROM shift_schedule WHERE employee_id=? AND work_date=?', (req['employee_id'], req['work_date']))
        else:
            other = one(conn, 'SELECT * FROM shift_schedule WHERE employee_id=? AND work_date=?', (req['target_employee_id'], req['work_date']))
            if not other:
                fail('Nhân viên đổi cùng chưa có lịch ca ngày này')
            for employee_id, shift_id in [(req['employee_id'], other['shift_id']), (req['target_employee_id'], original['shift_id'])]:
                employee = record(conn, 'employees', employee_id)
                if employee['status'] != 'ACTIVE':
                    fail('Không đổi ca cho nhân viên đã nghỉ việc')
                validate_schedule(conn, employee_id, record(conn, 'shifts', shift_id), req['work_date'])
            conn.execute('UPDATE shift_schedule SET shift_id=? WHERE id=?', (other['shift_id'], original['id']))
            conn.execute('UPDATE shift_schedule SET shift_id=? WHERE id=?', (original['shift_id'], other['id']))
    conn.execute('UPDATE hr_requests SET status=?,reviewed_by=? WHERE id=?', (target, user['id'], ident))
    audit(conn, user, 'REVIEW_HR_REQUEST', ident, {'status': target})
    return {'success': True}


def period(month, year):
    m = number(month, 'Tháng', minimum=1, integer=True)
    y = number(year, 'Năm', minimum=2000, integer=True)
    if m > 12 or y > 2100:
        fail('Tháng/năm không hợp lệ')
    return m, y, f'{y:04d}-{m:02d}-01', f'{y:04d}-{m:02d}-{calendar.monthrange(y,m)[1]}'


def calculate_payroll(conn, user, data):
    month, year, first, last = period(data.get('month'), data.get('year'))
    if one(conn, "SELECT id FROM payroll WHERE month=? AND year=? AND status='APPROVED'", (month, year)):
        fail('Bảng lương đã duyệt, không thể tính lại', 409)
    adjustments = data.get('adjustments', {})
    if not isinstance(adjustments, dict) or any(not isinstance(value, dict) for value in adjustments.values()):
        fail('Danh sách thưởng/khấu trừ không hợp lệ')
    for emp in rows(conn, "SELECT * FROM employees WHERE status='ACTIVE'"):
        attendance = rows(conn, 'SELECT * FROM attendance WHERE employee_id=? AND work_date BETWEEN ? AND ?', (emp['id'], first, last))
        days, hours = set(), 0
        for entry in attendance:
            if not entry['check_in_at'] or not entry['check_out_at']:
                continue
            days.add(entry['work_date'])
            hours += entry['hours_worked']
        base = rounded(hours * emp['hourly_rate']) if emp['salary_mode'] == 'HOURLY' else rounded(emp['base_salary'] * min(len(days), emp['working_days']) / emp['working_days'])
        adj = adjustments.get(str(emp['id']), {})
        bonus, deduction = money(adj.get('bonus', 0)), money(adj.get('deduction', 0))
        if deduction > base + bonus:
            fail(f"Khấu trừ của {emp['name']} vượt thu nhập")
        conn.execute('DELETE FROM payroll WHERE employee_id=? AND month=? AND year=?', (emp['id'], month, year))
        conn.execute("INSERT INTO payroll(employee_id,month,year,days_worked,hours_worked,base_salary,bonus,deduction,total,status) VALUES (?,?,?,?,?,?,?,?,?,'DRAFT')", (emp['id'], month, year, len(days), round(hours, 2), base, bonus, deduction, base + bonus - deduction))
        conn.execute('UPDATE payroll SET calculated_at=? WHERE employee_id=? AND month=? AND year=?', (now(), emp['id'], month, year))
    audit(conn, user, 'CALCULATE_PAYROLL', f'{year}-{month}', {'adjustments': adjustments})
    return {'success': True}


def approve_payroll(conn, user, data):
    month, year, _, _ = period(data.get('month'), data.get('year'))
    if not one(conn, 'SELECT id FROM payroll WHERE month=? AND year=?', (month, year)):
        fail('Chưa có bảng lương để duyệt')
    if one(conn, 'SELECT id FROM payroll WHERE month=? AND year=? AND calculated_at IS NULL', (month, year)):
        fail('Cần tính lại từ chấm công trước khi duyệt bảng lương mẫu/cũ')
    conn.execute("UPDATE payroll SET status='APPROVED' WHERE month=? AND year=?", (month, year))
    audit(conn, user, 'APPROVE_PAYROLL', f'{year}-{month}', {})
    return {'success': True}

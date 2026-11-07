from datetime import datetime, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from fastapi import HTTPException, Request
import math


def fail(message, status=400):
    raise HTTPException(status, message)


async def validate_payload(request: Request):
    """Reject malformed JSON shapes before untyped legacy domain handlers run."""
    if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        return
    if not await request.body():
        return
    try:
        data = await request.json()
    except (ValueError, RecursionError):
        fail('Nội dung JSON không hợp lệ')
    if not isinstance(data, dict):
        fail('Nội dung yêu cầu phải là một đối tượng JSON')

    def fields(values):
        for key, value in values.items():
            if isinstance(value, (dict, list)):
                fail(f'Trường {key} phải là giá trị đơn')
            if isinstance(value, float) and not math.isfinite(value):
                fail(f'Trường {key} không hợp lệ')
            if key in {'active', 'picked', 'restock'} and value not in (True, False, 0, 1):
                fail(f'Trường {key} phải là true hoặc false')

    for key, value in data.items():
        if key in {'items', 'payments'}:
            if value is not None:
                for item in objects(value, key):
                    fields(item)
        elif key == 'adjustments':
            if not isinstance(value, dict) or len(value) > 1000:
                fail('Danh sách thưởng/khấu trừ không hợp lệ')
            for item in value.values():
                if not isinstance(item, dict):
                    fail('Thưởng/khấu trừ phải là một đối tượng')
                fields(item)
        else:
            fields({key: value})


def number(value, label='Số lượng', minimum=0, integer=False):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < minimum or result > 1_000_000_000_000:
            raise ValueError()
        if integer and result != result.to_integral_value():
            raise ValueError()
        if not integer and result != result.quantize(Decimal('.001')):
            raise ValueError()
        return int(result) if integer else float(result)
    except (ValueError, TypeError, InvalidOperation):
        fail(f'{label} không hợp lệ')


def money(value):
    return number(value, 'Số tiền (đồng)', integer=True)


def quantity(value, allow_zero=False):
    return number(value, 'Số lượng phải là số nguyên', minimum=0 if allow_zero else 1, integer=True)


def rounded(value):
    return int(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def required(data, name, label=None, limit=500):
    value = str(data.get(name) or '').strip()
    if not value or len(value) > limit:
        fail(f'{label or name} cần có nội dung, tối đa {limit} ký tự')
    return value


def day(value):
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError:
        fail('Ngày phải có dạng YYYY-MM-DD')


def now():
    return datetime.now().isoformat(timespec='seconds')


def objects(value, label, minimum=1, maximum=100):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum or any(not isinstance(item, dict) for item in value):
        fail(f'{label} cần {minimum}–{maximum} mục hợp lệ')
    return value


def audit(conn, user, action, entity, details):
    conn.execute('INSERT INTO audit_log(user_id,action,entity,details) VALUES (?,?,?,?)', (user['id'] if user else None, action, str(entity), json.dumps(details, ensure_ascii=False)))


def record(conn, table, ident):
    from .database import one
    if isinstance(ident, bool) or not isinstance(ident, (int, str)):
        fail('Mã dữ liệu không hợp lệ')
    ident = number(ident, 'Mã dữ liệu', minimum=1, integer=True)
    result = one(conn, f'SELECT * FROM {table} WHERE id=?', (ident,))
    if not result:
        fail('Không tìm thấy dữ liệu', 404)
    return result

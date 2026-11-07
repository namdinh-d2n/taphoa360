import asyncio
from datetime import date
import json
import logging
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from .auth import require, current_user
from .database import transaction, reading, rows, one
from .common import fail, audit, record, day, validate_payload
from . import inventory as stock, sales, people, reporting

router = APIRouter(dependencies=[Depends(validate_payload)])


@router.get('/api/v1/products')
def products(q: str = '', user=Depends(require('cashier', 'inventory'))):
    with reading() as conn:
        result = stock.products(conn, q)
    if user['role'] == 'cashier':
        for item in result:
            item.pop('cost_price', None)
    return result


@router.post('/api/v1/products')
def create_product(data: dict, user=Depends(require('inventory'))):
    with transaction() as conn:
        return stock.save_product(conn, user, data)


@router.patch('/api/v1/products/{ident}')
def edit_product(ident: int, data: dict, user=Depends(require('inventory'))):
    if user['role'] != 'owner' and any(key in data for key in ['price', 'promo_price', 'promo_until']):
        fail('Chỉ chủ tiệm được sửa giá bán', 403)
    with transaction() as conn:
        return stock.save_product(conn, user, data, ident)


@router.get('/api/v1/inventory')
def inventory(user=Depends(require('inventory'))):
    with reading() as conn:
        return {'batches': rows(conn, 'SELECT b.*,p.product_name,p.sku FROM stock_batches b JOIN products p ON b.product_id=p.id ORDER BY b.id DESC LIMIT 500'), 'movements': rows(conn, 'SELECT m.*,p.product_name,u.name AS actor FROM stock_movements m JOIN products p ON m.product_id=p.id LEFT JOIN users u ON m.user_id=u.id ORDER BY m.id DESC LIMIT 300'), 'receipts': rows(conn, 'SELECT r.*,s.name AS supplier_name FROM purchase_receipts r JOIN suppliers s ON s.id=r.supplier_id ORDER BY r.id DESC LIMIT 100')}


@router.post('/api/v1/purchases')
def purchase(data: dict, user=Depends(require('inventory'))):
    with transaction() as conn:
        return stock.purchase(conn, user, data)


@router.post('/api/v1/stock-counts')
def stock_count(data: dict, user=Depends(require('inventory'))):
    with transaction() as conn:
        return stock.stock_count(conn, user, data)


@router.post('/api/v1/batches/{ident}/dispose')
def dispose_batch(ident: int, data: dict, user=Depends(require('inventory'))):
    from .common import quantity as whole_quantity, required
    with transaction() as conn:
        batch = record(conn, 'stock_batches', ident)
        quantity = whole_quantity(data.get('quantity'))
        note = required(data, 'note', 'Lý do loại bỏ hàng')
        if quantity > batch['remaining']:
            fail('Số lượng vượt tồn của lô')
        conn.execute('UPDATE stock_batches SET remaining=ROUND(remaining-?,3) WHERE id=?', (quantity, ident))
        stock.movement(conn, user, batch['product_id'], ident, -quantity, 'DAMAGE', ident, note)
        audit(conn, user, 'DISPOSE_BATCH', ident, {'quantity': quantity, 'note': note})
    return {'success': True}


@router.patch('/api/v1/batches/{ident}')
def edit_batch(ident: int, data: dict, user=Depends(require())):
    from .common import money, required
    with transaction() as conn:
        batch = record(conn, 'stock_batches', ident)
        cost = money(data.get('cost_price', batch['cost_price']))
        if cost != batch['cost_price'] and one(conn, 'SELECT id FROM stock_movements WHERE batch_id=? AND quantity<0', (ident,)):
            fail('Lô đã xuất hàng không được sửa giá vốn lịch sử', 409)
        lot = str(data.get('lot_code', batch['lot_code'])).strip()[:64]
        if not lot:
            fail('Cần mã lô')
        expiry = day(data['expires_on']) if data.get('expires_on') else None
        note = required(data, 'note', 'Lý do chỉnh lô')
        conn.execute('UPDATE stock_batches SET lot_code=?,cost_price=?,expires_on=? WHERE id=?', (lot, cost, expiry, ident))
        audit(conn, user, 'EDIT_BATCH', ident, {'before': batch, 'cost_price': cost, 'expires_on': expiry, 'note': note})
    return {'success': True}


@router.get('/api/v1/customers')
def customers(user=Depends(require('cashier'))):
    with reading() as conn:
        return stock.parties(conn, 'CUSTOMER')


@router.get('/api/v1/suppliers')
def suppliers(user=Depends(require('inventory'))):
    with reading() as conn:
        return stock.parties(conn, 'SUPPLIER')


@router.post('/api/v1/customers')
def create_customer(data: dict, user=Depends(require('cashier'))):
    with transaction() as conn:
        return stock.save_party(conn, user, 'CUSTOMER', data)


@router.patch('/api/v1/customers/{ident}')
def edit_customer(ident: int, data: dict, user=Depends(require('cashier'))):
    with transaction() as conn:
        return stock.save_party(conn, user, 'CUSTOMER', data, ident)


@router.post('/api/v1/suppliers')
def create_supplier(data: dict, user=Depends(require('inventory'))):
    with transaction() as conn:
        return stock.save_party(conn, user, 'SUPPLIER', data)


@router.patch('/api/v1/suppliers/{ident}')
def edit_supplier(ident: int, data: dict, user=Depends(require('inventory'))):
    with transaction() as conn:
        return stock.save_party(conn, user, 'SUPPLIER', data, ident)


@router.get('/api/v1/accounts/{kind}/{ident}')
def account(kind: str, ident: int, user=Depends(current_user)):
    require('cashier' if kind == 'CUSTOMER' else 'inventory')(user)
    if kind not in {'CUSTOMER', 'SUPPLIER'}:
        fail('Loại công nợ không hợp lệ')
    with reading() as conn:
        return rows(conn, 'SELECT * FROM account_entries WHERE party_type=? AND party_id=? ORDER BY id DESC', (kind, ident))


@router.post('/api/v1/accounts/{kind}/{ident}/settle')
def settle(kind: str, ident: int, data: dict, user=Depends(current_user)):
    require('cashier' if kind == 'CUSTOMER' else 'inventory')(user)
    with transaction() as conn:
        return stock.settle_debt(conn, user, kind, ident, data)


@router.get('/api/v1/orders')
def orders(status: str = '', customer_id: int | None = None, q: str = '', user=Depends(require('cashier', 'inventory', 'shipper'))):
    with reading() as conn:
        return sales.order_list(conn, user, status, customer_id, q)


@router.post('/api/v1/orders')
@router.post('/api/create_order', include_in_schema=False)
@router.post('/create_order.php', include_in_schema=False)
@router.post('/create_order', include_in_schema=False)
def create_order(data: dict, request: Request, user=Depends(require('cashier'))):
    with transaction() as conn:
        return sales.create_order(conn, user, data, request.headers.get('idempotency-key'))


@router.get('/api/v1/orders/{ident}')
def order(ident: int, user=Depends(require('cashier', 'inventory', 'shipper'))):
    with reading() as conn:
        result = sales.order_detail(conn, ident, user)
        if user['role'] != 'owner':
            for item in result['items']:
                item.pop('cost_price', None)
        return result


@router.post('/api/v1/orders/{ident}/status')
def status(ident: int, data: dict, user=Depends(require('cashier', 'inventory', 'shipper'))):
    if data.get('status') == 'CANCELLED':
        require('cashier')(user)
    with transaction() as conn:
        return sales.change_status(conn, user, ident, data)


@router.post('/api/v1/orders/{ident}/assign')
def assign(ident: int, data: dict, user=Depends(require('inventory'))):
    with transaction() as conn:
        return sales.assign_shipper(conn, user, ident, data)


@router.post('/api/v1/order-items/{ident}/pick')
def pick(ident: int, data: dict, user=Depends(require('inventory', 'cashier'))):
    with transaction() as conn:
        return sales.pick_item(conn, user, ident, data)


@router.post('/api/v1/orders/{ident}/returns')
def returns(ident: int, data: dict, user=Depends(require('cashier'))):
    with transaction() as conn:
        return sales.return_order(conn, user, ident, data)


@router.get('/api/v1/shippers')
def shippers(user=Depends(require('inventory', 'cashier'))):
    with reading() as conn:
        return rows(conn, "SELECT id,name FROM users WHERE role='shipper' AND active=1 ORDER BY name")


@router.get('/api/v1/cash-shifts')
def cash_shifts(user=Depends(require('cashier', 'inventory'))):
    with reading() as conn:
        result = rows(conn, '''SELECT s.*,u.name AS cashier, s.opening_cash+COALESCE((SELECT SUM(amount) FROM payments p WHERE p.cash_shift_id=s.id AND method='CASH'),0) AS live_expected,
            COALESCE((SELECT SUM(amount) FROM payments p WHERE p.cash_shift_id=s.id AND method='TRANSFER'),0) AS transfer_net,
            COALESCE((SELECT SUM(amount) FROM payments p WHERE p.cash_shift_id=s.id AND method='DEBT'),0) AS debt_net,
            COALESCE((SELECT SUM(amount) FROM payments p WHERE p.cash_shift_id=s.id AND kind IN ('SALE','REFUND')),0) AS net_sales
            FROM cash_shifts s JOIN users u ON s.user_id=u.id WHERE (?='owner' OR s.user_id=?) ORDER BY s.id DESC LIMIT 100''', (user['role'], user['id']))
        return result


@router.post('/api/v1/cash-shifts')
def open_cash(data: dict, user=Depends(require('cashier', 'inventory'))):
    with transaction() as conn:
        return sales.open_shift(conn, user, data)


@router.post('/api/v1/cash-shifts/{ident}/close')
def close_cash(ident: int, data: dict, user=Depends(require('cashier', 'inventory'))):
    with transaction() as conn:
        return sales.close_shift(conn, user, ident, data)


@router.get('/api/v1/suggestions')
def suggestions(user=Depends(require('inventory'))):
    with reading() as conn:
        return stock.suggestions(conn)


@router.post('/api/v1/suggestions/apply')
def apply_suggestion(data: dict, user=Depends(require())):
    with transaction() as conn:
        return stock.apply_suggestion(conn, user, data.get('key'))


@router.post('/api/v1/products/{ident}/end-promotion')
def end_promotion(ident: int, user=Depends(require())):
    with transaction() as conn:
        record(conn, 'products', ident)
        conn.execute('UPDATE products SET promo_price=NULL,promo_until=NULL WHERE id=?', (ident,))
        audit(conn, user, 'END_PROMOTION', ident, {})
    return {'success': True}


@router.get('/api/v1/hr')
def hr(user=Depends(current_user)):
    with reading() as conn:
        owner, employee = user['role'] == 'owner', user['employee_id'] or -1
        return {
            'employees': rows(conn, 'SELECT * FROM employees WHERE ? OR id=? ORDER BY id', (owner, employee)),
            'colleagues': rows(conn, "SELECT id,name FROM employees WHERE status='ACTIVE'"),
            'shifts': rows(conn, 'SELECT * FROM shifts ORDER BY id'),
            'schedule': rows(conn, '''SELECT sc.*,e.name AS employee_name,s.name AS shift_name,s.start_time,s.end_time FROM shift_schedule sc JOIN employees e ON sc.employee_id=e.id JOIN shifts s ON s.id=sc.shift_id WHERE (? OR sc.employee_id=?) AND work_date BETWEEN date('now','localtime','-31 day') AND date('now','localtime','+90 day') ORDER BY work_date DESC,e.name''', (owner, employee)),
            'attendance': rows(conn, 'SELECT a.*,e.name AS employee_name FROM attendance a JOIN employees e ON a.employee_id=e.id WHERE ? OR a.employee_id=? ORDER BY work_date DESC LIMIT 300', (owner, employee)),
            'requests': rows(conn, 'SELECT r.*,e.name AS employee_name,t.name AS target_name FROM hr_requests r JOIN employees e ON r.employee_id=e.id LEFT JOIN employees t ON t.id=r.target_employee_id WHERE ? OR r.employee_id=? ORDER BY r.id DESC LIMIT 100', (owner, employee))}


@router.post('/api/v1/hr/employees')
@router.post('/api/hr/employees', include_in_schema=False)
def add_employee(data: dict, user=Depends(require())):
    with transaction() as conn:
        return people.save_employee(conn, user, data)


@router.patch('/api/v1/hr/employees/{ident}')
def edit_employee(ident: int, data: dict, user=Depends(require())):
    with transaction() as conn:
        return people.save_employee(conn, user, data, ident)


@router.post('/api/v1/hr/shifts')
def add_shift(data: dict, user=Depends(require())):
    with transaction() as conn:
        return people.save_shift(conn, user, data)


@router.patch('/api/v1/hr/shifts/{ident}')
def edit_shift(ident: int, data: dict, user=Depends(require())):
    with transaction() as conn:
        return people.save_shift(conn, user, data, ident)


@router.post('/api/v1/hr/schedule')
def schedule(data: dict, user=Depends(require())):
    with transaction() as conn:
        return people.assign_shift(conn, user, data)


@router.post('/api/v1/hr/clock')
@router.post('/api/hr/attendance/checkin', include_in_schema=False)
def clock(data: dict, user=Depends(current_user)):
    with transaction() as conn:
        return people.clock(conn, user, data)


@router.post('/api/v1/hr/attendance/correct')
def correct_attendance(data: dict, user=Depends(require())):
    with transaction() as conn:
        return people.correct_attendance(conn, user, data)


@router.post('/api/v1/hr/requests')
def hr_request(data: dict, user=Depends(current_user)):
    with transaction() as conn:
        return people.hr_request(conn, user, data)


@router.post('/api/v1/hr/requests/{ident}/review')
def review_request(ident: int, data: dict, user=Depends(require())):
    with transaction() as conn:
        return people.review_request(conn, user, ident, data)


@router.get('/api/v1/hr/payroll')
@router.get('/api/hr/payroll', include_in_schema=False)
def payroll(request: Request, month: int | None = None, year: int | None = None, user=Depends(current_user)):
    month = date.today().month if month is None else month
    year = date.today().year if year is None else year
    people.period(month, year)
    with reading() as conn:
        result = rows(conn, 'SELECT p.*,e.name AS employee_name FROM payroll p JOIN employees e ON p.employee_id=e.id WHERE month=? AND year=? AND (? OR p.employee_id=?) ORDER BY e.name', (month, year, user['role'] == 'owner', user['employee_id'] or -1))
        return {'success': True, 'data': result} if request.url.path == '/api/hr/payroll' else result


@router.get('/api/hr/employees', include_in_schema=False)
def legacy_employees(user=Depends(current_user)):
    return {'success': True, 'data': hr(user)['employees']}


@router.get('/api/hr/attendance', include_in_schema=False)
def legacy_attendance(user=Depends(current_user)):
    result = [r for r in hr(user)['attendance'] if r['work_date'] == date.today().isoformat()]
    return {'success': True, 'data': result}


@router.get('/api/hr/schedule', include_in_schema=False)
def legacy_schedule(week: int = 0, user=Depends(current_user)):
    from datetime import timedelta
    if abs(week) > 520:
        fail('Tuần không hợp lệ')
    monday = date.today() - timedelta(days=date.today().weekday()) + timedelta(weeks=week)
    dates = [(monday + timedelta(days=i)).isoformat() for i in range(7)]
    data = hr(user)
    schedule_rows = []
    with reading() as conn:
        for employee in data['employees']:
            entries = rows(conn, 'SELECT sc.work_date,s.name FROM shift_schedule sc JOIN shifts s ON s.id=sc.shift_id WHERE employee_id=? AND work_date BETWEEN ? AND ?', (employee['id'], dates[0], dates[-1]))
            by_day = {r['work_date']: r['name'] for r in entries}
            schedule_rows.append({'employee': employee, 'days': [{'shift': by_day.get(d, 'NGHI')} for d in dates]})
    return {'success': True, 'data': {'week_dates': dates, 'day_labels': ['T2','T3','T4','T5','T6','T7','CN'], 'schedule_rows': schedule_rows}}


@router.get('/api/hr/stats', include_in_schema=False)
def legacy_hr_stats(user=Depends(current_user)):
    data = hr(user)
    today = date.today().isoformat()
    checked = [a for a in data['attendance'] if a['work_date'] == today and a['check_in']]
    return {'total_employees': len([e for e in data['employees'] if e['status'] == 'ACTIVE']), 'checked_today': len(checked), 'total_scheduled': len([s for s in data['schedule'] if s['work_date'] == today and s['start_time']]), 'current_month': date.today().month, 'current_year': date.today().year}


@router.post('/api/v1/hr/payroll/calculate')
def calculate_payroll(data: dict, user=Depends(require())):
    with transaction() as conn:
        return people.calculate_payroll(conn, user, data)


@router.post('/api/v1/hr/payroll/approve')
@router.post('/api/hr/payroll/approve', include_in_schema=False)
def approve_payroll(data: dict, user=Depends(require())):
    with transaction() as conn:
        return people.approve_payroll(conn, user, data)


@router.get('/api/v1/reports')
def reports(start: str | None = None, end: str | None = None, user=Depends(require())):
    with reading() as conn:
        return reporting.report(conn, start or date.today().replace(day=1).isoformat(), end or date.today().isoformat())


@router.get('/api/v1/audit')
def audit_log(user=Depends(require())):
    with reading() as conn:
        return rows(conn, 'SELECT a.*,u.name AS actor FROM audit_log a LEFT JOIN users u ON a.user_id=u.id ORDER BY a.id DESC LIMIT 300')


@router.get('/api/v1/backups')
def backups(user=Depends(require())):
    return reporting.list_backups()


@router.post('/api/v1/backups')
def backup(user=Depends(require())):
    return reporting.make_backup(user)


@router.get('/api/v1/backups/{name}/download')
def download_backup(name: str, user=Depends(require())):
    return FileResponse(reporting.backup_file(name), filename=name, media_type='application/octet-stream')


@router.post('/api/v1/backups/{name}/restore')
def restore(name: str, data: dict, user=Depends(require())):
    return reporting.restore_backup(user, name, data.get('confirmation'))


@router.get('/api/search_inventory', include_in_schema=False)
@router.get('/search_inventory.php', include_in_schema=False)
@router.get('/search_inventory', include_in_schema=False)
def search_inventory(keyword: str = '', user=Depends(require('cashier', 'inventory'))):
    with reading() as conn:
        result = stock.products(conn, keyword)
    return {'success': True, 'data': [{'id': p['id'], 'name': p['product_name'], 'sku': p['sku'], 'stock': p['sellable_stock'], 'unit': p['unit'], 'location': p['shelf_location'], 'price': p['selling_price']} for p in result if p['active']][:10]}


@router.get('/api/get_merchant_orders', include_in_schema=False)
@router.get('/get_merchant_orders.php', include_in_schema=False)
@router.get('/get_merchant_orders', include_in_schema=False)
def merchant_orders(user=Depends(require('cashier', 'inventory', 'shipper'))):
    with reading() as conn:
        queue = [o for o in sales.order_list(conn, user) if o['status'] in {'PENDING', 'PROCESSING', 'SHIPPING'}]
        selected = sales.order_detail(conn, queue[-1]['id'], user) if queue else None
        pick = [{**i, 'name': i['product_name'], 'shelfLocation': i['shelf_location'], 'isDone': bool(i['is_picked']), 'qty': f"{i['quantity']:g} sp"} for i in selected['items']] if selected else []
        for item in pick:
            item.pop('cost_price', None)
        shippers = rows(conn, "SELECT id,name FROM users WHERE role='shipper' AND active=1")
        return {'success': True, 'order': {k:v for k,v in selected.items() if k not in {'items', 'payments', 'returns', 'events'}} if selected else None, 'orders': queue, 'pick_list': pick, 'shippers': shippers}


@router.get('/api/v1/events')
@router.get('/stream_orders.php', include_in_schema=False)
@router.get('/api/stream_orders', include_in_schema=False)
@router.get('/stream_orders', include_in_schema=False)
async def events(request: Request, user=Depends(require('cashier', 'inventory', 'shipper'))):
    def initial_cursor():
        cursor = request.headers.get('last-event-id') or request.query_params.get('after')
        if cursor is None:
            with reading() as conn:
                cursor = one(conn, 'SELECT COALESCE(MAX(id),0) AS n FROM order_events')['n']
        try:
            return min(9223372036854775807, max(0, int(cursor)))
        except ValueError:
            fail('Mốc sự kiện không hợp lệ')
    cursor = await asyncio.to_thread(initial_cursor)

    def fetch(after):
        current_user(request)
        with reading() as conn:
            return rows(conn, '''SELECT e.*,o.order_code,o.total_amount FROM order_events e JOIN orders o ON e.order_id=o.id WHERE e.id>? AND (?!='shipper' OR o.shipper_user_id=?) ORDER BY e.id LIMIT 100''', (after, user['role'], user['id']))

    async def stream():
        nonlocal cursor
        yield f'id: {cursor}\ndata: {{"status":"connected"}}\n\n'
        while not await request.is_disconnected():
            try:
                data = await asyncio.to_thread(fetch, cursor)
            except HTTPException as exc:
                if exc.status_code in {401, 403}:
                    yield 'event: session-expired\ndata: {}\n\n'
                    return
                raise
            except Exception:
                logging.getLogger('taphoa').exception('Event stream temporarily unavailable')
                yield 'retry: 5000\n\n'
                return
            for item in data:
                cursor = item['id']
                yield f'id: {cursor}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n'
            if not data:
                yield ': heartbeat\n\n'
            await asyncio.sleep(2)
    return StreamingResponse(stream(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

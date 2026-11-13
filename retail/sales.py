from datetime import date
import hashlib
import json
import secrets
from .database import one, rows
from .common import fail, money, number, rounded, required, audit, record, objects, quantity
from .inventory import take_stock, movement, payment

METHODS = {'Tiền mặt': 'CASH', 'Chuyển khoản': 'TRANSFER', 'Công nợ': 'DEBT'}


def create_order(conn, user, data, key=None):
    key = key or data.get('idempotency_key')
    if not isinstance(key, str) or not 8 <= len(key) <= 128:
        fail('Cần Idempotency-Key từ 8 đến 128 ký tự để tránh tạo trùng đơn')
    fingerprint = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    previous = one(conn, 'SELECT * FROM orders WHERE idempotency_key=?', (key,))
    if previous:
        if previous['request_hash'] != fingerprint or previous['cashier_id'] != user['id']:
            fail('Mã chống trùng đã được dùng cho một yêu cầu khác', 409)
        return {'success': True, 'order_id': previous['id'], 'order_code': previous['order_code'], 'total_amount': previous['total_amount'], 'replayed': True}
    items = data.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        fail('Đơn hàng cần 1–100 mặt hàng')
    normalized, seen = [], set()
    gross = 0
    for item in items:
        if not isinstance(item, dict):
            fail('Mặt hàng không hợp lệ')
        product_id = item.get('product_id') or item.get('id')
        if not product_id:
            matches = rows(conn, 'SELECT id FROM products WHERE product_name=? AND active=1', (item.get('name'),))
            if len(matches) != 1:
                fail('Mỗi mặt hàng cần product_id hoặc tên duy nhất')
            product_id = matches[0]['id']
        p = record(conn, 'products', product_id)
        if not p['active'] or p['id'] in seen:
            fail('Sản phẩm ngừng bán hoặc xuất hiện nhiều lần trong đơn')
        seen.add(p['id'])
        qty = quantity(item.get('quantity'))
        price = p['promo_price'] if p['promo_price'] is not None and (p['promo_until'] or '') >= date.today().isoformat() else p['price']
        price = money(price)
        subtotal = money(rounded(qty * price))
        normalized.append((p, qty, price, subtotal))
        gross = money(gross + subtotal)
    customer = record(conn, 'customers', data['customer_id']) if data.get('customer_id') else None
    discount = money(data.get('discount', 0))
    points = number(data.get('points_redeemed', 0), 'Điểm đổi', integer=True)
    if points and (not customer or points > customer['points']):
        fail('Khách hàng không đủ điểm')
    if discount + points * 100 > gross:
        fail('Giảm giá và điểm đổi không được vượt tổng tiền hàng')
    total = gross - discount - points * 100
    payments = data.get('payments')
    if payments is None:
        method = METHODS.get(data.get('payment_method'), data.get('payment_method', 'CASH'))
        payments = [{'method': method, 'amount': total}]
    payments = objects(payments, 'Thanh toán', maximum=3)
    prepared_payments = [(p.get('method'), money(p.get('amount'))) for p in payments]
    if len({m for m, _ in prepared_payments}) != len(prepared_payments):
        fail('Phương thức thanh toán bị trùng')
    if any(m not in {'CASH', 'TRANSFER', 'DEBT'} for m, _ in prepared_payments):
        fail('Phương thức thanh toán không hợp lệ')
    if sum(a for _, a in prepared_payments) != total:
        fail('Tổng thanh toán phải bằng tổng tiền do hệ thống tính')
    debt = sum(a for m, a in prepared_payments if m == 'DEBT')
    if debt and not customer:
        fail('Bán chịu cần chọn khách hàng')
    cash = sum(a for m, a in prepared_payments if m == 'CASH')
    tendered = money(data.get('cash_tendered', cash))
    if tendered < cash:
        fail('Tiền khách đưa chưa đủ')
    fulfillment = data.get('fulfillment', 'PICKUP')
    if fulfillment not in {'PICKUP', 'DELIVERY'}:
        fail('Hình thức nhận hàng không hợp lệ')
    address = required(data, 'apartment', 'Địa chỉ giao hàng') if fulfillment == 'DELIVERY' else str(data.get('apartment', ''))[:500]
    status = 'PENDING' if fulfillment == 'DELIVERY' else 'COMPLETED'
    code = 'DH-' + date.today().strftime('%Y%m%d') + '-' + secrets.token_hex(4).upper()
    earned = total // 10000 if customer else 0
    ident = conn.execute('''INSERT INTO orders(order_code,created_by,total_amount,payment_method,apartment,customer_note,status,customer_id,cashier_id,gross_amount,discount,points_redeemed,points_earned,managed,idempotency_key,request_hash,fulfillment)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)''', (code, user['name'], total, '+'.join(m for m, _ in prepared_payments), address, str(data.get('customer_note', ''))[:500], status, customer['id'] if customer else None, user['id'], gross, discount, points, earned, key, fingerprint, fulfillment)).lastrowid
    net_left = total
    for index, (p, qty, price, subtotal) in enumerate(normalized):
        net = net_left if index == len(normalized) - 1 else min(net_left, rounded(total * subtotal / gross) if gross else 0)
        net_left -= net
        allocations = take_stock(conn, user, p['id'], qty, 'SALE', ident)
        cost = sum(q * c for _, q, c in allocations) / qty
        item_id = conn.execute('''INSERT INTO order_items(order_id,product_name,shelf_location,quantity,price,subtotal,is_picked,product_id,cost_price,net_subtotal)
            VALUES (?,?,?,?,?,?,?,?,?,?)''', (ident, p['product_name'], p['shelf_location'], qty, price, subtotal, int(fulfillment == 'PICKUP'), p['id'], cost, net)).lastrowid
        conn.executemany('INSERT INTO order_allocations(order_item_id,batch_id,quantity,cost_price) VALUES (?,?,?,?)', [(item_id, b, q, c) for b, q, c in allocations])
    for method, amount in prepared_payments:
        payment(conn, user, amount, method, 'SALE', ident, ident)
    if customer:
        conn.execute('UPDATE customers SET points=points-?+? WHERE id=?', (points, earned, customer['id']))
        if debt:
            conn.execute("INSERT INTO account_entries(party_type,party_id,amount,reference,user_id) VALUES ('CUSTOMER',?,?,?,?)", (customer['id'], debt, f'ORDER:{ident}', user['id']))
    conn.execute('INSERT INTO order_events(order_id,status,user_id) VALUES (?,?,?)', (ident, status, user['id']))
    audit(conn, user, 'CREATE_ORDER', ident, {'total': total, 'discount': discount, 'points': points})
    return {'success': True, 'order_id': ident, 'order_code': code, 'total_amount': total, 'change': tendered - cash}


def order_detail(conn, ident, user):
    order = record(conn, 'orders', ident)
    if user['role'] == 'shipper' and order['shipper_user_id'] != user['id']:
        fail('Đơn hàng chưa được giao cho bạn', 403)
    order['items'] = rows(conn, 'SELECT i.*,p.zone_code FROM order_items i LEFT JOIN products p ON p.id=i.product_id WHERE order_id=? ORDER BY p.zone_code,i.shelf_location,i.id', (ident,))
    order['payments'] = rows(conn, 'SELECT * FROM payments WHERE order_id=? ORDER BY id', (ident,))
    order['returns'] = rows(conn, 'SELECT * FROM returns WHERE order_id=? ORDER BY id', (ident,))
    order['events'] = rows(conn, 'SELECT * FROM order_events WHERE order_id=? ORDER BY id', (ident,))
    return order


def order_list(conn, user, status='', customer_id=None, search='', limit=100):
    clauses, params = ['1=1'], []
    if user['role'] == 'shipper':
        clauses.append('o.shipper_user_id=?')
        params.append(user['id'])
    if status:
        clauses.append('o.status=?')
        params.append(status)
    if customer_id:
        clauses.append('o.customer_id=?')
        params.append(customer_id)
    if search:
        clauses.append('(o.order_code LIKE ? OR o.created_by LIKE ?)')
        params.extend(['%' + search + '%'] * 2)
    return rows(conn, 'SELECT o.*,c.name AS customer_name,u.name AS shipper_name,COALESCE((SELECT SUM(amount) FROM returns r WHERE r.order_id=o.id),0) AS refunded FROM orders o LEFT JOIN customers c ON c.id=o.customer_id LEFT JOIN users u ON u.id=o.shipper_user_id WHERE ' + ' AND '.join(clauses) + ' ORDER BY o.id DESC LIMIT ?', (*params, limit))


def return_order(conn, user, ident, data, cancel=False):
    order = record(conn, 'orders', ident)
    if not order['managed']:
        fail('Đơn từ dữ liệu cũ chưa có lịch sử phân bổ kho; không thể hoàn tự động', 409)
    if order['status'] in {'CANCELLED', 'RETURNED'}:
        fail('Đơn đã hủy hoặc đã trả toàn bộ', 409)
    if not cancel and order['status'] not in {'COMPLETED', 'PARTIAL_RETURN'}:
        fail('Chỉ trả hàng cho đơn đã hoàn tất')
    reason = required(data, 'reason', 'Lý do')
    items = rows(conn, 'SELECT * FROM order_items WHERE order_id=? ORDER BY id', (ident,))
    requested = [{'item_id': i['id'], 'quantity': i['quantity'] - i['returned_qty'], 'restock': True} for i in items] if cancel else data.get('items')
    requested = objects(requested, 'Mặt hàng trả')
    normalized, seen, refund = [], set(), 0
    lookup = {i['id']: i for i in items}
    for req in requested:
        item = lookup.get(req.get('item_id'))
        if not item or item['id'] in seen:
            fail('Chi tiết trả hàng không hợp lệ')
        seen.add(item['id'])
        qty = number(req.get('quantity'), minimum=.001)
        # Preserve exact reversal of historical fractional orders, without allowing new fractions.
        remaining_old = round(item['quantity'] - item['returned_qty'], 3)
        if not cancel and (float(item['quantity']).is_integer() or qty != remaining_old):
            qty = quantity(qty)
        if qty > item['quantity'] - item['returned_qty'] + .00001:
            fail('Số lượng trả vượt số lượng chưa trả')
        amount = rounded(item['net_subtotal'] * (item['returned_qty'] + qty) / item['quantity']) - rounded(item['net_subtotal'] * item['returned_qty'] / item['quantity'])
        refund += amount
        normalized.append((item, qty, amount, bool(req.get('restock', True))))
    # Recover earned points and restore redeemed points proportionally to returned merchandise.
    if order['customer_id']:
        customer = record(conn, 'customers', order['customer_id'])
        old_nominal = sum(rounded(i['net_subtotal'] * i['returned_qty'] / i['quantity']) for i in items)
        denominator = order['total_amount'] or 1
        final_return = all(i['returned_qty'] + sum(q for it,q,_,_ in normalized if it['id']==i['id']) >= i['quantity'] - .00001 for i in items)
        fraction_after = 1 if final_return else min(1, (old_nominal + refund) / denominator)
        fraction_before = min(1, old_nominal / denominator) if order['total_amount'] else 0
        recover = rounded(order['points_earned'] * fraction_after) - rounded(order['points_earned'] * fraction_before)
        restore = rounded(order['points_redeemed'] * fraction_after) - rounded(order['points_redeemed'] * fraction_before)
        available = customer['points'] + restore
        missing = max(0, recover - available)
        refund = max(0, refund - missing * 100)
        conn.execute('UPDATE customers SET points=? WHERE id=?', (max(0, available - recover), customer['id']))
    ret_id = conn.execute('INSERT INTO returns(order_id,amount,reason,user_id) VALUES (?,?,?,?)', (ident, refund, reason, user['id'])).lastrowid
    for item, qty, amount, restock in normalized:
        remaining = qty
        for alloc in rows(conn, 'SELECT * FROM order_allocations WHERE order_item_id=? ORDER BY id', (item['id'],)):
            take = round(min(remaining, alloc['quantity'] - alloc['returned_qty']), 3)
            if take <= 0:
                continue
            conn.execute('UPDATE order_allocations SET returned_qty=ROUND(returned_qty+?,3) WHERE id=?', (take, alloc['id']))
            if restock:
                conn.execute('UPDATE stock_batches SET remaining=ROUND(remaining+?,3) WHERE id=?', (take, alloc['batch_id']))
                movement(conn, user, item['product_id'], alloc['batch_id'], take, 'CANCEL' if cancel else 'RETURN', ret_id, reason)
            remaining = round(remaining - take, 3)
            if remaining <= 0:
                break
        if remaining > .00001:
            fail('Không đủ dữ liệu phân bổ lô để xử lý trả hàng', 409)
        conn.execute('UPDATE order_items SET returned_qty=ROUND(returned_qty+?,3) WHERE id=?', (qty, item['id']))
        conn.execute('INSERT INTO return_items(return_id,order_item_id,quantity,amount,restock) VALUES (?,?,?,?,?)', (ret_id, item['id'], qty, amount, int(restock)))
    # Debt refunds reduce the outstanding balance first; already settled debt is refunded as money.
    debt = one(conn, "SELECT COALESCE(SUM(amount),0) AS n FROM payments WHERE order_id=? AND method='DEBT'", (ident,))['n']
    balance = one(conn, "SELECT COALESCE(SUM(amount),0) AS n FROM account_entries WHERE party_type='CUSTOMER' AND party_id=?", (order['customer_id'],))['n'] if order['customer_id'] else 0
    debt_refund = min(refund, max(0, debt), max(0, balance))
    if debt_refund:
        conn.execute("INSERT INTO account_entries(party_type,party_id,amount,reference,user_id) VALUES ('CUSTOMER',?,?,?,?)", (order['customer_id'], -debt_refund, f'RETURN:{ret_id}', user['id']))
        payment(conn, user, -debt_refund, 'DEBT', 'REFUND', ret_id, ident)
    if refund - debt_refund:
        method = data.get('method', 'CASH')
        if method not in {'CASH', 'TRANSFER'}:
            fail('Chọn tiền mặt hoặc chuyển khoản để hoàn tiền')
        payment(conn, user, -(refund - debt_refund), method, 'REFUND', ret_id, ident)
    left = one(conn, 'SELECT SUM(quantity-returned_qty) AS n FROM order_items WHERE order_id=?', (ident,))['n']
    status = 'CANCELLED' if cancel else ('RETURNED' if left < .00001 else 'PARTIAL_RETURN')
    conn.execute('UPDATE orders SET status=? WHERE id=?', (status, ident))
    conn.execute('INSERT INTO order_events(order_id,status,user_id,note) VALUES (?,?,?,?)', (ident, status, user['id'], reason))
    audit(conn, user, 'CANCEL_ORDER' if cancel else 'RETURN_ORDER', ident, {'refund': refund, 'reason': reason})
    return {'success': True, 'return_id': ret_id, 'refund': refund, 'status': status}


def change_status(conn, user, ident, data):
    order = record(conn, 'orders', ident)
    target = data.get('status')
    allowed = {'PENDING': {'PROCESSING', 'CANCELLED'}, 'PROCESSING': {'SHIPPING', 'CANCELLED'}, 'SHIPPING': {'COMPLETED'}}
    if user['role'] == 'shipper':
        if order['shipper_user_id'] != user['id'] or target != 'COMPLETED':
            fail('Bạn chỉ có thể hoàn tất đơn được giao cho mình', 403)
    if target not in allowed.get(order['status'], set()):
        fail('Chuyển trạng thái không hợp lệ', 409)
    if target == 'CANCELLED':
        return return_order(conn, user, ident, data, cancel=True)
    if target == 'SHIPPING':
        if not order['shipper_user_id']:
            fail('Cần phân công người giao hàng')
        if one(conn, 'SELECT id FROM order_items WHERE order_id=? AND is_picked=0', (ident,)):
            fail('Cần soạn đủ hàng trước khi giao')
    conn.execute('UPDATE orders SET status=? WHERE id=?', (target, ident))
    conn.execute('INSERT INTO order_events(order_id,status,user_id) VALUES (?,?,?)', (ident, target, user['id']))
    audit(conn, user, 'ORDER_STATUS', ident, {'from': order['status'], 'to': target})
    return {'success': True}


def assign_shipper(conn, user, ident, data):
    order = record(conn, 'orders', ident)
    shipper = record(conn, 'users', data.get('user_id'))
    if order['status'] not in {'PENDING', 'PROCESSING'} or shipper['role'] != 'shipper' or not shipper['active']:
        fail('Đơn hoặc người giao hàng không phù hợp')
    conn.execute('UPDATE orders SET shipper_user_id=? WHERE id=?', (shipper['id'], ident))
    audit(conn, user, 'ASSIGN_SHIPPER', ident, {'user_id': shipper['id']})
    return {'success': True}


def pick_item(conn, user, ident, data):
    item = record(conn, 'order_items', ident)
    order = record(conn, 'orders', item['order_id'])
    if order['status'] not in {'PENDING', 'PROCESSING'}:
        fail('Đơn không ở trạng thái soạn hàng', 409)
    conn.execute('UPDATE order_items SET is_picked=? WHERE id=?', (int(bool(data.get('picked', True))), ident))
    audit(conn, user, 'PICK_ITEM', ident, {'picked': bool(data.get('picked', True))})
    return {'success': True}


def open_shift(conn, user, data):
    if one(conn, 'SELECT id FROM cash_shifts WHERE user_id=? AND closed_at IS NULL', (user['id'],)):
        fail('Bạn đang có một ca chưa chốt', 409)
    ident = conn.execute('INSERT INTO cash_shifts(user_id,opening_cash) VALUES (?,?)', (user['id'], money(data.get('opening_cash', 0)))).lastrowid
    audit(conn, user, 'OPEN_CASH_SHIFT', ident, data)
    return {'success': True, 'id': ident}


def close_shift(conn, user, ident, data):
    shift = record(conn, 'cash_shifts', ident)
    if shift['user_id'] != user['id'] and user['role'] != 'owner':
        fail('Bạn chỉ được chốt ca của mình', 403)
    if shift['closed_at']:
        fail('Ca đã chốt', 409)
    total = one(conn, "SELECT COALESCE(SUM(amount),0) AS n FROM payments WHERE cash_shift_id=? AND method='CASH'", (ident,))['n']
    expected = shift['opening_cash'] + total
    counted = money(data.get('counted_cash'))
    note = str(data.get('note', ''))[:500]
    if counted != expected and not note.strip():
        fail('Vui lòng ghi lý do chênh lệch tiền mặt')
    conn.execute("UPDATE cash_shifts SET expected_cash=?,counted_cash=?,difference=?,note=?,closed_at=datetime('now','localtime') WHERE id=?", (expected, counted, counted - expected, note, ident))
    audit(conn, user, 'CLOSE_CASH_SHIFT', ident, {'expected': expected, 'counted': counted})
    return {'success': True, 'expected': expected, 'difference': counted - expected}

from datetime import date, timedelta
import secrets
import math
from .database import rows, one
from .common import fail, money, number, rounded, required, day, audit, record, objects, quantity


def movement(conn, user, product_id, batch_id, quantity, kind, reference, note=''):
    conn.execute('INSERT INTO stock_movements(product_id,batch_id,quantity,kind,reference,note,user_id) VALUES (?,?,?,?,?,?,?)', (product_id, batch_id, quantity, kind, str(reference), note, user['id']))
    conn.execute('UPDATE products SET stock=ROUND(stock+?,3) WHERE id=?', (quantity, product_id))


def take_stock(conn, user, product_id, quantity, kind, reference, include_expired=False):
    product = record(conn, 'products', product_id)
    batches = rows(conn, '''SELECT * FROM stock_batches WHERE product_id=? AND remaining>0
        AND (? OR expires_on IS NULL OR expires_on>=?)
        ORDER BY expires_on IS NULL,expires_on,received_at,id''', (product_id, int(include_expired), date.today().isoformat()))
    if sum(batch['remaining'] for batch in batches) + .00001 < quantity:
        fail(f"{product['product_name']}: không đủ tồn có thể sử dụng", 409)
    allocations = []
    remaining = quantity
    for batch in batches:
        if remaining < .00001:
            break
        qty = round(min(remaining, batch['remaining']), 3)
        conn.execute('UPDATE stock_batches SET remaining=ROUND(remaining-?,3) WHERE id=?', (qty, batch['id']))
        movement(conn, user, product_id, batch['id'], -qty, kind, reference)
        allocations.append((batch['id'], qty, batch['cost_price']))
        remaining = round(remaining - qty, 3)
    return allocations


def add_batch(conn, user, product_id, qty, cost, lot, expiry, kind, reference, note=''):
    batch = conn.execute('INSERT INTO stock_batches(product_id,lot_code,expires_on,remaining,cost_price) VALUES (?,?,?,?,?)', (product_id, lot, expiry, qty, cost)).lastrowid
    movement(conn, user, product_id, batch, qty, kind, reference, note)
    return batch


def products(conn, query=''):
    term = '%' + query.strip() + '%'
    result = rows(conn, '''SELECT p.*,COALESCE((SELECT SUM(remaining) FROM stock_batches b
        WHERE b.product_id=p.id AND (expires_on IS NULL OR expires_on>=?)),0) AS sellable_stock,
        CASE WHEN promo_until>=? AND promo_price IS NOT NULL THEN promo_price ELSE price END AS selling_price
        FROM products p WHERE product_name LIKE ? OR sku LIKE ? OR barcode LIKE ? ORDER BY active DESC,product_name''', (date.today().isoformat(), date.today().isoformat(), term, term, term))
    for product in result:
        product['sellable_stock'] = math.floor(round(product['sellable_stock'], 3))
    return result


def save_product(conn, user, data, ident=None):
    old = record(conn, 'products', ident) if ident else {}
    merged = {**old, **data}
    name, sku = required(merged, 'product_name', 'Tên hàng', 150), required(merged, 'sku', 'SKU', 64)
    barcode = str(merged.get('barcode', '')).strip()[:64]
    duplicate = one(conn, "SELECT id FROM products WHERE (sku=? OR (barcode=? AND barcode!='')) AND id!=?", (sku, barcode, ident or 0))
    if duplicate:
        fail('SKU hoặc mã vạch đã tồn tại', 409)
    values = (name, sku, barcode, money(merged.get('price', 0)), money(merged.get('cost_price', 0)), required(merged, 'unit', 'Đơn vị', 30), required(merged, 'zone_code', 'Khu/kệ', 40), str(merged.get('shelf_location', ''))[:100], quantity(merged.get('min_stock', 5), allow_zero=True), int(bool(merged.get('active', True))))
    if ident:
        conn.execute('UPDATE products SET product_name=?,sku=?,barcode=?,price=?,cost_price=?,unit=?,zone_code=?,shelf_location=?,min_stock=?,active=? WHERE id=?', (*values, ident))
    else:
        ident = conn.execute('INSERT INTO products(product_name,sku,barcode,price,cost_price,unit,zone_code,shelf_location,min_stock,active,stock) VALUES (?,?,?,?,?,?,?,?,?,?,0)', values).lastrowid
    audit(conn, user, 'SAVE_PRODUCT', ident, {'sku': sku, 'price': values[3], 'cost': values[4]})
    return {'success': True, 'id': ident}


def cash_shift(conn, user):
    shift = one(conn, 'SELECT * FROM cash_shifts WHERE user_id=? AND closed_at IS NULL', (user['id'],))
    if not shift:
        fail('Hãy mở ca thu ngân trước khi thu hoặc chi tiền mặt', 409)
    return shift['id']


def payment(conn, user, amount, method, kind, reference, order_id=None):
    if method not in {'CASH', 'TRANSFER', 'DEBT'}:
        fail('Phương thức thanh toán không hợp lệ')
    if method == 'CASH':
        shift = cash_shift(conn, user)
    else:
        opened = one(conn, 'SELECT id FROM cash_shifts WHERE user_id=? AND closed_at IS NULL', (user['id'],))
        shift = opened['id'] if opened else None
    conn.execute('INSERT INTO payments(order_id,amount,method,kind,cash_shift_id,reference,user_id) VALUES (?,?,?,?,?,?,?)', (order_id, amount, method, kind, shift, str(reference), user['id']))


def purchase(conn, user, data):
    supplier = record(conn, 'suppliers', data.get('supplier_id'))
    items = objects(data.get('items'), 'Phiếu nhập')
    normalized = []
    total = 0
    for item in items:
        p = record(conn, 'products', item.get('product_id'))
        qty = quantity(item.get('quantity'))
        cost = money(item.get('cost_price'))
        expiry = day(item['expires_on']) if item.get('expires_on') else None
        if expiry and expiry < date.today().isoformat():
            fail('Không nhập lô đã hết hạn')
        normalized.append((p['id'], qty, cost, str(item.get('lot_code') or secrets.token_hex(4))[:64], expiry))
        total = money(total + rounded(qty * cost))
    paid = money(data.get('paid', total))
    if paid > total:
        fail('Tiền trả vượt giá trị phiếu nhập')
    method = data.get('method', 'TRANSFER')
    if method not in {'CASH', 'TRANSFER'}:
        fail('Chọn tiền mặt hoặc chuyển khoản cho số tiền đã trả')
    ident = conn.execute('INSERT INTO purchase_receipts(supplier_id,total,paid,note,user_id) VALUES (?,?,?,?,?)', (supplier['id'], total, paid, str(data.get('note', ''))[:500], user['id'])).lastrowid
    for product_id, qty, cost, lot, expiry in normalized:
        batch = add_batch(conn, user, product_id, qty, cost, lot, expiry, 'PURCHASE', ident)
        conn.execute('INSERT INTO purchase_items(receipt_id,product_id,batch_id,quantity,cost_price) VALUES (?,?,?,?,?)', (ident, product_id, batch, qty, cost))
        conn.execute('UPDATE products SET cost_price=? WHERE id=?', (cost, product_id))
    if paid:
        payment(conn, user, -paid, method, 'PURCHASE', ident)
    conn.execute("INSERT INTO account_entries(party_type,party_id,amount,reference,user_id) VALUES ('SUPPLIER',?,?,?,?)", (supplier['id'], total - paid, f'PURCHASE:{ident}', user['id']))
    audit(conn, user, 'PURCHASE', ident, {'total': total, 'paid': paid})
    return {'success': True, 'id': ident, 'total': total}


def stock_count(conn, user, data):
    product = record(conn, 'products', data.get('product_id'))
    counted = quantity(data.get('counted'), allow_zero=True)
    note = required(data, 'note', 'Lý do kiểm kê')
    difference = round(counted - product['stock'], 3)
    ref = 'COUNT-' + secrets.token_hex(6)
    if difference < 0:
        take_stock(conn, user, product['id'], -difference, 'COUNT', ref, True)
    elif difference > 0:
        add_batch(conn, user, product['id'], difference, product['cost_price'], ref, None, 'COUNT', ref, note)
    audit(conn, user, 'STOCK_COUNT', product['id'], {'before': product['stock'], 'counted': counted, 'difference': difference, 'note': note})
    return {'success': True, 'difference': difference}


def parties(conn, kind):
    table = 'customers' if kind == 'CUSTOMER' else 'suppliers'
    return rows(conn, f'''SELECT p.*,COALESCE((SELECT SUM(amount) FROM account_entries e WHERE e.party_type=? AND e.party_id=p.id),0) AS debt FROM {table} p ORDER BY p.name''', (kind,))


def save_party(conn, user, kind, data, ident=None):
    table = 'customers' if kind == 'CUSTOMER' else 'suppliers'
    merged = {**(record(conn, table, ident) if ident else {}), **data}
    name = required(merged, 'name', 'Tên', 120)
    phone = str(merged.get('phone', ''))[:30]
    field = 'customer_group' if kind == 'CUSTOMER' else 'address'
    value = str(merged.get(field, 'RETAIL' if kind == 'CUSTOMER' else ''))[:200]
    if ident:
        conn.execute(f'UPDATE {table} SET name=?,phone=?,{field}=? WHERE id=?', (name, phone, value, ident))
    else:
        ident = conn.execute(f'INSERT INTO {table}(name,phone,{field}) VALUES (?,?,?)', (name, phone, value)).lastrowid
    audit(conn, user, 'SAVE_' + kind, ident, {'name': name})
    return {'success': True, 'id': ident}


def settle_debt(conn, user, kind, ident, data):
    if kind not in {'CUSTOMER', 'SUPPLIER'}:
        fail('Loại công nợ không hợp lệ')
    record(conn, 'customers' if kind == 'CUSTOMER' else 'suppliers', ident)
    amount = money(data.get('amount'))
    balance = one(conn, 'SELECT COALESCE(SUM(amount),0) AS n FROM account_entries WHERE party_type=? AND party_id=?', (kind, ident))['n']
    if not 0 < amount <= balance:
        fail('Số tiền phải lớn hơn 0 và không vượt dư nợ')
    method = data.get('method', 'CASH')
    if method not in {'CASH', 'TRANSFER'}:
        fail('Phương thức thanh toán không hợp lệ')
    ref = 'SETTLEMENT-' + secrets.token_hex(6)
    conn.execute('INSERT INTO account_entries(party_type,party_id,amount,reference,note,user_id) VALUES (?,?,?,?,?,?)', (kind, ident, -amount, ref, str(data.get('note', ''))[:500], user['id']))
    payment(conn, user, amount if kind == 'CUSTOMER' else -amount, method, 'DEBT_SETTLEMENT', ref)
    audit(conn, user, 'SETTLE_DEBT', ident, {'party_type': kind, 'amount': amount})
    return {'success': True}


def suggestions(conn):
    result = []
    today = date.today()
    for product in products(conn):
        if not product['active']:
            continue
        if product['sellable_stock'] <= product['min_stock']:
            result.append({'key': f"LOW:{product['id']}", 'product_id': product['id'], 'name': product['product_name'], 'type': 'LOW', 'reason': f"Tồn bán được {product['sellable_stock']:g}, ngưỡng đặt hàng {product['min_stock']:g}", 'action': 'Tạo phiếu nhập hàng'})
        sold = one(conn, "SELECT COALESCE(SUM(-quantity),0) AS n FROM stock_movements WHERE product_id=? AND kind='SALE' AND created_at>=?", (product['id'], (today - timedelta(days=30)).isoformat()))['n']
        first = one(conn, 'SELECT MIN(received_at) AS d FROM stock_batches WHERE product_id=?', (product['id'],))['d']
        if product['stock'] > 0 and sold == 0 and first and first[:10] <= (today - timedelta(days=30)).isoformat():
            result.append({'key': f"SLOW:{product['id']}", 'product_id': product['id'], 'name': product['product_name'], 'type': 'SLOW', 'reason': 'Có tồn từ ít nhất 30 ngày và chưa bán trong 30 ngày gần nhất', 'action': 'Giảm giá 10% trong 7 ngày'})
    for batch in rows(conn, '''SELECT b.*,p.product_name FROM stock_batches b JOIN products p ON p.id=b.product_id WHERE remaining>0 AND expires_on<=? ORDER BY expires_on''', ((today + timedelta(days=7)).isoformat(),)):
        expired = batch['expires_on'] < today.isoformat()
        result.append({'key': f"{'EXPIRED' if expired else 'EXPIRING'}:{batch['id']}", 'product_id': batch['product_id'], 'name': batch['product_name'], 'type': 'EXPIRED' if expired else 'EXPIRING', 'reason': f"Lô {batch['lot_code']}, còn {batch['remaining']:g}, hạn {batch['expires_on']}", 'action': 'Kiểm kê loại bỏ lô hết hạn' if expired else 'Giảm giá 20% đến ngày hết hạn', 'expires_on': batch['expires_on']})
    return result


def apply_suggestion(conn, user, key):
    suggestion = next((s for s in suggestions(conn) if s['key'] == key), None)
    if not suggestion:
        fail('Đề xuất không còn phù hợp với dữ liệu hiện tại', 409)
    if suggestion['type'] not in {'SLOW', 'EXPIRING'}:
        fail('Đề xuất này cần xử lý bằng phiếu nhập hoặc kiểm kê')
    p = record(conn, 'products', suggestion['product_id'])
    price = rounded(p['price'] * (.8 if suggestion['type'] == 'EXPIRING' else .9))
    until = suggestion.get('expires_on') or (date.today() + timedelta(days=7)).isoformat()
    conn.execute('UPDATE products SET promo_price=?,promo_until=? WHERE id=?', (price, until, p['id']))
    audit(conn, user, 'APPLY_PROMOTION', p['id'], {'key': key, 'price': price, 'until': until})
    return {'success': True, 'price': price, 'until': until}

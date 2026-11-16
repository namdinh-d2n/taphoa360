"""Local expiry planning, basket associations and bounded rescue combos.

Demand estimates keep the recent sales rate constant. They do not invent a
sales uplift for discounts. All prices, stock and caps are rechecked at sale.
"""
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING
import math
import unicodedata

from .common import audit, fail, money, quantity, record, rounded
from .database import one, rows

MIN_MARGIN_PERCENT = 10


def selling_price(product):
    return product['promo_price'] if product['promo_price'] is not None and (product['promo_until'] or '') >= date.today().isoformat() else product['price']


def batches(conn, product_id):
    from .inventory import local_now
    return rows(conn, '''SELECT * FROM stock_batches WHERE product_id=? AND remaining>0
        AND (expires_on IS NULL OR expires_on>=?) AND quality_status='SELLABLE' AND (sell_until IS NULL OR sell_until>?)
        ORDER BY expires_on IS NULL,expires_on,received_at,id''', (product_id, local_now()[:10],local_now()))


def ceil_number(value):
    return int(Decimal(str(value)).to_integral_value(rounding=ROUND_CEILING))


def cost_for(conn, product_id, count):
    left, total = Decimal(str(count)), Decimal(0)
    for batch in batches(conn, product_id):
        take = min(left, Decimal(str(batch['remaining'])))
        if take and batch['cost_price'] <= 0:
            fail('Cần khai báo giá vốn các lô sẽ bán trước khi tạo combo.', 409)
        total += take * batch['cost_price']
        left -= take
        if left <= 0:
            return ceil_number(total)
    fail('Không còn đủ tồn có thể bán cho combo.', 409)


def combination(conn, batch_id, partner_id):
    batch = record(conn, 'stock_batches', batch_id)
    product = record(conn, 'products', batch['product_id'])
    partner = record(conn, 'products', partner_id)
    today = date.today().isoformat()
    if not batch['expires_on'] or batch['expires_on'] < today or batch['remaining'] < 1:
        fail('Lô đã hết hạn, hết hàng hoặc không còn đủ một đơn vị để giải cứu.', 409)
    if not product['active'] or not partner['active'] or product['id'] == partner['id']:
        fail('Chọn hai sản phẩm khác nhau đang bán.', 409)
    first = batches(conn, product['id'])
    if not first or first[0]['id'] != batch['id']:
        fail('Cần bán lô có hạn sớm hơn của sản phẩm này trước.', 409)
    partner_batches = batches(conn, partner['id'])
    stock = math.floor(round(sum(b['remaining'] for b in partner_batches), 3))
    capacity = min(math.floor(batch['remaining']), stock)
    if capacity < 1:
        fail('Mặt hàng ghép không còn đủ tồn có thể bán.', 409)
    return batch, product, partner, capacity


def quote(conn, data):
    batch, product, partner, capacity = combination(conn, data.get('batch_id'), data.get('partner_id'))
    sets = quantity(data.get('max_sets', capacity))
    if sets > capacity:
        fail('Số combo vượt tồn khả dụng của lô hoặc hàng ghép.', 409)
    discount = quantity(data.get('discount_percent', 15), allow_zero=True)
    if discount > 50:
        fail('Mức giảm combo từ 0 đến 50%.')
    # A price that protects every set, even as FEFO advances to a dearer partner lot.
    anchor_cost = cost_for(conn, product['id'], sets)
    partner_cost = cost_for(conn, partner['id'], sets)
    left, partner_max = sets, 0
    for candidate in batches(conn, partner['id']):
        if left <= 0: break
        partner_max = max(partner_max, candidate['cost_price'])
        left -= candidate['remaining']
    cost_ceiling = batch['cost_price'] + partner_max
    regular = money(selling_price(product) + selling_price(partner))
    floor = ceil_number(Decimal(cost_ceiling) * 100 / (100 - MIN_MARGIN_PERCENT))
    if regular <= 0 or floor > regular:
        fail('Giá bán hiện tại chưa đủ lãi gộp tối thiểu 10%. Hãy kiểm tra giá bán và giá vốn.', 409)
    price = max(floor, rounded(Decimal(regular) * (100 - discount) / 100))
    if price >= regular:
        fail('Chưa có khoảng giá để giảm mà vẫn giữ lãi gộp tối thiểu 10%.', 409)
    total_cost = anchor_cost + partner_cost
    revenue = money(price*sets)
    days = (date.fromisoformat(batch['expires_on']) - date.today()).days + 1
    return {'batch_id': batch['id'], 'product_id': product['id'], 'partner_id': partner['id'],
            'product_name': product['product_name'], 'partner_name': partner['product_name'],
            'product_unit': product['unit'], 'partner_unit': partner['unit'],
            'regular_price': regular, 'price': price, 'max_sets': sets, 'capacity': capacity,
            'discount_percent': discount, 'actual_discount_percent': round((regular-price)*100/regular, 1),
            'margin_floor_applied': price > rounded(Decimal(regular)*(100-discount)/100),
            'cost_total': total_cost, 'revenue_if_all_sold': revenue,
            'gross_profit_if_all_sold': revenue-total_cost,
            'min_gross_profit_per_set': price-cost_ceiling,
            'min_margin_percent': MIN_MARGIN_PERCENT, 'sets_per_day': ceil_number(Decimal(sets)/days),
            'expires_on': batch['expires_on']}


def create_campaign(conn, user, data):
    current = quote(conn, data)
    if money(data.get('expected_price')) != current['price']:
        fail('Giá đã thay đổi. Hãy xem lại phương án trước khi bật combo.', 409)
    if one(conn, 'SELECT id FROM rescue_campaigns WHERE batch_id=? AND active=1 AND expires_on>=?',
           (current['batch_id'], date.today().isoformat())):
        fail('Lô này đã có combo đang bật. Hãy dừng combo cũ trước khi tạo phương án mới.', 409)
    name = ('Giải cứu ' + current['product_name'] + ' + ' + current['partner_name'])[:200]
    ident = conn.execute('''INSERT INTO rescue_campaigns(name,batch_id,product_id,partner_id,price,max_sets,expires_on,user_id)
        VALUES (?,?,?,?,?,?,?,?)''', (name,current['batch_id'],current['product_id'],current['partner_id'],
                                   current['price'],current['max_sets'],current['expires_on'],user['id'])).lastrowid
    audit(conn, user, 'CREATE_RESCUE_COMBO', ident, current)
    return {'success': True, 'id': ident, 'quote': current}


def campaign_state(conn, campaign):
    used = one(conn, '''SELECT COALESCE(SUM(rescue_sets),0) AS n FROM orders
        WHERE rescue_campaign_id=? AND status!='CANCELLED' ''', (campaign['id'],))['n']
    if one(conn,"SELECT name FROM sqlite_master WHERE type='table' AND name='online_orders'"):
        used+=one(conn,"SELECT COALESCE(SUM(rescue_sets),0) n FROM online_orders WHERE rescue_campaign_id=? AND stock_reserved=1 AND status IN ('PENDING','PAYMENT_REVIEW','CONFIRMED','SHIPPING')",(campaign['id'],))['n']
    result = {**campaign, 'used_sets': used, 'available_sets': 0, 'reason': ''}
    if not campaign['active']:
        result['reason'] = 'Đã dừng'
    elif campaign['expires_on'] < date.today().isoformat():
        result['reason'] = 'Đã hết hạn'
    elif used >= campaign['max_sets']:
        result['reason'] = 'Đã dùng hết giới hạn combo'
    else:
        try:
            batch, product, partner, capacity = combination(conn, campaign['batch_id'], campaign['partner_id'])
            capacity = min(capacity, campaign['max_sets'] - used)
            # Current costs/prices may have changed since the owner approved the offer.
            cost_for(conn, product['id'], capacity)
            cost_for(conn, partner['id'], capacity)
            max_partner_cost = max(b['cost_price'] for b in batches(conn,partner['id'])[:1])
            left = capacity
            for b in batches(conn,partner['id']):
                if left <= 0: break
                max_partner_cost = max(max_partner_cost,b['cost_price']); left -= b['remaining']
            if campaign['price'] * (100-MIN_MARGIN_PERCENT) < (batch['cost_price']+max_partner_cost)*100:
                result['reason'] = 'Giá vốn thay đổi; cần chủ tiệm xem lại giá combo'
            elif campaign['price'] >= selling_price(product) + selling_price(partner):
                result['reason'] = 'Giá bán hiện tại đã bằng hoặc thấp hơn giá combo'
            else:
                result['available_sets'] = capacity
                result['regular_price'] = selling_price(product)+selling_price(partner)
                result['product_name'], result['partner_name'] = product['product_name'], partner['product_name']
                result['product_unit'], result['partner_unit'] = product['unit'], partner['unit']
        except Exception as exc:
            from fastapi import HTTPException
            if not isinstance(exc, HTTPException): raise
            result['reason'] = exc.detail
    return result


def campaigns(conn, include_unavailable=False):
    values = [campaign_state(conn, c) for c in rows(conn, 'SELECT * FROM rescue_campaigns ORDER BY id DESC LIMIT 200')]
    if not include_unavailable:
        values = [c for c in values if c['available_sets'] > 0]
    return values


def checkout_discount(conn, campaign_id, sets, normalized):
    campaign = campaign_state(conn, record(conn,'rescue_campaigns',campaign_id))
    if not campaign['available_sets'] or sets > campaign['available_sets']:
        fail(campaign['reason'] or 'Combo không còn đủ số lượng. Hãy tải lại giỏ hàng.', 409)
    lookup = {p['id']:(qty,price) for p,qty,price,_ in normalized}
    pair = [campaign['product_id'],campaign['partner_id']]
    if any(ident not in lookup or lookup[ident][0] < sets for ident in pair):
        fail('Giỏ hàng cần đủ hai mặt hàng cho số combo đã chọn.')
    base = sum(lookup[ident][1] for ident in pair)
    discount = money((base-campaign['price'])*sets)
    first = rounded(Decimal(discount)*lookup[pair[0]][1]/base)
    return campaign, discount, {pair[0]: first, pair[1]: discount-first}


def _group(name):
    text = ''.join(c for c in unicodedata.normalize('NFD',name.lower().replace('đ','d')) if not unicodedata.combining(c))
    for group, terms in [('bread',['banh']),('dairy',['sua','pho mai']),('noodles',['mi ','bun','pho ']),
                         ('drink',['nuoc','tra ','ca phe']),('beer',['bia']),('snack',['hat ','snack','kho ga','kho bo'])]:
        if any(term in text for term in terms): return group
    return ''


def analyze(conn, horizon=7):
    today = date.today()
    if not 1 <= horizon <= 30: fail('Chọn khoảng cận hạn từ 1 đến 30 ngày.')
    start = today - timedelta(days=27)
    catalog = {p['id']:p for p in rows(conn,'SELECT * FROM products WHERE active=1')}
    all_batches = rows(conn, '''SELECT b.* FROM stock_batches b JOIN products p ON p.id=b.product_id
        WHERE remaining>0 AND p.active=1 ORDER BY expires_on IS NULL,expires_on,received_at,b.id''')
    grouped = defaultdict(list)
    for b in all_batches: grouped[b['product_id']].append(b)
    sales = rows(conn, '''SELECT i.product_id,SUM(i.quantity-i.returned_qty) AS units,COUNT(DISTINCT o.id) AS orders
        FROM order_items i JOIN orders o ON o.id=i.order_id
        WHERE o.managed=1 AND o.status IN ('COMPLETED','PARTIAL_RETURN') AND date(o.created_at) BETWEEN ? AND ?
        AND i.quantity>i.returned_qty GROUP BY i.product_id''',(start.isoformat(),today.isoformat()))
    stats = {s['product_id']:s for s in sales}
    first = one(conn, "SELECT MIN(date(created_at)) AS d FROM orders WHERE managed=1 AND status IN ('COMPLETED','PARTIAL_RETURN')")['d']
    observed = max(0,(today-max(start,date.fromisoformat(first))).days+1) if first else 0
    # Distinct orders prevent duplicate lines from inflating basket support.
    baskets = rows(conn, '''SELECT DISTINCT o.id,i.product_id FROM orders o JOIN order_items i ON i.order_id=o.id
        WHERE o.managed=1 AND o.status IN ('COMPLETED','PARTIAL_RETURN') AND date(o.created_at) BETWEEN ? AND ?
        AND i.quantity>i.returned_qty''',(start.isoformat(),today.isoformat()))
    order_products = defaultdict(set)
    for value in baskets: order_products[value['id']].add(value['product_id'])
    pair_counts = Counter()
    for ids in order_products.values():
        for a in ids:
            for b in ids:
                if a!=b: pair_counts[a,b]+=1
    stock = {pid:sum(b['remaining'] for b in values if not b['expires_on'] or b['expires_on']>=today.isoformat()) for pid,values in grouped.items()}
    items, expired = [], []
    complements = {frozenset(pair) for pair in [('bread','dairy'),('bread','drink'),('noodles','drink'),('beer','snack')]}
    for pid, values in grouped.items():
        p = catalog[pid]
        stat = stats.get(pid,{'units':0,'orders':0})
        reliable = observed>=7 and stat['orders']>=3
        rate = stat['units']/observed if reliable else None
        simulated = {b['id']:0.0 for b in values}
        remaining = {b['id']:b['remaining'] for b in values}
        if rate is not None:
            for offset in range(horizon+1):
                current = (today+timedelta(days=offset)).isoformat(); capacity=rate
                for b in values:
                    if b['expires_on'] and b['expires_on']<current: continue
                    used = min(remaining[b['id']],capacity)
                    simulated[b['id']]+=used; remaining[b['id']]-=used; capacity-=used
                    if capacity<=0: break
        first_valid = next((b['id'] for b in values if not b['expires_on'] or b['expires_on']>=today.isoformat()),None)
        for b in values:
            if not b['expires_on'] or b['expires_on']>(today+timedelta(days=horizon)).isoformat(): continue
            days=(date.fromisoformat(b['expires_on'])-today).days+1
            base={'batch_id':b['id'],'product_id':pid,'name':p['product_name'],'unit':p['unit'],
                  'lot_code':b['lot_code'],'expires_on':b['expires_on'],'remaining':b['remaining'],
                  'cost_price':b['cost_price'],'days_left':max(days,0),'first_in_fefo':first_valid==b['id']}
            if days<=0:
                expired.append(base); continue
            prior=sum(other['remaining'] for other in values if (other['expires_on'] is None or other['expires_on']>=today.isoformat()) and values.index(other)<=values.index(b))
            partners=[]
            for partner_id, partner in catalog.items():
                if partner_id==pid or stock.get(partner_id,0)<1: continue
                support=pair_counts[pid,partner_id]
                heuristic=frozenset((_group(p['product_name']),_group(partner['product_name']))) in complements
                partners.append({'id':partner_id,'name':partner['product_name'],'unit':partner['unit'],
                                 'co_orders':support,'basis':'history' if support>=3 else 'category' if heuristic else 'manual',
                                 'price':selling_price(partner)})
            partners.sort(key=lambda x:(x['basis']=='history',x['co_orders'],x['basis']=='category'),reverse=True)
            suggested = next((v for v in partners if v['basis']!='manual'), None)
            scenario=None; blocked=''
            if b['id']!=first_valid: blocked='Ưu tiên bán lô có hạn sớm hơn trước.'
            elif b['remaining']<1: blocked='Lô còn lượng lẻ dưới một đơn vị; cần kiểm kê trước.'
            elif suggested:
                try: scenario=quote(conn,{'batch_id':b['id'],'partner_id':suggested['id'],'discount_percent':25 if days<=2 else 20 if days<=4 else 10})
                except Exception as exc:
                    from fastapi import HTTPException
                    if not isinstance(exc,HTTPException): raise
                    blocked=exc.detail
            items.append({**base,'daily_target':ceil_number(Decimal(str(prior))/days),
                          'daily_sales':round(rate,2) if rate is not None else None,'observed_days':observed,
                          'sales_orders':stat['orders'],'expected_unsold':round(max(0,b['remaining']-simulated[b['id']]),3) if reliable else None,
                          'partners':partners,'suggested_partner':suggested,'suggested_quote':scenario,'blocked':blocked})
    items.sort(key=lambda item:(item['expires_on'],-item['remaining']))
    return {'as_of':today.isoformat(),'horizon_days':horizon,'history_days':28,'items':items,'expired':expired,
            'campaigns':campaigns(conn,True),'note':'Ước tính giữ nguyên tốc độ bán gần đây, chưa tính việc tăng nhu cầu do giảm giá. Lãi gộp chưa trừ chi phí vận hành.'}

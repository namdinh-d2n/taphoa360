"""Payment-first QR orders, staff approval, invoices and accountable online money."""
from datetime import datetime,timedelta
from pathlib import Path
import hashlib,json,sqlite3
import config
from .database import reading,transaction,rows,one,add_columns
from .common import fail,required,money,record,audit,objects
from . import commerce as shop,inventory as stock


def migrate_workflow():
    with reading() as conn:
        if one(conn,'SELECT version FROM schema_migrations WHERE version=9'):return
        folder=Path(config.SQLITE_PATH).parent/'backups';folder.mkdir(exist_ok=True)
        target=sqlite3.connect(folder/('before-v9-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db'))
        try:conn.backup(target)
        finally:target.close()
    with transaction() as conn:
        add_columns(conn,'online_orders',{'payment_flow':"TEXT NOT NULL DEFAULT 'LEGACY'",'payment_status':"TEXT NOT NULL DEFAULT 'UNPAID'",'payment_reported_at':'TEXT','payment_note':"TEXT NOT NULL DEFAULT ''",'bank_snapshot':"TEXT NOT NULL DEFAULT ''",'stock_reserved':'INTEGER NOT NULL DEFAULT 0','picker_id':'INTEGER REFERENCES users(id)'})
        add_columns(conn,'online_items',{'is_picked':'INTEGER NOT NULL DEFAULT 0'})
        add_columns(conn,'shop_settings',{'online_cashier_id':'INTEGER REFERENCES users(id)','online_dispatcher_id':'INTEGER REFERENCES users(id)'})
        add_columns(conn,'payments',{'online_order_id':'INTEGER REFERENCES online_orders(id)','online_note':"TEXT NOT NULL DEFAULT ''"})
        conn.execute('''CREATE TABLE online_invoices(id INTEGER PRIMARY KEY, online_order_id INTEGER NOT NULL UNIQUE REFERENCES online_orders(id), code TEXT NOT NULL UNIQUE, issued_by INTEGER REFERENCES users(id), issued_at TEXT NOT NULL, snapshot TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE online_cash_handovers(id INTEGER PRIMARY KEY,collector_id INTEGER NOT NULL REFERENCES users(id),receiver_id INTEGER NOT NULL REFERENCES users(id),amount INTEGER NOT NULL CHECK(amount>0),reference TEXT NOT NULL UNIQUE,note TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL)''')
        conn.execute('''CREATE TABLE online_finance_keys(key TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),request_hash TEXT NOT NULL,payment_id INTEGER NOT NULL REFERENCES payments(id))''')
        conn.execute("UPDATE online_orders SET stock_reserved=1 WHERE status IN ('CONFIRMED','SHIPPING')")
        conn.execute("UPDATE online_orders SET payment_status='VERIFIED' WHERE paid>0")
        conn.execute("UPDATE payments SET online_order_id=(SELECT o.id FROM online_orders o WHERE payments.reference=o.code OR payments.reference LIKE o.code||':%' LIMIT 1) WHERE kind IN ('ONLINE_PREPAY','ONLINE_COD','ONLINE_REFUND')")
        conn.execute('INSERT INTO schema_migrations(version) VALUES(9)')


def permissions(conn,user):
    settings=one(conn,'SELECT online_cashier_id,online_dispatcher_id FROM shop_settings WHERE id=1')
    return {'money':user['role']=='owner' or (user['role']=='cashier' and (not settings['online_cashier_id'] or settings['online_cashier_id']==user['id'])),
            'dispatch':user['role']=='owner' or (user['role'] in {'cashier','inventory'} and (not settings['online_dispatcher_id'] or settings['online_dispatcher_id']==user['id']))}


def require_permission(conn,user,kind):
    if not permissions(conn,user)[kind]:fail('Tài khoản chưa được phân công phụ trách '+('thu chi online.' if kind=='money' else 'điều phối đơn online.'),403)


def reserve(conn,order,user):
    if order['stock_reserved']:return
    items=rows(conn,'SELECT * FROM online_items WHERE online_order_id=?',(order['id'],))
    for item in items:
        allocation=stock.take_stock(conn,user,item['product_id'],item['quantity'],'ONLINE_HOLD',order['id'])
        conn.execute('UPDATE online_items SET allocations=? WHERE id=?',(json.dumps(allocation),item['id']))
    conn.execute('UPDATE online_orders SET stock_reserved=1 WHERE id=?',(order['id'],))


def release(conn,order,user,kind='ONLINE_RELEASE'):
    if not order['stock_reserved']:return
    for item in rows(conn,'SELECT * FROM online_items WHERE online_order_id=?',(order['id'],)):
        for bid,qty,cost in json.loads(item['allocations']):
            conn.execute('UPDATE stock_batches SET remaining=remaining+? WHERE id=?',(qty,bid))
            stock.movement(conn,user,item['product_id'],bid,qty,kind,order['id'])
        conn.execute("UPDATE online_items SET allocations='[]',is_picked=0 WHERE id=?",(item['id'],))
    conn.execute('UPDATE online_orders SET stock_reserved=0 WHERE id=?',(order['id'],))


def begin_payment(conn,order):
    settings=one(conn,'SELECT bank_bin,bank_account,bank_name FROM shop_settings WHERE id=1')
    conn.execute("UPDATE online_orders SET payment_flow='PREPAY',bank_snapshot=?,payment_status='UNPAID' WHERE id=?",(json.dumps(settings,ensure_ascii=False),order['id']))
    reserve(conn,order,{'id':None})
    shop.event(conn,order['id'],'PENDING','Đã giữ hàng 30 phút. Quét QR rồi bấm Xác nhận đã thanh toán để cửa hàng đối chiếu.')


def report(conn,order,data):
    if order['payment_method']!='QR' or order['payment_flow']!='PREPAY':fail('Đơn này không dùng luồng QR trả trước.',409)
    if order['paid'] or order['status'] in {'CONFIRMED','SHIPPING','COMPLETED'}:fail('Tiệm đã xử lý thanh toán đơn này.',409)
    if order['payment_status']=='REPORTED':return {'success':True,'replayed':True}
    note=str(data.get('note','')).strip()[:250]
    status='PAYMENT_REVIEW' if order['status'] in {'PENDING','REVIEW'} else order['status']
    conn.execute("UPDATE online_orders SET payment_status='REPORTED',payment_reported_at=?,payment_note=?,status=?,updated_at=? WHERE id=?",(shop.clock(),note,status,shop.clock(),order['id']))
    shop.event(conn,order['id'],status,'Khách báo đã chuyển khoản. Chờ thu ngân/chủ tiệm đối chiếu; đây chưa phải xác nhận tiền vào ngân hàng.')
    return {'success':True}


def validate_held(conn,order):
    if not order['stock_reserved']:fail('Đơn không còn giữ hàng; cần đối chiếu và xử lý hoàn tiền.',409)
    for item in rows(conn,'SELECT allocations,product_id FROM online_items WHERE online_order_id=?',(order['id'],)):
        p=record(conn,'products',item['product_id'])
        if not p['active'] or not p['online_enabled']:fail('Có hàng ngừng bán. Cần hủy đơn và đối chiếu/hoàn tiền.',409)
        for bid,qty,cost in json.loads(item['allocations']):
            b=record(conn,'stock_batches',bid)
            if b['quality_status']!='SELLABLE' or (b['expires_on'] and b['expires_on']<shop.clock()[:10]) or (b['sell_until'] and b['sell_until']<=shop.clock()):fail('Lô không còn đủ điều kiện giao; hủy để đối chiếu và hoàn tiền.',409)


def issue_invoice(conn,user,order):
    old=one(conn,'SELECT id FROM online_invoices WHERE online_order_id=?',(order['id'],))
    if old:return old['id']
    document=shop.detail(conn,order,True)
    for field in ['bank','payment_note']:document.pop(field,None)
    ident=conn.execute('INSERT INTO online_invoices(online_order_id,code,issued_by,issued_at,snapshot) VALUES(?,?,?,?,?)',
        (order['id'],'HD-'+order['code'],user['id'],shop.clock(),json.dumps(document,ensure_ascii=False))).lastrowid
    return ident


def approve(conn,user,order,data):
    require_permission(conn,user,'money')
    amount=money(data.get('amount'));reference=required(data,'reference','Mã giao dịch ngân hàng',100)
    if order['payment_status']=='VERIFIED' and order['paid']==amount and order['payment_reference']==reference:return {'success':True,'replayed':True}
    if order['payment_method']!='QR' or order['payment_flow']!='PREPAY' or order['payment_status']!='REPORTED' or order['paid']:fail('Cần khách báo đã thanh toán trước khi đối chiếu.',409)
    if amount!=order['goods_total']+order['shipping_fee']:fail('Số tiền thực nhận cần khớp tổng đơn.')
    if one(conn,'SELECT id FROM online_orders WHERE payment_reference=? AND id!=?',(reference,order['id'])):fail('Mã giao dịch đã dùng cho đơn khác.',409)
    terminal=order['status'] in {'CANCELLED','EXPIRED'}
    if not terminal:validate_held(conn,order)
    if any(data.get(field) for field in ['picker_id','shipper_id']):require_permission(conn,user,'dispatch')
    for field,roles in [('picker_id',{'inventory','cashier'}),('shipper_id',{'shipper'})]:
        if data.get(field):
            person=record(conn,'users',data[field])
            if not person['active'] or person['role'] not in roles:fail('Chọn nhân viên đúng vai trò đang hoạt động.')
            conn.execute('UPDATE online_orders SET '+field+'=? WHERE id=?',(person['id'],order['id']))
    shop.money_entry(conn,user,order,amount,'TRANSFER','ONLINE_PREPAY',reference=reference)
    conn.execute("UPDATE online_orders SET paid=?,payment_reference=?,payment_status='VERIFIED',status=?,refund_due=?,updated_at=? WHERE id=?",
        (amount,reference,order['status'] if terminal else 'CONFIRMED',amount if terminal else order['refund_due'],shop.clock(),order['id']))
    if not terminal:issue_invoice(conn,user,record(conn,'online_orders',order['id']))
    shop.event(conn,order['id'],order['status'] if terminal else 'CONFIRMED','Đã đối chiếu nhận '+str(amount)+'đ. '+('Đơn đã hủy/hết hạn: chờ hoàn toàn bộ tiền.' if terminal else 'Đã duyệt đơn, xuất hóa đơn và chuyển sang chuẩn bị giao.'))
    audit(conn,user,'APPROVE_ONLINE_PAYMENT',order['id'],{'amount':amount,'reference':reference,'refund':terminal})
    return {'success':True,'refund_required':terminal}


def reject_report(conn,user,order,data):
    require_permission(conn,user,'money')
    if order['payment_status']!='REPORTED' or order['paid']:fail('Đơn không chờ đối chiếu thanh toán.',409)
    reason=required(data,'reason','Lý do chưa xác minh được tiền',400)
    pending=order['status']=='PAYMENT_REVIEW'
    conn.execute("UPDATE online_orders SET payment_status='UNPAID',status=?,expires_at=?,updated_at=? WHERE id=?",('PENDING' if pending else order['status'],(datetime.fromisoformat(shop.clock())+timedelta(minutes=30)).isoformat(),shop.clock(),order['id']))
    shop.event(conn,order['id'],'PENDING' if pending else order['status'],'Chưa xác minh được giao dịch: '+reason)
    audit(conn,user,'REJECT_ONLINE_PAYMENT_REPORT',order['id'],{'reason':reason})


def prepare(conn,user,order,data):
    if user['role']!='owner' and user['id']!=order['picker_id']:require_permission(conn,user,'dispatch')
    if order['status']!='CONFIRMED':fail('Chỉ soạn đơn đã duyệt.',409)
    if data.get('picker_id'):
        require_permission(conn,user,'dispatch')
        person=record(conn,'users',data['picker_id'])
        if not person['active'] or person['role'] not in {'cashier','inventory'}:fail('Chọn thu ngân/kiểm kho đang hoạt động.')
        conn.execute('UPDATE online_orders SET picker_id=? WHERE id=?',(person['id'],order['id']))
    if 'items' in data:
        seen=set()
        for item in objects(data['items'],'Danh sách soạn hàng',maximum=50):
            line=record(conn,'online_items',item.get('item_id'))
            if line['online_order_id']!=order['id'] or line['id'] in seen:fail('Chi tiết soạn hàng không hợp lệ.')
            seen.add(line['id']);conn.execute('UPDATE online_items SET is_picked=? WHERE id=?',(int(bool(item.get('picked'))),line['id']))
    audit(conn,user,'PREPARE_ONLINE_ORDER',order['id'],{})


def finance(conn):
    entries=rows(conn,'''SELECT p.*,o.code,u.name AS actor FROM payments p LEFT JOIN online_orders o ON o.id=p.online_order_id LEFT JOIN users u ON u.id=p.user_id
        WHERE p.online_order_id IS NOT NULL OR p.kind='ONLINE_EXPENSE' ORDER BY p.id DESC LIMIT 300''')
    totals=one(conn,"SELECT COALESCE(SUM(CASE WHEN amount>0 THEN amount ELSE 0 END),0) income,COALESCE(SUM(CASE WHEN amount<0 THEN -amount ELSE 0 END),0) expense FROM payments WHERE online_order_id IS NOT NULL OR kind='ONLINE_EXPENSE'")
    reports=one(conn,"SELECT COUNT(*) n FROM online_orders WHERE payment_status='REPORTED' AND paid=0")['n']
    refund=one(conn,'SELECT COALESCE(SUM(MAX(0,refund_due-refund_paid)),0) n FROM online_orders')['n']
    collectors=rows(conn,'''SELECT u.id,u.name,COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.user_id=u.id AND p.kind='ONLINE_COD'),0) collected,
        COALESCE((SELECT SUM(h.amount) FROM online_cash_handovers h WHERE h.collector_id=u.id),0) handed_over FROM users u
        WHERE EXISTS(SELECT 1 FROM payments p WHERE p.user_id=u.id AND p.kind='ONLINE_COD')''')
    for c in collectors:c['outstanding']=c['collected']-c['handed_over']
    return {'entries':entries,'totals':{**totals,'net':totals['income']-totals['expense'],'payment_reports':reports,'refund_pending':refund},'collectors':collectors,
        'handovers':rows(conn,'''SELECT h.*,c.name collector,r.name receiver FROM online_cash_handovers h JOIN users c ON c.id=h.collector_id JOIN users r ON r.id=h.receiver_id ORDER BY h.id DESC LIMIT 100''')}


def expense(conn,user,data,key):
    require_permission(conn,user,'money')
    if not isinstance(key,str) or not 8<=len(key)<=128:fail('Thiếu mã chống ghi trùng khoản chi.')
    fingerprint=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    previous=one(conn,'SELECT * FROM online_finance_keys WHERE key=?',(key,))
    if previous:
        if previous['request_hash']!=fingerprint or previous['user_id']!=user['id']:fail('Mã khoản chi đã dùng cho yêu cầu khác.',409)
        return {'success':True,'replayed':True}
    amount=money(data.get('amount'));method=data.get('method');note=required(data,'note','Lý do/biên nhận chi',500)
    if not amount or method not in {'CASH','TRANSFER'}:fail('Nhập khoản chi dương và tiền mặt/chuyển khoản.')
    ident=conn.execute("INSERT INTO payments(amount,method,kind,reference,user_id,online_note) VALUES(?,?,'ONLINE_EXPENSE',?,?,?)",(-amount,method,'EXP-'+key,user['id'],note)).lastrowid
    conn.execute('INSERT INTO online_finance_keys VALUES(?,?,?,?)',(key,user['id'],fingerprint,ident))
    audit(conn,user,'ONLINE_EXPENSE',ident,{'amount':amount,'method':method,'note':note});return {'success':True}


def handover(conn,user,data):
    require_permission(conn,user,'money');collector=record(conn,'users',data.get('collector_id'))
    amount=money(data.get('amount'));reference=required(data,'reference','Biên nhận bàn giao',100)
    old=one(conn,'SELECT * FROM online_cash_handovers WHERE reference=?',(reference,))
    if old:
        if old['collector_id']==collector['id'] and old['amount']==amount:return {'success':True,'replayed':True}
        fail('Biên nhận đã sử dụng.',409)
    total=one(conn,"SELECT COALESCE(SUM(amount),0) n FROM payments WHERE user_id=? AND kind='ONLINE_COD'",(collector['id'],))['n']
    given=one(conn,'SELECT COALESCE(SUM(amount),0) n FROM online_cash_handovers WHERE collector_id=?',(collector['id'],))['n']
    if not amount or amount>total-given:fail('Số bàn giao vượt tiền COD nhân viên còn phải nộp.')
    conn.execute('INSERT INTO online_cash_handovers(collector_id,receiver_id,amount,reference,note,created_at) VALUES(?,?,?,?,?,?)',(collector['id'],user['id'],amount,reference,str(data.get('note',''))[:500],shop.clock()))
    audit(conn,user,'ONLINE_CASH_HANDOVER',collector['id'],{'amount':amount,'reference':reference});return {'success':True}

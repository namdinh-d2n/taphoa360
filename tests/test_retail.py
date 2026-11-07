"""Integration tests against isolated SQLite databases, never the local shop database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient
import config
import db
from app import app
from retail.database import reading, transaction, one, rows, migrate


class RetailTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='taphoa-test-')
        self.original = config.SQLITE_PATH, db.SQLITE_PATH
        config.SQLITE_PATH = db.SQLITE_PATH = str(Path(self.folder.name) / 'shop.db')
        self.client = TestClient(app)
        self.client.__enter__()
        self.post('/api/setup', {'username': 'owner', 'name': 'Test Owner', 'password': 'test-password-123'})
        self.login()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        config.SQLITE_PATH, db.SQLITE_PATH = self.original
        self.folder.cleanup()

    def login(self, username='owner'):
        result = self.client.post('/api/login', json={'username': username, 'password': 'test-password-123'})
        self.assertEqual(result.status_code, 200, result.text)
        self.client.headers['X-CSRF-Token'] = result.json()['csrf']
        return result.json()

    def post(self, url, data, status=200, **kwargs):
        result = self.client.post(url, json=data, **kwargs)
        self.assertEqual(result.status_code, status, result.text)
        return result.json()

    def get(self, url):
        result = self.client.get(url)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def product(self, quantity=10, price=10000, cost=6000, expiry=None):
        ident = self.post('/api/v1/products', {'product_name': 'Test Product '+uuid.uuid4().hex[:6], 'sku': uuid.uuid4().hex, 'price': price, 'cost_price': cost, 'unit': 'cai', 'zone_code': 'Z9'})['id']
        if quantity:
            supplier = self.post('/api/v1/suppliers', {'name': 'Test Supplier'})['id']
            self.post('/api/v1/purchases', {'supplier_id': supplier, 'paid': 0, 'items': [{'product_id': ident, 'quantity': quantity, 'cost_price': cost, 'lot_code': 'TEST', 'expires_on': expiry}]})
        return ident

    def order(self, ident, qty=1, **extra):
        return self.post('/api/v1/orders', {'items': [{'product_id': ident, 'quantity': qty}], 'payment_method': 'TRANSFER', **extra}, headers={'Idempotency-Key': uuid.uuid4().hex})

    def customer(self):
        return self.post('/api/v1/customers', {'name': 'Test Customer'})['id']

    def user(self, role, employee_id=None):
        return self.post('/api/v1/users', {'username': role, 'name': role, 'password': 'test-password-123', 'role': role, 'employee_id': employee_id})['id']

    def stock(self, ident):
        with reading() as conn:
            return one(conn, 'SELECT stock FROM products WHERE id=?', (ident,))['stock']

    def test_migration_preserves_opening_stock_and_is_idempotent(self):
        with reading() as conn:
            before = rows(conn, 'SELECT * FROM products')
            for p in before:
                self.assertEqual(p['stock'], one(conn, 'SELECT SUM(remaining) AS n FROM stock_batches WHERE product_id=?', (p['id'],))['n'])
        migrate()
        with reading() as conn:
            self.assertEqual(before, rows(conn, 'SELECT * FROM products'))
            self.assertEqual([], rows(conn, 'PRAGMA foreign_key_check'))

    def test_setup_locked_and_unauthenticated_routes_protected(self):
        self.post('/api/setup', {'username': 'newowner', 'name': 'New', 'password': 'test-password-123'}, 409)
        self.client.cookies.clear()
        for url in ['/api/v1/orders', '/api/v1/products', '/api/v1/hr', '/api/v1/backups', '/api/search_inventory', '/get_merchant_orders.php']:
            self.assertEqual(self.client.get(url).status_code, 401, url)
        self.assertIn('/login', str(self.client.get('/orders.php?action=delete&id=1').url))

    def test_csrf_and_cross_origin_rejected(self):
        self.post('/api/v1/customers', {'name': 'Invalid'}, 403, headers={'X-CSRF-Token': ''})
        self.post('/api/v1/customers', {'name': 'Invalid'}, 403, headers={'Origin': 'https://attacker.invalid'})

    def test_role_restrictions_and_last_owner(self):
        self.user('cashier')
        self.login('cashier')
        for url in ['/api/v1/users', '/api/v1/reports', '/api/v1/backups', '/api/v1/inventory', '/api/v1/audit']:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.post('/api/v1/hr/employees', {'name': 'No permission'}, 403)
        self.assertEqual(self.get('/api/v1/hr')['employees'], [])
        self.assertNotIn('cost_price', self.get('/api/v1/products')[0])
        self.login()
        result = self.client.patch('/api/v1/users/1', json={'active': False})
        self.assertEqual(result.status_code, 400)

    def test_price_validation_totals_stock_and_idempotency(self):
        p = self.product()
        payload = {'items': [{'product_id': p, 'quantity': 2, 'price': 1}], 'total_amount': 1, 'payment_method': 'TRANSFER'}
        key = uuid.uuid4().hex
        a = self.post('/api/v1/orders', payload, headers={'Idempotency-Key': key})
        b = self.post('/api/v1/orders', payload, headers={'Idempotency-Key': key})
        self.assertEqual(a['total_amount'], 20000)
        self.assertEqual(a['order_id'], b['order_id'])
        self.assertEqual(self.stock(p), 8)
        self.post('/api/v1/orders', {**payload, 'discount': 100}, 409, headers={'Idempotency-Key': key})
        self.post('/api/v1/orders', payload, 400)

    def test_atomic_rollback_on_insufficient_stock(self):
        first, second = self.product(), self.product(quantity=1)
        with reading() as conn:
            count = one(conn, 'SELECT COUNT(*) AS n FROM orders')['n']
        self.post('/api/v1/orders', {'items': [{'product_id': first, 'quantity': 1}, {'product_id': second, 'quantity': 2}], 'payment_method': 'TRANSFER'}, 409, headers={'Idempotency-Key': uuid.uuid4().hex})
        self.assertEqual(self.stock(first), 10)
        with reading() as conn:
            self.assertEqual(count, one(conn, 'SELECT COUNT(*) AS n FROM orders')['n'])

    def test_concurrent_sales_do_not_oversell(self):
        p = self.product(quantity=1)
        def buy(_):
            return self.client.post('/api/v1/orders', json={'items': [{'product_id': p, 'quantity': 1}], 'payment_method': 'TRANSFER'}, headers={'Idempotency-Key': uuid.uuid4().hex}).status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(buy, range(4)))
        self.assertEqual(sorted(results), [200, 409, 409, 409])
        self.assertEqual(self.stock(p), 0)

    def test_fefo_and_expired_stock_not_sold(self):
        p = self.product(quantity=2)
        supplier = self.post('/api/v1/suppliers', {'name': 'Supplier'})['id']
        expiry = (date.today() + timedelta(days=2)).isoformat()
        self.post('/api/v1/purchases', {'supplier_id': supplier, 'paid': 0, 'items': [{'product_id': p, 'quantity': 2, 'cost_price': 5000, 'expires_on': expiry}]})
        order = self.order(p)
        with transaction() as conn:
            allocated = one(conn, 'SELECT b.* FROM order_allocations a JOIN stock_batches b ON a.batch_id=b.id JOIN order_items i ON i.id=a.order_item_id WHERE i.order_id=?', (order['order_id'],))
            self.assertEqual(allocated['expires_on'], expiry)
            conn.execute('UPDATE stock_batches SET expires_on=? WHERE product_id=?', ((date.today()-timedelta(days=1)).isoformat(), p))
        self.post('/api/v1/orders', {'items': [{'product_id': p, 'quantity': 1}], 'payment_method': 'TRANSFER'}, 409, headers={'Idempotency-Key': uuid.uuid4().hex})

    def test_returns_refund_discount_and_cannot_repeat(self):
        p = self.product(quantity=3)
        order = self.order(p, qty=3, discount=1000)
        detail = self.get('/api/v1/orders/'+str(order['order_id']))
        item_id = detail['items'][0]['id']
        amounts = []
        for _ in range(3):
            result = self.post(f"/api/v1/orders/{order['order_id']}/returns", {'reason': 'Test return', 'method': 'TRANSFER', 'items': [{'item_id': item_id, 'quantity': 1, 'restock': True}]})
            amounts.append(result['refund'])
        self.assertEqual(sum(amounts), 29000)
        self.assertEqual(self.stock(p), 3)
        self.post(f"/api/v1/orders/{order['order_id']}/returns", {'reason': 'Again', 'items': [{'item_id': item_id, 'quantity': 1}]}, 409)

    def test_damaged_return_does_not_restock(self):
        p = self.product()
        order = self.order(p)
        item = self.get('/api/v1/orders/'+str(order['order_id']))['items'][0]
        self.post(f"/api/v1/orders/{order['order_id']}/returns", {'reason': 'Damaged', 'method': 'TRANSFER', 'items': [{'item_id': item['id'], 'quantity': 1, 'restock': False}]})
        self.assertEqual(self.stock(p), 9)

    def test_delivery_pick_assign_and_shipper_scope(self):
        p = self.product()
        shipper = self.user('shipper')
        order = self.order(p, fulfillment='DELIVERY', apartment='A-101')
        ident = order['order_id']
        self.post(f'/api/v1/orders/{ident}/status', {'status': 'COMPLETED'}, 409)
        self.post(f'/api/v1/orders/{ident}/status', {'status': 'PROCESSING'})
        self.post(f'/api/v1/orders/{ident}/status', {'status': 'SHIPPING'}, 400)
        self.post(f'/api/v1/orders/{ident}/assign', {'user_id': shipper})
        self.post(f'/api/v1/orders/{ident}/status', {'status': 'SHIPPING'}, 400)
        detail = self.get(f'/api/v1/orders/{ident}')
        self.post('/api/v1/order-items/'+str(detail['items'][0]['id'])+'/pick', {'picked': True})
        self.post(f'/api/v1/orders/{ident}/status', {'status': 'SHIPPING'})
        self.login('shipper')
        self.assertEqual([o['id'] for o in self.get('/api/v1/orders')], [ident])
        self.assertEqual(self.client.get('/api/v1/orders/1').status_code, 403)
        self.post(f'/api/v1/orders/{ident}/status', {'status': 'COMPLETED'})

    def test_cancel_restocks_and_reverses_payment(self):
        p = self.product()
        order = self.order(p, fulfillment='DELIVERY', apartment='A-101')
        result = self.post(f"/api/v1/orders/{order['order_id']}/status", {'status': 'CANCELLED', 'reason': 'Changed mind', 'method': 'TRANSFER'})
        self.assertEqual(result['refund'], 10000)
        self.assertEqual(self.stock(p), 10)

    def test_cash_shift_and_refund_accounting(self):
        p = self.product()
        self.post('/api/v1/orders', {'items':[{'product_id':p,'quantity':1}],'payment_method':'CASH'},409,headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(self.stock(p),10)
        shift=self.post('/api/v1/cash-shifts',{'opening_cash':100000})['id']
        order=self.order(p,payment_method='CASH',cash_tendered=20000)
        self.assertEqual(order['change'],10000)
        self.order(p,payment_method='TRANSFER')
        summary=next(s for s in self.get('/api/v1/cash-shifts') if s['id']==shift)
        self.assertEqual(summary['transfer_net'],10000)
        self.assertEqual(summary['net_sales'],20000)
        self.post('/api/v1/cash-shifts',{'opening_cash':0},409)
        self.post(f'/api/v1/cash-shifts/{shift}/close',{'counted_cash':100000},400)
        result=self.post(f'/api/v1/cash-shifts/{shift}/close',{'counted_cash':110000})
        self.assertEqual(result['difference'],0)

    def test_customer_debt_and_loyalty_reversed(self):
        p,c=self.product(),self.customer()
        order=self.order(p,qty=2,customer_id=c,payment_method='DEBT')
        customer=next(cu for cu in self.get('/api/v1/customers') if cu['id']==c)
        self.assertEqual((customer['debt'],customer['points']),(20000,2))
        self.post(f'/api/v1/accounts/CUSTOMER/{c}/settle',{'amount':5000,'method':'TRANSFER'})
        item=self.get(f"/api/v1/orders/{order['order_id']}")['items'][0]
        self.post(f"/api/v1/orders/{order['order_id']}/returns",{'reason':'Return','method':'TRANSFER','items':[{'item_id':item['id'],'quantity':2,'restock':True}]})
        customer=next(cu for cu in self.get('/api/v1/customers') if cu['id']==c)
        self.assertEqual((customer['debt'],customer['points']),(0,0))

    def test_supplier_debt_and_inventory_count(self):
        p=self.product(quantity=0)
        supplier=self.post('/api/v1/suppliers',{'name':'Supplier'})['id']
        self.post('/api/v1/purchases',{'supplier_id':supplier,'paid':1000,'method':'TRANSFER','items':[{'product_id':p,'quantity':2,'cost_price':6000}]})
        self.assertEqual(self.get('/api/v1/suppliers')[0]['debt'],11000)
        self.post(f'/api/v1/accounts/SUPPLIER/{supplier}/settle',{'amount':11000,'method':'TRANSFER'})
        self.post('/api/v1/stock-counts',{'product_id':p,'counted':1,'note':'Counted physically'})
        self.assertEqual(self.stock(p),1)
        with reading() as conn:
            self.assertEqual(one(conn,'SELECT SUM(remaining) AS n FROM stock_batches WHERE product_id=?',(p,))['n'],1)

    def test_role_login_pages_and_redirects(self):
        for role in ['cashier','inventory','shipper']:
            self.user(role)
        for role in ['owner','cashier','inventory','shipper']:
            page=self.client.get('/login/'+role)
            self.assertEqual(page.status_code,200)
            self.assertIn('name="role" value="'+role+'"',page.text)
            result=self.post('/api/login',{'username':role,'password':'test-password-123','role':role})
            self.client.headers['X-CSRF-Token']=result['csrf']
            self.assertEqual(result['redirect_url'],'/'+role)
            root=self.client.get('/',follow_redirects=False)
            self.assertEqual(root.headers['location'],'/'+role)
            home=self.client.get('/'+role)
            self.assertIn('data-page="'+role+'_portal"',home.text)
            self.assertIn('class="logout-button">Đăng xuất</button>',home.text)
            if role!='owner':
                self.assertEqual(self.client.get('/owner',follow_redirects=False).headers['location'],'/'+role)
        self.login()
        for path in ['/owner','/cashier','/inventory','/shipper','/settings','/reports']:
            self.assertEqual(self.client.get(path,follow_redirects=False).status_code,200)

    def test_wrong_portal_cannot_grant_role_or_session(self):
        self.user('cashier')
        self.client.cookies.clear()
        with reading() as conn:
            before=one(conn,'SELECT COUNT(*) AS n FROM sessions')['n']
        self.post('/api/login',{'username':'cashier','password':'test-password-123','role':'owner'},403)
        self.assertEqual(self.client.get('/api/session').status_code,401)
        with reading() as conn:
            self.assertEqual(before,one(conn,'SELECT COUNT(*) AS n FROM sessions')['n'])
        self.post('/api/login',{'username':'cashier','password':'test-password-123','role':'admin'},400)
        self.post('/api/login',{'username':'cashier','password':'test-password-123','role':['owner']},400)
        self.assertEqual(self.client.get('/login/admin').status_code,404)

    def test_logout_revokes_cookie_and_bearer(self):
        token=self.login()['token']
        self.post('/api/logout',{})
        self.assertNotIn('taphoa_session',self.client.cookies)
        self.assertEqual(self.client.get('/api/session').status_code,401)
        self.assertEqual(self.client.get('/api/session',headers={'Authorization':'Bearer '+token}).status_code,401)

    def test_integer_quantities_required_in_every_stock_entry(self):
        p=self.product()
        supplier=self.get('/api/v1/suppliers')[0]['id']
        batch=next(b for b in self.get('/api/v1/inventory')['batches'] if b['product_id']==p)
        for fraction in [.001,1.008,1.5]:
            self.post('/api/v1/orders',{'items':[{'product_id':p,'quantity':fraction}],'payment_method':'TRANSFER'},400,headers={'Idempotency-Key':uuid.uuid4().hex})
            self.post('/api/v1/purchases',{'supplier_id':supplier,'items':[{'product_id':p,'quantity':fraction,'cost_price':100}]},400)
            self.post('/api/v1/stock-counts',{'product_id':p,'counted':fraction,'note':'Invalid'},400)
            self.post(f"/api/v1/batches/{batch['id']}/dispose",{'quantity':fraction,'note':'Invalid'},400)
        order=self.order(p,qty=2)
        item=self.get(f"/api/v1/orders/{order['order_id']}")['items'][0]
        self.post(f"/api/v1/orders/{order['order_id']}/returns",{'reason':'Invalid fractional return','method':'TRANSFER','items':[{'item_id':item['id'],'quantity':1.5}]},400)
        self.assertEqual(self.stock(p),8)

    def test_legacy_fractional_stock_is_preserved_but_not_offered_for_sale(self):
        p=self.product(quantity=2)
        with transaction() as conn:
            conn.execute('UPDATE stock_batches SET remaining=2.008 WHERE product_id=?',(p,))
            conn.execute('UPDATE products SET stock=2.008 WHERE id=?',(p,))
        product=next(row for row in self.get('/api/v1/products') if row['id']==p)
        self.assertEqual(product['sellable_stock'],2)
        self.assertEqual(product['stock'],2.008)
        self.order(p,qty=2)
        self.assertEqual(self.stock(p),.008)
        self.post('/api/v1/stock-counts',{'product_id':p,'counted':0,'note':'Recount old fractional residue'})
        self.assertEqual(self.stock(p),0)

    def test_dispose_batch_and_apply_real_promotion(self):
        p=self.product(quantity=5,expiry=(date.today()+timedelta(days=2)).isoformat())
        suggestion=next(s for s in self.get('/api/v1/suggestions') if s['product_id']==p and s['type']=='EXPIRING')
        self.post('/api/v1/suggestions/apply',{'key':suggestion['key']})
        self.assertEqual(self.order(p)['total_amount'],8000)
        batch=next(b for b in self.get('/api/v1/inventory')['batches'] if b['product_id']==p)
        self.post(f"/api/v1/batches/{batch['id']}/dispose",{'quantity':1,'note':'Broken'})
        self.assertEqual(self.stock(p),3)

    def test_reports_profit_uses_batch_cost(self):
        p=self.product()
        before=self.get('/api/v1/reports')
        self.order(p,qty=2)
        after=self.get('/api/v1/reports')
        self.assertEqual(after['net_revenue']-before['net_revenue'],20000)
        self.assertEqual(after['gross_profit']-before['gross_profit'],8000)

    def employee(self):
        return self.post('/api/v1/hr/employees',{'name':'Test Employee','salary_mode':'HOURLY','hourly_rate':30000})['id']

    def test_schedule_clock_and_own_attendance(self):
        emp=self.employee()
        start=datetime.now()-timedelta(hours=1)
        end=datetime.now()+timedelta(hours=1)
        shift=self.post('/api/v1/hr/shifts',{'name':'Test shift','start_time':start.strftime('%H:%M'),'end_time':end.strftime('%H:%M')})['id']
        self.post('/api/v1/hr/schedule',{'employee_id':emp,'shift_id':shift,'work_date':start.date().isoformat()})
        self.user('cashier',emp)
        self.login('cashier')
        self.post('/api/v1/hr/clock',{'action':'IN'})
        self.post('/api/v1/hr/clock',{'action':'IN'},409)
        self.post('/api/v1/hr/clock',{'action':'OUT'})
        self.post('/api/v1/hr/clock',{'action':'OUT'},409)
        data=self.get('/api/v1/hr')
        self.assertEqual([e['id'] for e in data['employees']],[emp])
        self.assertTrue(all(a['employee_id']==emp for a in data['attendance']))

    def test_calculate_approve_payroll_and_lock(self):
        emp=self.employee()
        work_date=(date.today()-timedelta(days=2)).isoformat()
        self.post('/api/v1/hr/attendance/correct',{'employee_id':emp,'work_date':work_date,'check_in_at':work_date+'T08:00','check_out_at':work_date+'T16:00','note':'Verified timesheet'})
        month,year=int(work_date[5:7]),int(work_date[:4])
        period={'month':month,'year':year}
        self.post('/api/v1/hr/payroll/calculate',{**period,'adjustments':{str(emp):{'bonus':10000,'deduction':5000}}})
        payroll=self.get(f'/api/v1/hr/payroll?month={month}&year={year}')
        row=next(r for r in payroll if r['employee_id']==emp)
        self.assertEqual(row['total'],245000)
        self.post('/api/v1/hr/payroll/approve',period)
        self.post('/api/v1/hr/payroll/calculate',period,409)
        self.post('/api/v1/hr/attendance/correct',{'employee_id':emp,'work_date':work_date,'check_in_at':work_date+'T08:00','check_out_at':work_date+'T15:00','note':'Cannot change'},409)

    def test_leave_and_swap_requests_modify_schedule(self):
        a,b=self.employee(),self.employee()
        work_date=(date.today()+timedelta(days=5)).isoformat()
        for emp,shift in [(a,1),(b,2)]:
            self.post('/api/v1/hr/schedule',{'employee_id':emp,'shift_id':shift,'work_date':work_date})
        req=self.post('/api/v1/hr/requests',{'employee_id':a,'kind':'SWAP','target_employee_id':b,'work_date':work_date,'reason':'Swap agreed'})['id']
        self.post(f'/api/v1/hr/requests/{req}/review',{'status':'APPROVED'})
        with reading() as conn:
            self.assertEqual(one(conn,'SELECT shift_id FROM shift_schedule WHERE employee_id=? AND work_date=?',(a,work_date))['shift_id'],2)
        req=self.post('/api/v1/hr/requests',{'employee_id':a,'kind':'LEAVE','work_date':work_date,'reason':'Personal leave'})['id']
        self.post(f'/api/v1/hr/requests/{req}/review',{'status':'APPROVED'})
        with reading() as conn:
            self.assertIsNone(one(conn,'SELECT id FROM shift_schedule WHERE employee_id=? AND work_date=?',(a,work_date)))

    def test_backup_restore_restores_data_and_revokes_sessions(self):
        backup=self.post('/api/v1/backups',{})['name']
        created=self.customer()
        self.post(f'/api/v1/backups/{backup}/restore',{'confirmation':'wrong'},400)
        result=self.post(f'/api/v1/backups/{backup}/restore',{'confirmation':'KHOI PHUC'})
        self.assertTrue(result['safety_backup'])
        self.assertEqual(self.client.get('/api/session').status_code,401)
        self.login()
        self.assertFalse(any(c['id']==created for c in self.get('/api/v1/customers')))

    def test_password_change_revokes_old_login(self):
        self.post('/api/password',{'current_password':'wrong','password':'new-password-456'},403)
        self.post('/api/password',{'current_password':'test-password-123','password':'new-password-456'})
        self.assertEqual(self.client.get('/api/session').status_code,401)
        self.post('/api/login',{'username':'owner','password':'test-password-123'},401)
        self.post('/api/login',{'username':'owner','password':'new-password-456'})

    def test_legacy_get_delete_does_not_mutate_and_receipt_escapes(self):
        p=self.product()
        order=self.order(p,customer_note='<script>alert(1)</script>')
        self.assertEqual(self.client.get(f"/orders.php?action=delete&id={order['order_id']}").status_code,200)
        self.get(f"/api/v1/orders/{order['order_id']}")
        receipt=self.client.get(f"/receipt/{order['order_id']}")
        self.assertEqual(receipt.status_code,200)
        self.assertIn('&lt;script&gt;',receipt.text)
        self.assertNotIn('<script>alert(1)</script>',receipt.text)

    def test_bad_numbers_and_excess_payment_rejected(self):
        p=self.product()
        for value in [-1,0,'NaN','Infinity',.0001]:
            self.post('/api/v1/orders',{'items':[{'product_id':p,'quantity':value}],'payment_method':'TRANSFER'},400,headers={'Idempotency-Key':uuid.uuid4().hex})
        self.post('/api/v1/orders',{'items':[{'product_id':p,'quantity':1}],'payments':[{'method':'TRANSFER','amount':1}]},400,headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(self.stock(p),10)

    def test_nested_invalid_payloads_are_rejected(self):
        p=self.product()
        supplier=self.get('/api/v1/suppliers')[0]['id']
        self.post('/api/v1/purchases',{'supplier_id':supplier,'items':['invalid']},400)
        self.post('/api/v1/orders',{'items':[{'product_id':p,'quantity':1}],'payments':['invalid']},400,headers={'Idempotency-Key':uuid.uuid4().hex})
        order=self.order(p)
        self.post(f"/api/v1/orders/{order['order_id']}/returns",{'reason':'Bad request','items':['invalid']},400)

    def test_batch_cost_can_be_corrected_only_before_sale(self):
        p=self.product()
        batch=next(b for b in self.get('/api/v1/inventory')['batches'] if b['product_id']==p)
        url=f"/api/v1/batches/{batch['id']}"
        response=self.client.patch(url,json={'cost_price':7000,'lot_code':'EDITED','note':'Invoice correction'})
        self.assertEqual(response.status_code,200,response.text)
        self.order(p)
        response=self.client.patch(url,json={'cost_price':8000,'lot_code':'EDITED','note':'Cannot rewrite history'})
        self.assertEqual(response.status_code,409)

    def test_sample_payroll_must_be_recalculated(self):
        self.post('/api/v1/hr/payroll/approve',{'month':date.today().month,'year':date.today().year},400)

    def test_overnight_schedule_cannot_overlap(self):
        emp=self.employee()
        tomorrow=date.today()+timedelta(days=1)
        overnight=self.post('/api/v1/hr/shifts',{'name':'Night','start_time':'22:00','end_time':'08:00'})['id']
        morning=self.post('/api/v1/hr/shifts',{'name':'Early','start_time':'07:00','end_time':'12:00'})['id']
        self.post('/api/v1/hr/schedule',{'employee_id':emp,'shift_id':overnight,'work_date':tomorrow.isoformat()})
        self.post('/api/v1/hr/schedule',{'employee_id':emp,'shift_id':morning,'work_date':(tomorrow+timedelta(days=1)).isoformat()},409)

    def test_bearer_auth_and_legacy_routes(self):
        token=self.login()['token']
        self.client.cookies.clear()
        self.client.headers.pop('X-CSRF-Token')
        self.client.headers['Authorization']='Bearer '+token
        self.post('/api/v1/customers',{'name':'Mobile customer'})
        for endpoint in ['/api/hr/employees','/api/hr/attendance','/api/hr/schedule','/api/hr/stats','/api/hr/payroll','/search_inventory.php','/get_merchant_orders.php']:
            self.get(endpoint)

    def test_restore_rejects_incomplete_schema(self):
        name='incomplete.db'
        path=Path(config.SQLITE_PATH).parent/'backups'/name
        connection=sqlite3.connect(path)
        try:
            connection.executescript("CREATE TABLE schema_migrations(version INTEGER); INSERT INTO schema_migrations VALUES (3); CREATE TABLE users(id INTEGER,role TEXT,active INTEGER); INSERT INTO users VALUES (1,'owner',1);")
        finally:
            connection.close()
        self.post(f'/api/v1/backups/{name}/restore',{'confirmation':'KHOI PHUC'},400)
        self.assertEqual(len(self.get('/api/v1/products')),6)

    def registration(self, role='cashier', username=None, **extra):
        return self.post('/api/register', {'username':username or 'new_'+role, 'name':'New '+role,
            'role':role, 'phone':'0901234567', 'password':'registration-test-123',
            'confirm_password':'registration-test-123', **extra}, 201)

    def test_registration_pages_and_login_links_for_every_role(self):
        selector=self.client.get('/register')
        self.assertEqual(selector.status_code,200)
        for role in ['owner','cashier','inventory','shipper']:
            self.assertIn('/register/'+role,selector.text)
            page=self.client.get('/register/'+role)
            self.assertIn('name="role" value="'+role+'"',page.text)
            self.assertIn('name="confirm_password"',page.text)
            self.assertIn('/register/'+role,self.client.get('/login/'+role).text)
        self.assertEqual(self.client.get('/register/invalid').status_code,404)

    def test_registration_approval_all_roles_and_password_privacy(self):
        for role in ['owner','cashier','inventory','shipper']:
            registration=self.registration(role)
            self.assertEqual(registration['status'],'PENDING')
            self.post('/api/login',{'username':'new_'+role,'password':'registration-test-123','role':role},403)
            requests=self.get('/api/v1/registrations')
            item=next(r for r in requests if r['id']==registration['registration_id'])
            self.assertNotIn('password_hash',item)
            self.assertNotIn('password',item)
            result=self.post('/api/v1/registrations/'+str(item['id'])+'/review',{'status':'APPROVED','active':False,'role':'owner'})
            with reading() as conn:
                account=one(conn,'SELECT * FROM users WHERE id=?',(result['user_id'],))
                self.assertEqual(account['role'],role)
                self.assertEqual(account['active'],1)
                self.assertIsNotNone(account['employee_id'])
                self.assertNotEqual(account['password_hash'],'registration-test-123')
                self.assertEqual(one(conn,'SELECT password_hash FROM registrations WHERE id=?',(item['id'],))['password_hash'],'')
            login=self.post('/api/login',{'username':'new_'+role,'password':'registration-test-123','role':role})
            self.assertEqual(login['redirect_url'],'/'+role)
            self.login()
            self.post('/api/v1/registrations/'+str(item['id'])+'/review',{'status':'APPROVED'},409)

    def test_registration_cannot_self_activate_or_review(self):
        self.user('cashier')
        result=self.registration('owner',active=1,employee_id=1,status='APPROVED')
        with reading() as conn:
            self.assertIsNone(one(conn,"SELECT id FROM users WHERE username='new_owner'"))
        self.login('cashier')
        self.assertEqual(self.client.get('/api/v1/registrations').status_code,403)
        self.post(f"/api/v1/registrations/{result['registration_id']}/review",{'status':'APPROVED'},403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/v1/registrations').status_code,401)
        self.post(f"/api/v1/registrations/{result['registration_id']}/review",{'status':'APPROVED'},401)

    def test_registration_duplicate_validation_rejection_and_retry(self):
        data={'username':'duplicate','name':'Employee','role':'cashier','password':'registration-test-123','confirm_password':'wrong'}
        self.post('/api/register',data,400)
        self.post('/api/register',{**data,'confirm_password':data['password'],'role':['owner']},400)
        self.post('/api/register',{**data,'confirm_password':data['password'],'phone':'invalid'},400)
        reg=self.registration(username='duplicate')
        self.post('/api/register',{**data,'confirm_password':data['password'],'username':'DUPLICATE'},409)
        self.post('/api/register',{**data,'confirm_password':data['password'],'username':'owner'},409)
        self.post('/api/v1/users',{'username':'duplicate','name':'Other','role':'cashier','password':'test-password-123'},409)
        path=f"/api/v1/registrations/{reg['registration_id']}/review"
        self.post(path,{'status':'REJECTED'},400)
        self.post(path,{'status':'REJECTED','note':'Chưa xác nhận nhân viên'})
        self.post('/api/login',{'username':'duplicate','password':'registration-test-123'},401)
        self.assertEqual(self.registration(username='duplicate')['status'],'PENDING')

    def test_registration_link_existing_employee_without_creating_another(self):
        registration=self.registration()
        with reading() as conn:
            count=one(conn,'SELECT COUNT(*) AS n FROM employees')['n']
        result=self.post(f"/api/v1/registrations/{registration['registration_id']}/review",{'status':'APPROVED','employee_id':2})
        with reading() as conn:
            self.assertEqual(one(conn,'SELECT COUNT(*) AS n FROM employees')['n'],count)
            self.assertEqual(one(conn,'SELECT employee_id FROM users WHERE id=?',(result['user_id'],))['employee_id'],2)
        other=self.registration('inventory')
        self.post(f"/api/v1/registrations/{other['registration_id']}/review",{'status':'APPROVED','employee_id':2},409)

    def test_registration_requires_setup_and_same_origin(self):
        data={'username':'signup','name':'Employee','role':'cashier','password':'registration-test-123','confirm_password':'registration-test-123'}
        self.post('/api/register',data,403,headers={'Origin':'https://another.invalid'})
        with transaction() as conn:
            conn.execute('DELETE FROM sessions')
            conn.execute('DELETE FROM audit_log')
            conn.execute('DELETE FROM users')
        self.post('/api/register',data,409)
        self.assertEqual(self.client.get('/register/cashier',follow_redirects=False).headers['location'],'/setup')
        self.post('/api/setup',{'username':'owner','name':'Owner','password':'test-password-123'})

    def test_registration_throttle_and_review_csrf(self):
        for index in range(10):
            self.registration(username='signup'+str(index))
        self.post('/api/register',{'username':'blocked','name':'Blocked','role':'cashier','password':'registration-test-123','confirm_password':'registration-test-123'},429)
        ident=self.get('/api/v1/registrations')[0]['id']
        self.post(f'/api/v1/registrations/{ident}/review',{'status':'APPROVED'},403,headers={'X-CSRF-Token':''})

    def test_registration_migration_preserves_v3_data(self):
        product=self.product()
        self.order(product)
        with transaction() as conn:
            before={table:rows(conn,'SELECT * FROM '+table) for table in ['users','employees','orders','order_items','products','stock_batches','stock_movements']}
            conn.execute('DROP TABLE registrations')
            conn.execute('DELETE FROM schema_migrations WHERE version=4')
        migrate()
        migrate()
        with reading() as conn:
            for table,expected in before.items():
                self.assertEqual(expected,rows(conn,'SELECT * FROM '+table),table)
            self.assertEqual(one(conn,'SELECT MAX(version) AS n FROM schema_migrations')['n'],4)
            self.assertEqual(rows(conn,'SELECT * FROM registrations'),[])


    def test_malformed_scalar_fields_are_rejected_without_server_errors(self):
        product = self.product()
        for extra in ({'payment_method': []}, {'fulfillment': {}}, {'customer_id': [1]},
                      {'payments': [{'method': [], 'amount': 10000}]}):
            self.post('/api/v1/orders', {'items': [{'product_id': product, 'quantity': 1}], **extra},
                      status=400, headers={'Idempotency-Key': uuid.uuid4().hex})
        self.post('/api/v1/products', {'product_name': 'Bad', 'sku': 'BAD', 'active': 'false'}, status=400)
        self.assertEqual(self.stock(product), 10)

    def test_large_sale_and_purchase_totals_are_rejected_atomically(self):
        product = self.product(quantity=0, price=1_000_000_000_000)
        self.post('/api/v1/orders', {'items': [{'product_id': product, 'quantity': 1000000000000}],
                  'payment_method': 'TRANSFER'}, status=400, headers={'Idempotency-Key': uuid.uuid4().hex})
        supplier = self.post('/api/v1/suppliers', {'name': 'Supplier'})['id']
        self.post('/api/v1/purchases', {'supplier_id': supplier, 'items': [
            {'product_id': product, 'quantity': 1000000000000, 'cost_price': 1000000000000}]}, status=400)
        self.assertEqual(self.stock(product), 0)

    def test_employee_cannot_be_linked_to_two_accounts(self):
        employee = self.get('/api/v1/hr')['employees'][0]['id']
        self.user('cashier', employee)
        self.post('/api/v1/users', {'username': 'duplicate', 'name': 'Duplicate',
                  'password': 'test-password-123', 'role': 'inventory', 'employee_id': employee}, status=409)
        other = self.user('inventory')
        response = self.client.patch('/api/v1/users/' + str(other), json={'employee_id': employee})
        self.assertEqual(response.status_code, 409)

    def test_health_security_headers_and_body_limit(self):
        self.assertEqual(self.get('/health/ready'), {'status': 'ok'})
        response = self.client.get('/owner')
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        response = self.client.post('/api/login', content=b'x' * (config.MAX_REQUEST_BYTES + 1))
        self.assertEqual(response.status_code, 413)
        response = self.client.post('/api/login', content=iter([b'x' * 600000, b'y' * 600000]))
        self.assertEqual(response.status_code, 413)

if __name__ == '__main__':
    unittest.main()

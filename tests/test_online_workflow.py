"""Payment-first QR does not trust customer claims or double count stock/cash."""
import unittest,uuid
from concurrent.futures import ThreadPoolExecutor
from retail.database import reading,transaction,one,rows


class OnlineWorkflowTests(unittest.TestCase):
    def setUp(self):
        from test_commerce import CommerceTests
        self.e=CommerceTests('test_vietqr_payload_round_trip_and_crc');self.e.setUp()
        self.e.post('/api/v1/shop/settings',{'store_name':'Test','bank_bin':'970422','bank_account':'1234567890','bank_name':'MB Bank'})

    def tearDown(self):self.e.tearDown()

    def order(self,**extra):return self.e.place(self.e.payload(payment_method='QR',**extra))
    def report(self,order,status=200):return self.e.post('/api/shop/orders/'+str(order['id'])+'/report-payment',{},status,client=self.e.client)
    def approve(self,order,reference=None,status=200):return self.e.action(order,'paid',{'amount':72000,'reference':reference or uuid.uuid4().hex},status)

    def staff_login(self,name):
        response=self.e.post('/api/login',{'username':name,'password':'commerce-password-123'})
        self.e.staff.headers['X-CSRF-Token']=response['csrf']

    def test_qr_is_immediate_and_reserves_stock_but_does_not_book_income(self):
        order=self.order();path='/api/shop/orders/'+str(order['id'])
        detail=self.e.client.get(path).json()
        self.assertEqual(detail['status'],'PENDING');self.assertEqual(detail['payment_status'],'UNPAID')
        self.assertEqual(detail['paid'],0);self.assertIsNone(detail['invoice'])
        self.assertEqual(detail['bank']['amount'],72000)
        self.assertEqual(self.e.client.get(path+'/qr?format=png').status_code,200)
        with reading() as conn:
            self.assertEqual(one(conn,'SELECT stock FROM products WHERE id=?',(self.e.p,))['stock'],8)
            self.assertEqual(one(conn,'SELECT COUNT(*) n FROM payments')['n'],0)
        self.e.action(order,'confirm',status=409)

    def test_reporting_is_idempotent_and_not_proof_of_money_received(self):
        order=self.order();self.report(order);self.assertTrue(self.report(order)['replayed'])
        with transaction() as conn:conn.execute("UPDATE online_orders SET expires_at='2000-01-01T00:00:00' WHERE id=?",(order['id'],))
        detail=self.e.client.get('/api/shop/orders/'+str(order['id'])).json()
        self.assertEqual(detail['status'],'PAYMENT_REVIEW');self.assertEqual(detail['paid'],0)
        self.assertEqual(detail['payment_status'],'REPORTED')
        self.assertEqual(self.e.client.get('/api/shop/orders/'+str(order['id'])+'/qr').status_code,409)
        with reading() as conn:self.assertEqual(one(conn,'SELECT COUNT(*) n FROM payments')['n'],0)
        self.e.register('0900000001');self.report(order,404)

    def test_verified_approval_issues_one_invoice_and_does_not_reduce_stock_twice(self):
        order=self.order();self.approve(order,status=409);self.report(order)
        reference='UNIQUE-TRANSACTION';self.approve(order,reference);again=self.approve(order,reference)
        self.assertTrue(again['replayed'])
        with reading() as conn:
            self.assertEqual(one(conn,'SELECT stock FROM products WHERE id=?',(self.e.p,))['stock'],8)
            self.assertEqual(one(conn,'SELECT COUNT(*) n FROM online_invoices')['n'],1)
            self.assertEqual(one(conn,"SELECT SUM(amount) n FROM payments WHERE kind='ONLINE_PREPAY'")['n'],72000)
        invoice=self.e.client.get('/shop/orders/'+str(order['id'])+'/invoice')
        self.assertEqual(invoice.status_code,200);self.assertIn('HD-WEB-',invoice.text);self.assertIn('Sữa tươi',invoice.text)
        second=self.order();self.report(second);self.approve(second,reference,409)
        ledger=self.e.staff.get('/api/v1/shop/finance').json();self.assertEqual(ledger['totals']['income'],72000)

    def test_expiry_releases_unpaid_hold_and_late_payment_goes_to_refund_queue(self):
        order=self.order()
        with transaction() as conn:conn.execute("UPDATE online_orders SET expires_at='2000-01-01T00:00:00' WHERE id=?",(order['id'],))
        self.e.client.get('/api/shop/orders')
        with reading() as conn:self.assertEqual(one(conn,'SELECT stock FROM products WHERE id=?',(self.e.p,))['stock'],10)
        self.report(order);self.approve(order)
        detail=self.e.client.get('/api/shop/orders/'+str(order['id'])).json()
        self.assertEqual(detail['status'],'EXPIRED');self.assertEqual(detail['refund_due'],72000);self.assertIsNone(detail['invoice'])
        self.e.action(order,'refund',{'amount':72000,'reference':'REFUND-LATE','method':'TRANSFER'})
        self.assertEqual(self.e.staff.get('/api/v1/shop/finance').json()['totals']['net'],0)

    def test_prepare_dispatch_partial_delivery_and_refund_follow_verified_payment(self):
        order=self.order();self.report(order);self.approve(order)
        shipper=self.e.post('/api/v1/users',{'username':'driver','name':'Driver','role':'shipper','password':'commerce-password-123'})['id']
        self.e.action(order,'ship',{'shipper_id':shipper},409)
        detail=self.e.client.get('/api/shop/orders/'+str(order['id'])).json()
        self.e.action(order,'prepare',{'items':[{'item_id':i['id'],'picked':True} for i in detail['items']]})
        self.e.action(order,'ship',{'shipper_id':shipper})
        delivered=self.e.action(order,'deliver',self.e.inspect(order,accepted=1))
        self.assertEqual(delivered['refund_due'],20000)
        self.e.action(order,'refund',{'amount':20000,'reference':'REFUND-PARTIAL','method':'TRANSFER'})
        ledger=self.e.staff.get('/api/v1/shop/finance').json()
        self.assertEqual(ledger['totals']['income'],72000);self.assertEqual(ledger['totals']['expense'],20000);self.assertEqual(ledger['totals']['net'],52000)
        self.assertIn('Kết quả kiểm hàng khi nhận',self.e.client.get('/shop/orders/'+str(order['id'])+'/invoice').text)

    def test_assigned_cashier_and_dispatcher_have_separate_permissions(self):
        people={}
        for name,role in [('money','cashier'),('other','cashier'),('stock','inventory')]:people[name]=self.e.post('/api/v1/users',{'username':name,'name':name,'role':role,'password':'commerce-password-123'})['id']
        self.e.post('/api/v1/shop/responsibilities',{'online_cashier_id':people['money'],'online_dispatcher_id':people['stock']})
        order=self.order();self.report(order)
        self.staff_login('stock');self.approve(order,status=403)
        self.assertEqual(self.e.staff.get('/api/v1/shop/finance').status_code,403)
        self.staff_login('other');self.approve(order,status=403)
        self.staff_login('money');self.approve(order)
        self.e.action(order,'ship',{'shipper_id':people['stock']},403)
        self.staff_login('owner');self.assertEqual(self.e.staff.get('/api/v1/shop/finance').status_code,200)

    def test_payment_holds_are_atomic_and_checkout_replay_does_not_hold_again(self):
        data=self.e.payload(payment_method='QR',items=[{'product_id':self.e.p,'quantity':8}])
        quote=self.e.post('/api/shop/quote',data,client=self.e.client)
        payload={**data,'fingerprint':quote['fingerprint']};key=uuid.uuid4().hex
        one=self.e.post('/api/shop/orders',payload,client=self.e.client,headers={'Idempotency-Key':key})
        replay=self.e.post('/api/shop/orders',payload,client=self.e.client,headers={'Idempotency-Key':key})
        self.assertEqual(one['id'],replay['id']);self.assertTrue(replay['replayed'])
        self.e.post('/api/shop/orders',payload,409,client=self.e.client,headers={'Idempotency-Key':uuid.uuid4().hex})
        with reading() as conn:self.assertEqual(rows(conn,'SELECT stock FROM products WHERE id=?',(self.e.p,))[0]['stock'],2)

    def test_expense_idempotency_and_cod_handover_do_not_double_count_income(self):
        order=self.e.place();self.e.confirm_ship(order)
        with reading() as conn:
            oid=one(conn,'SELECT shipper_id FROM online_orders WHERE id=?',(order['id'],))['shipper_id']
            driver=one(conn,'SELECT username FROM users WHERE id=?',(oid,))['username']
        self.staff_login(driver);self.e.action(order,'deliver',self.e.inspect(order))
        self.staff_login('owner')
        finance=self.e.staff.get('/api/v1/shop/finance').json();self.assertEqual(finance['collectors'][0]['outstanding'],72000)
        body={'collector_id':oid,'amount':72000,'reference':'HANDOVER-ONE'}
        self.e.post('/api/v1/shop/finance/handovers',body)
        self.assertTrue(self.e.post('/api/v1/shop/finance/handovers',body)['replayed'])
        key=uuid.uuid4().hex;expense={'amount':5000,'method':'CASH','note':'Packaging receipt TEST'}
        self.e.post('/api/v1/shop/finance/expenses',expense,headers={'Idempotency-Key':key})
        self.assertTrue(self.e.post('/api/v1/shop/finance/expenses',expense,headers={'Idempotency-Key':key})['replayed'])
        finance=self.e.staff.get('/api/v1/shop/finance').json()
        self.assertEqual(finance['totals']['income'],72000);self.assertEqual(finance['totals']['net'],67000)
        self.assertEqual(finance['collectors'][0]['outstanding'],0)


if __name__=='__main__':unittest.main()

"""Rescue plans preserve inventory and combos use checked prices and FEFO."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
from pathlib import Path
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient
import config
import db
from app import app
from retail.database import reading,transaction,rows,one,migrate,SCHEMA_VERSION


class RescueTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='taphoa-rescue-')
        self.original=config.SQLITE_PATH,db.SQLITE_PATH,config.SEED_DEMO
        config.SQLITE_PATH=db.SQLITE_PATH=str(Path(self.folder.name)/'shop.db')
        config.SEED_DEMO=False
        self.client=TestClient(app); self.client.__enter__()
        self.post('/api/setup',{'username':'owner','name':'Owner','password':'rescue-test-password'})
        self.login('owner')
        self.supplier=self.post('/api/v1/suppliers',{'name':'Supplier'})['id']
        self.anchor=self.product('Bánh mì cứu trợ',10000,6000,20,2)
        self.partner=self.product('Sữa hộp ghép',6000,3000,20,None)
        self.batch=self.batch_for(self.anchor)

    def tearDown(self):
        self.client.__exit__(None,None,None)
        config.SQLITE_PATH,db.SQLITE_PATH,config.SEED_DEMO=self.original
        self.folder.cleanup()

    def post(self,path,data,status=200,**kwargs):
        result=self.client.post(path,json=data,**kwargs)
        self.assertEqual(result.status_code,status,result.text)
        return result.json()

    def get(self,path):
        result=self.client.get(path); self.assertEqual(result.status_code,200,result.text); return result.json()

    def login(self,name):
        result=self.post('/api/login',{'username':name,'password':'rescue-test-password'})
        self.client.headers['X-CSRF-Token']=result['csrf']

    def product(self,name,price,cost,qty,expiry):
        ident=self.post('/api/v1/products',{'product_name':name,'unit':'cái','zone_code':'A1','price':price})['id']
        self.purchase(ident,cost,qty,expiry)
        return ident

    def purchase(self,p,cost,qty,expiry):
        self.post('/api/v1/purchases',{'supplier_id':self.supplier,'paid':0,'items':[
            {'product_id':p,'quantity':qty,'cost_price':cost,
             'expires_on':(date.today()+timedelta(days=expiry)).isoformat() if expiry is not None else None}]})

    def batch_for(self,p):
        with reading() as conn: return one(conn,'SELECT id FROM stock_batches WHERE product_id=? ORDER BY id DESC',(p,))['id']

    def quote(self,**extra):
        return self.post('/api/v1/rescue/quote',{'batch_id':self.batch,'partner_id':self.partner,'discount_percent':25,**extra})

    def campaign(self,**extra):
        quote=self.quote(**extra)
        return self.post('/api/v1/rescue/campaigns',{'batch_id':self.batch,'partner_id':self.partner,
            'discount_percent':25,'max_sets':quote['max_sets'],'expected_price':quote['price'],**extra})

    def order(self,campaign=None,sets=1,**extra):
        data={'items':[{'product_id':self.anchor,'quantity':sets},{'product_id':self.partner,'quantity':sets}],
              'payment_method':'TRANSFER',**extra}
        if campaign: data.update(rescue_campaign_id=campaign,rescue_sets=sets)
        return self.post('/api/v1/orders',data,headers={'Idempotency-Key':uuid.uuid4().hex})

    def snapshot(self):
        with reading() as conn:
            return {name:rows(conn,'SELECT * FROM '+name) for name in ['products','stock_batches','stock_movements',
                'orders','order_items','payments','account_entries','audit_log','rescue_campaigns']}

    def test_analysis_and_quote_are_read_only_with_honest_missing_history(self):
        before=self.snapshot()
        data=self.get('/api/v1/rescue')
        item=next(item for item in data['items'] if item['batch_id']==self.batch)
        self.assertIsNone(item['daily_sales']); self.assertIsNone(item['expected_unsold'])
        self.assertEqual(item['daily_target'],7)
        self.assertEqual(item['suggested_partner']['id'],self.partner)
        self.assertEqual(item['suggested_partner']['basis'],'category')
        quote=self.quote(max_sets=5)
        self.assertEqual((quote['price'],quote['gross_profit_if_all_sold']),(12000,15000))
        self.assertEqual(self.snapshot(),before)

    def test_quote_respects_margin_floor_and_unknown_cost(self):
        quote=self.quote(discount_percent=50,max_sets=2)
        self.assertEqual(quote['price'],10000)
        self.assertTrue(quote['margin_floor_applied'])
        self.assertGreaterEqual(quote['price']*90,9000*100)
        with transaction() as conn: conn.execute('UPDATE stock_batches SET cost_price=0 WHERE id=?',(self.batch,))
        self.post('/api/v1/rescue/quote',{'batch_id':self.batch,'partner_id':self.partner},409)

    def test_expired_lots_and_non_fefo_lots_cannot_be_discounted(self):
        self.purchase(self.anchor,6000,3,0)
        earlier=self.batch_for(self.anchor)
        self.post('/api/v1/rescue/quote',{'batch_id':self.batch,'partner_id':self.partner},409)
        self.assertEqual(self.post('/api/v1/rescue/quote',{'batch_id':earlier,'partner_id':self.partner})['max_sets'],3)
        with transaction() as conn: conn.execute('UPDATE stock_batches SET expires_on=? WHERE id=?',((date.today()-timedelta(days=1)).isoformat(),earlier))
        data=self.get('/api/v1/rescue')
        self.assertTrue(any(item['batch_id']==earlier for item in data['expired']))
        self.assertFalse(any(item['batch_id']==earlier for item in data['items']))
        self.post('/api/v1/rescue/quote',{'batch_id':earlier,'partner_id':self.partner},409)

    def test_forecast_models_earlier_lot_expiry_before_later_lot(self):
        p=self.product('Tốc độ bán',10000,6000,40,None)
        for age,qty in [(6,4),(3,4),(1,6)]:
            order=self.post('/api/v1/orders',{'items':[{'product_id':p,'quantity':qty}],'payment_method':'TRANSFER'},headers={'Idempotency-Key':uuid.uuid4().hex})
            with transaction() as conn: conn.execute('UPDATE orders SET created_at=? WHERE id=?',((date.today()-timedelta(days=age)).isoformat()+' 10:00:00',order['order_id']))
        self.purchase(p,6000,4,0); first=self.batch_for(p)
        self.purchase(p,6000,6,2); second=self.batch_for(p)
        data=self.get('/api/v1/rescue')
        a=next(item for item in data['items'] if item['batch_id']==first)
        b=next(item for item in data['items'] if item['batch_id']==second)
        self.assertEqual(a['daily_sales'],2)
        self.assertEqual(a['expected_unsold'],2)
        self.assertEqual(b['expected_unsold'],2)
        self.assertFalse(b['first_in_fefo'])

    def test_purchase_together_uses_completed_net_sales(self):
        ids=[]
        for age in [10,5,2,1]:
            order=self.order(sets=2,**({'fulfillment':'DELIVERY','apartment':'Test address'} if age==1 else {})); ids.append(order['order_id'])
            with transaction() as conn: conn.execute('UPDATE orders SET created_at=? WHERE id=?',((date.today()-timedelta(days=age)).isoformat()+' 10:00:00',order['order_id']))
        self.post(f'/api/v1/orders/{ids[-1]}/status',{'status':'CANCELLED','reason':'Test cancel','method':'TRANSFER'})
        detail=self.get(f'/api/v1/orders/{ids[0]}')
        item=next(item for item in detail['items'] if item['product_id']==self.anchor)
        self.post(f'/api/v1/orders/{ids[0]}/returns',{'reason':'One returned','method':'TRANSFER','items':[{'item_id':item['id'],'quantity':1,'restock':True}]})
        proposal=next(item for item in self.get('/api/v1/rescue')['items'] if item['batch_id']==self.batch)
        self.assertEqual(proposal['daily_sales'],round(5/11,2))
        self.assertEqual(proposal['suggested_partner']['co_orders'],3)
        self.assertEqual(proposal['suggested_partner']['basis'],'history')

    def test_campaign_sale_discounts_only_pair_and_keeps_extra_item_full_price(self):
        extra=self.product('Khác',5000,2000,5,None)
        campaign=self.campaign(max_sets=3)['id']
        order=self.order(campaign,items=[{'product_id':self.anchor,'quantity':1},
            {'product_id':self.partner,'quantity':1},{'product_id':extra,'quantity':1}])
        self.assertEqual(order['total_amount'],17000)
        detail=self.get('/api/v1/orders/'+str(order['order_id']))
        self.assertEqual(detail['discount'],4000)
        self.assertEqual(detail['rescue_sets'],1)
        self.assertIn('Giải cứu',detail['rescue_name'])
        self.assertEqual(sum(item['net_subtotal'] for item in detail['items']),17000)
        self.assertEqual(next(item for item in detail['items'] if item['product_id']==extra)['net_subtotal'],5000)
        self.assertIn('Combo:',self.client.get('/receipt/'+str(order['order_id'])).text)

    def test_redemption_cap_is_atomic_and_idempotent(self):
        campaign=self.campaign(max_sets=1)['id']
        data={'rescue_campaign_id':campaign,'rescue_sets':1,'items':[
            {'product_id':self.anchor,'quantity':1},{'product_id':self.partner,'quantity':1}],'payment_method':'TRANSFER'}
        def sell(_): return self.client.post('/api/v1/orders',json=data,headers={'Idempotency-Key':uuid.uuid4().hex}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool: statuses=list(pool.map(sell,range(2)))
        self.assertEqual(sorted(statuses),[200,409])
        self.assertEqual(self.get('/api/v1/rescue/campaigns'),[])
        with reading() as conn:
            self.assertEqual(one(conn,'SELECT stock FROM products WHERE id=?',(self.anchor,))['stock'],19)

    def test_idempotent_order_replay_does_not_consume_another_combo(self):
        campaign=self.campaign(max_sets=2)['id']; key=uuid.uuid4().hex
        data={'rescue_campaign_id':campaign,'rescue_sets':1,'items':[
            {'product_id':self.anchor,'quantity':1},{'product_id':self.partner,'quantity':1}],'payment_method':'TRANSFER'}
        first=self.post('/api/v1/orders',data,headers={'Idempotency-Key':key})
        again=self.post('/api/v1/orders',data,headers={'Idempotency-Key':key})
        self.assertEqual(first['order_id'],again['order_id']); self.assertTrue(again['replayed'])
        self.assertEqual(self.get('/api/v1/rescue/campaigns')[0]['used_sets'],1)

    def test_cancel_restores_capacity_and_returns_refund_original_net_prices(self):
        campaign=self.campaign(max_sets=2)['id']
        order=self.order(campaign,fulfillment='DELIVERY',apartment='Test address')
        self.post(f"/api/v1/orders/{order['order_id']}/status",{'status':'CANCELLED','reason':'Wrong order','method':'TRANSFER'})
        self.assertEqual(self.get('/api/v1/rescue/campaigns')[0]['available_sets'],2)
        sale=self.order(campaign)
        detail=self.get('/api/v1/orders/'+str(sale['order_id']))
        refund=self.post(f"/api/v1/orders/{sale['order_id']}/returns",{'reason':'Return all','method':'TRANSFER','items':[
            {'item_id':item['id'],'quantity':1,'restock':True} for item in detail['items']]})
        self.assertEqual(refund['refund'],12000)

    def test_stopped_expired_changed_cost_and_insufficient_basket_are_rejected(self):
        campaign=self.campaign(max_sets=2)['id']
        data={'rescue_campaign_id':campaign,'rescue_sets':1,'items':[{'product_id':self.anchor,'quantity':1}],'payment_method':'TRANSFER'}
        self.post('/api/v1/orders',data,400,headers={'Idempotency-Key':uuid.uuid4().hex})
        with transaction() as conn: conn.execute('UPDATE stock_batches SET cost_price=7000 WHERE product_id=?',(self.partner,))
        data['items'].append({'product_id':self.partner,'quantity':1})
        self.post('/api/v1/orders',data,409,headers={'Idempotency-Key':uuid.uuid4().hex})
        with transaction() as conn: conn.execute('UPDATE stock_batches SET cost_price=3000 WHERE product_id=?',(self.partner,))
        self.post('/api/v1/rescue/campaigns/'+str(campaign)+'/stop',{})
        before=self.snapshot()
        self.post('/api/v1/orders',data,409,headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(self.snapshot(),before)
        with transaction() as conn: conn.execute('UPDATE rescue_campaigns SET active=1,expires_on=? WHERE id=?',((date.today()-timedelta(days=1)).isoformat(),campaign))
        self.post('/api/v1/orders',data,409,headers={'Idempotency-Key':uuid.uuid4().hex})

    def test_combo_cannot_stack_manual_discounts_or_points(self):
        campaign=self.campaign(max_sets=2)['id']
        for extra in [{'discount':1},{'points_redeemed':1}]:
            self.post('/api/v1/orders',{'rescue_campaign_id':campaign,'rescue_sets':1,'items':[
                {'product_id':self.anchor,'quantity':1},{'product_id':self.partner,'quantity':1}],
                'payment_method':'TRANSFER',**extra},400,headers={'Idempotency-Key':uuid.uuid4().hex})

    def test_permissions_csrf_and_stale_quote(self):
        q=self.quote(max_sets=2)
        body={'batch_id':self.batch,'partner_id':self.partner,'max_sets':2,'discount_percent':25,'expected_price':q['price']-1}
        self.post('/api/v1/rescue/campaigns',body,409)
        self.post('/api/v1/rescue/campaigns',body,403,headers={'X-CSRF-Token':''})
        for role in ['inventory','cashier']:
            self.post('/api/v1/users',{'username':role,'name':role,'role':role,'password':'rescue-test-password'})
        self.login('inventory')
        self.quote(); self.get('/api/v1/rescue')
        self.post('/api/v1/rescue/campaigns',body,403)
        self.login('cashier')
        self.get('/api/v1/rescue/campaigns')
        self.assertEqual(self.client.get('/api/v1/rescue').status_code,403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/v1/rescue/campaigns').status_code,401)

    def test_migration_keeps_existing_data_and_is_idempotent(self):
        self.order()
        with transaction() as conn:
            before={name:rows(conn,'SELECT * FROM '+name) for name in ['products','orders','stock_batches','payments','order_items']}
            conn.execute('DROP TABLE rescue_campaigns'); conn.execute('DELETE FROM schema_migrations WHERE version=6')
        migrate(); migrate()
        with reading() as conn:
            for name,value in before.items(): self.assertEqual(rows(conn,'SELECT * FROM '+name),value)
            self.assertEqual(one(conn,'SELECT MAX(version) AS n FROM schema_migrations')['n'],SCHEMA_VERSION)
            self.assertEqual(rows(conn,'PRAGMA foreign_key_check'),[])
        self.assertTrue(list((Path(config.SQLITE_PATH).parent/'backups').glob('before-v6-*.db')))


if __name__=='__main__': unittest.main()

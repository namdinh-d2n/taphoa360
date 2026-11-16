"""Public product merchandising stays read-only, truthful and scoped to saleable stock."""
from datetime import datetime,timedelta
from pathlib import Path
import json,tempfile,unittest,uuid
from fastapi.testclient import TestClient
import config,db
from app import app
from retail import commerce
from retail.database import reading,transaction,one,rows


class ProductDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix='th360-discovery-')
        self.original=config.SQLITE_PATH,db.SQLITE_PATH,config.SEED_DEMO
        config.SQLITE_PATH=db.SQLITE_PATH=str(Path(self.folder.name)/'shop.db');config.SEED_DEMO=False
        self.staff=TestClient(app);self.staff.__enter__()
        self.staff.post('/api/setup',json={'username':'owner','name':'Owner','password':'product-test-123'})
        login=self.staff.post('/api/login',json={'username':'owner','password':'product-test-123'}).json()
        self.staff.headers['X-CSRF-Token']=login['csrf']
        self.supplier=self.post('/api/v1/suppliers',{'name':'Supplier'})['id']
        self.bread=self.product('Bánh mì sandwich A','Bánh tươi & sandwich','DRY','Brand A')
        self.milk=self.product('Sữa tươi 1L','Sữa tươi','CHILLED','Brand Milk')
        self.related=self.product('Bánh mì sandwich B','Bánh tươi & sandwich','DRY','Brand B',count=0)
        self.same_brand=self.product('Bánh bông lan A','Bánh bông lan','DRY','Brand A',count=0)
        self.soap=self.product('Nước rửa chén','Nước rửa chén','HOUSEHOLD','Brand Soap')
        self.anon=TestClient(app)

    def tearDown(self):
        self.anon.close();self.staff.__exit__(None,None,None)
        config.SQLITE_PATH,db.SQLITE_PATH,config.SEED_DEMO=self.original;self.folder.cleanup()

    def post(self,path,data):
        r=self.staff.post(path,json=data);self.assertEqual(r.status_code,200,r.text);return r.json()

    def product(self,name,category,storage,brand,count=10):
        p=self.post('/api/v1/products',{'product_name':name,'category':category,'storage_kind':storage,'brand':brand,
            'unit':'hộp','price':10000,'zone_code':'A1','description':'Mô tả do cửa hàng khai báo.'})['id']
        if count:self.post('/api/v1/purchases',{'supplier_id':self.supplier,'paid':0,'items':[
            {'product_id':p,'quantity':count,'cost_price':6000,'expires_on':(datetime.fromisoformat(commerce.clock())+timedelta(days=5)).date().isoformat()}]})
        return p

    def detail(self,p):
        r=self.anon.get('/api/shop/products/'+str(p));self.assertEqual(r.status_code,200,r.text);return r.json()

    def snapshot(self):
        with reading() as conn:return {t:rows(conn,'SELECT * FROM '+t) for t in ['products','orders','order_items','stock_batches','stock_movements','payments','audit_log']}

    def test_detail_and_recommendations_are_public_read_only_and_no_cost_leak(self):
        before=self.snapshot();data=self.detail(self.bread)
        self.assertEqual(data['product']['description'],'Mô tả do cửa hàng khai báo.')
        self.assertEqual(data['product']['brand'],'Brand A')
        for p in [data['product'],*data['cross_sell'],*data['related']]:
            for key in ['cost_price','supplier_cost_price','reference_price','supplier_sku']:self.assertNotIn(key,p)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.anon.get('/api/shop/products/999999').status_code,404)

    def test_recommendations_distinguish_complements_related_and_brands(self):
        data=self.detail(self.bread)
        self.assertEqual([p['id'] for p in data['cross_sell']],[self.milk])
        self.assertEqual(data['cross_sell'][0]['suggestion_basis'],'complement')
        self.assertIsNone(data['cross_sell'][0]['co_orders'])
        self.assertIn('chưa đủ lịch sử',data['cross_sell'][0]['suggestion_reason'])
        self.assertEqual({p['id'] for p in data['related']},{self.related,self.same_brand})
        self.assertEqual(data['brands'][0]['name'],'Brand A')
        self.assertEqual(data['brands'][0]['product_count'],2)
        self.assertEqual(data['brands'][0]['available_count'],1)
        self.assertIn('Brand B',{b['name'] for b in data['brands']})
        self.assertNotIn('Brand Soap',{b['name'] for b in data['brands']})
        self.assertFalse(any(p['id']==self.bread for p in data['cross_sell']+data['related']))

    def test_three_completed_distinct_baskets_justify_purchase_together_claim(self):
        last=None
        for i in range(3):
            last=self.post('/api/v1/orders',{'items':[{'product_id':self.bread,'quantity':1},{'product_id':self.milk,'quantity':1}],
                'payment_method':'TRANSFER','idempotency_key':uuid.uuid4().hex})
        data=self.detail(self.bread);suggestion=data['cross_sell'][0]
        self.assertEqual(suggestion['suggestion_basis'],'history');self.assertEqual(suggestion['co_orders'],3)
        detail=self.staff.get('/api/v1/orders/'+str(last['order_id'])).json()
        item=next(i for i in detail['items'] if i['product_id']==self.milk)
        self.post('/api/v1/orders/'+str(last['order_id'])+'/returns',{'reason':'Test','method':'TRANSFER','items':[{'item_id':item['id'],'quantity':1,'restock':True}]})
        suggestion=self.detail(self.bread)['cross_sell'][0]
        self.assertEqual(suggestion['suggestion_basis'],'complement');self.assertIsNone(suggestion['co_orders'])

    def test_pending_cancelled_old_and_future_orders_do_not_inflate_support(self):
        for condition in ['PENDING','CANCELLED','OLD','FUTURE']:
            order=self.post('/api/v1/orders',{'items':[{'product_id':self.bread,'quantity':1},{'product_id':self.milk,'quantity':1}],
                'payment_method':'TRANSFER','idempotency_key':uuid.uuid4().hex})
            with transaction() as conn:
                if condition in {'PENDING','CANCELLED'}:conn.execute('UPDATE orders SET status=? WHERE id=?',(condition,order['order_id']))
                else:conn.execute('UPDATE orders SET created_at=? WHERE id=?',((datetime.fromisoformat(commerce.clock())+timedelta(days=-40 if condition=='OLD' else 3)).isoformat(),order['order_id']))
        self.assertEqual(self.detail(self.bread)['cross_sell'][0]['suggestion_basis'],'complement')

    def test_cross_sell_respects_quality_expiry_cutoff_and_hidden_products(self):
        with transaction() as conn:conn.execute("UPDATE stock_batches SET quality_status='HOLD' WHERE product_id=?",(self.milk,))
        self.assertEqual(self.detail(self.bread)['cross_sell'],[])
        with transaction() as conn:conn.execute("UPDATE stock_batches SET quality_status='SELLABLE',expires_on='2000-01-01' WHERE product_id=?",(self.milk,))
        self.assertEqual(self.detail(self.bread)['cross_sell'],[])
        with transaction() as conn:conn.execute("UPDATE stock_batches SET expires_on='2099-01-01',sell_until='2000-01-01T00:00:00' WHERE product_id=?",(self.milk,))
        self.assertEqual(self.detail(self.bread)['cross_sell'],[])
        with transaction() as conn:conn.execute('UPDATE products SET online_enabled=0 WHERE id=?',(self.related,))
        self.assertNotIn(self.related,[p['id'] for p in self.detail(self.bread)['related']])
        self.assertEqual(self.anon.get('/api/shop/products/'+str(self.related)).status_code,404)

    def test_sale_details_use_active_price_and_real_remaining_cap(self):
        now=datetime.fromisoformat(commerce.clock())
        self.post('/api/v1/shop/sales',{'name':'Thử sale','product_id':self.bread,'price':8000,'max_units':3,
            'starts_at':(now-timedelta(minutes=2)).isoformat(),'ends_at':(now+timedelta(minutes=30)).isoformat()})
        data=self.detail(self.bread)['product']
        self.assertEqual(data['price'],8000);self.assertEqual(data['regular_price'],10000)
        self.assertEqual(data['sale']['remaining'],3)
        self.post('/api/v1/orders',{'items':[{'product_id':self.bread,'quantity':2}],'payment_method':'TRANSFER','idempotency_key':uuid.uuid4().hex})
        self.assertEqual(self.detail(self.bread)['product']['sale']['remaining'],1)

    def test_brand_filter_matches_exact_brand_not_substring(self):
        self.product('Bánh thương hiệu A Plus','Bánh tươi & sandwich','DRY','Brand A Plus',count=0)
        response=self.anon.get('/api/shop/catalog',params={'brand':'  brand a  '})
        self.assertEqual(response.status_code,200)
        self.assertEqual({p['id'] for p in response.json()['products']},{self.bread,self.same_brand})
        self.assertIn('Brand B',response.json()['brands'])
        self.assertEqual(self.anon.get('/api/shop/catalog',params={'brand':'<unknown>'}).json()['products'],[])

    def test_cross_sell_limit_and_unknown_brand_are_not_fabricated(self):
        for i in range(5):self.product('Sữa khác '+str(i),'Sữa tươi','CHILLED','Milk '+str(i))
        self.assertEqual(len(self.detail(self.bread)['cross_sell']),3)
        with transaction() as conn:conn.execute("UPDATE products SET brand='' WHERE id=?",(self.bread,))
        data=self.detail(self.bread)
        self.assertEqual(data['product']['brand'],'')
        self.assertFalse(any(b['current'] for b in data['brands']))

    def test_fallback_does_not_push_expensive_bulk_box_without_purchase_history(self):
        with transaction() as conn:conn.execute('UPDATE products SET price=1000000 WHERE id=?',(self.milk,))
        self.assertEqual(self.detail(self.bread)['cross_sell'],[])


if __name__=='__main__':unittest.main()

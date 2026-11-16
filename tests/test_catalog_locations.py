"""Reference data cannot invent inventory or override store prices; addresses stay local."""
from pathlib import Path
import json,sqlite3,tempfile,unittest,uuid,hashlib
from fastapi.testclient import TestClient
import config,db
from app import app
from retail.database import reading,transaction,migrate,rows,one,SCHEMA_VERSION
from retail.locations import address_snapshot,dataset
from retail.catalog_data import taxonomy
from scripts.import_catalog_reference import import_catalog


class CatalogLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='th360-catalog-')
        self.original=config.SQLITE_PATH,db.SQLITE_PATH,config.SEED_DEMO
        config.SQLITE_PATH=db.SQLITE_PATH=str(Path(self.temp.name)/'test.db');config.SEED_DEMO=False
        self.staff=TestClient(app);self.staff.__enter__()
        self.staff.post('/api/setup',json={'username':'owner','name':'Owner','password':'catalog-test-123'})
        auth=self.staff.post('/api/login',json={'username':'owner','password':'catalog-test-123'}).json()
        self.staff.headers['X-CSRF-Token']=auth['csrf']
        self.manifest=json.loads((config.BASE_DIR/'data/catalog-reference.json').read_text(encoding='utf-8'))
        self.sample={**self.manifest,'products':self.manifest['products'][:3]}

    def tearDown(self):
        self.staff.__exit__(None,None,None)
        config.SQLITE_PATH,db.SQLITE_PATH,config.SEED_DEMO=self.original;self.temp.cleanup()

    def test_vietnam_snapshot_complete_and_unique_without_remote_dependency(self):
        data=self.staff.get('/api/shop/locations').json()
        self.assertEqual(len(data['provinces']),34);self.assertEqual(data['ward_count'],3321)
        codes=[w['code'] for p in dataset()['provinces'] for w in p['wards']]
        self.assertEqual(len(codes),len(set(codes)))
        first=data['provinces'][0]
        wards=self.staff.get('/api/shop/locations/'+str(first['code'])+'/wards').json()['wards']
        self.assertGreater(len(wards),0)
        self.assertEqual(self.staff.get('/api/shop/locations/9999/wards').status_code,404)

    def test_selected_address_rejects_wrong_ward_and_ignores_forged_free_text(self):
        provinces=dataset()['provinces'];p=provinces[0];w=p['wards'][0]
        result=address_snapshot({'address_mode':'SELECT','province_code':p['code'],'ward_code':w['code'],'address_line':'Căn A1, 10 đường A','address':'FORGED'})
        self.assertEqual(result['address'],f"Căn A1, 10 đường A, {w['name']}, {p['name']}")
        from fastapi import HTTPException
        for extra in [{'ward_code':provinces[1]['wards'][0]['code']},{'province_code':True},{'address_line':''},{'ward_code':'4'}]:
            with self.assertRaises(HTTPException):address_snapshot({'address_mode':'SELECT','province_code':p['code'],'ward_code':w['code'],'address_line':'Test',**extra})
        self.assertEqual(address_snapshot({'address_mode':'MANUAL','address':'Địa chỉ tự nhập của khách'})['address'],'Địa chỉ tự nhập của khách')

    def test_reference_import_is_idempotent_and_creates_no_inventory_or_business_records(self):
        with transaction() as conn:
            first=import_catalog(conn,self.sample)
            second=import_catalog(conn,self.sample)
        self.assertEqual(first['added'],3);self.assertEqual(second['added'],0)
        with reading() as conn:
            self.assertEqual(one(conn,'SELECT SUM(stock) n FROM products')['n'],0)
            for name in ['stock_batches','purchase_receipts','stock_movements','payments','account_entries','orders']:
                self.assertEqual(one(conn,'SELECT COUNT(*) n FROM '+name)['n'],0,name)
            self.assertTrue(all(p['catalog_origin']=='REFERENCE' for p in rows(conn,'SELECT * FROM products')))
            self.assertTrue(all(s['is_sample']==1 for s in rows(conn,'SELECT * FROM suppliers')))
            self.assertTrue(all(s['is_sample_price']==1 for s in rows(conn,'SELECT * FROM supplier_products')))

    def test_import_keeps_manual_prices_and_existing_supplier_quote(self):
        with transaction() as conn:import_catalog(conn,self.sample)
        with reading() as conn:product=one(conn,'SELECT * FROM products WHERE sku=?',(self.sample['products'][0]['sku'],))
        response=self.staff.patch('/api/v1/products/'+str(product['id']),json={'price':33333})
        self.assertEqual(response.status_code,200,response.text)
        with transaction() as conn:import_catalog(conn,self.sample)
        with reading() as conn:
            updated=one(conn,'SELECT * FROM products WHERE id=?',(product['id'],))
            self.assertEqual(updated['price'],33333);self.assertEqual(updated['catalog_origin'],'STORE')

    def test_public_category_groups_and_stockless_images_are_present(self):
        with transaction() as conn:import_catalog(conn,self.sample)
        catalog=self.staff.get('/api/shop/catalog').json()
        self.assertGreaterEqual(len(catalog['category_groups']),17)
        self.assertEqual(len(catalog['products']),3)
        self.assertTrue(all(p['stock']==0 and p['image_path'].startswith('/static/catalog-images/') for p in catalog['products']))
        for p in catalog['products']:self.assertEqual(self.staff.get(p['image_path']).status_code,200)
        self.assertTrue(any('Snack & bim bim' in group['categories'] for group in catalog['category_groups']))

    def test_checkout_saves_validated_address_and_does_not_expand_delivery_zones(self):
        account=TestClient(app)
        registration={'name':'Test','phone':'0900000000','password':'test-password-123','confirm_password':'test-password-123'}
        account.post('/api/shop/register',json=registration);account.post('/api/shop/login',json=registration)
        me=account.get('/api/shop/me').json();account.headers['X-CSRF-Token']=me['csrf']
        self.staff.post('/api/v1/shop/zones',json={'name':'Khu giao thật','fee':12000})
        with reading() as conn:zone=one(conn,'SELECT id FROM delivery_zones')['id']
        p=self.staff.post('/api/v1/products',json={'product_name':'Test product','price':10000,'unit':'cai','zone_code':'A1'}).json()['id']
        supplier=self.staff.post('/api/v1/suppliers',json={'name':'NCC thật'}).json()['id']
        self.staff.post('/api/v1/purchases',json={'supplier_id':supplier,'paid':0,'items':[{'product_id':p,'quantity':2,'cost_price':6000}]})
        province=dataset()['provinces'][0];ward=province['wards'][0]
        data={'items':[{'product_id':p,'quantity':1}],'zone_id':zone,'receiver':'Test','phone':'0900000000','payment_method':'COD','substitution':'CALL',
              'address_mode':'SELECT','province_code':province['code'],'ward_code':ward['code'],'address_line':'Địa chỉ mẫu','address':'NOT TRUSTED'}
        q=account.post('/api/shop/quote',json=data);self.assertEqual(q.status_code,200,q.text)
        result=account.post('/api/shop/orders',json={**data,'fingerprint':q.json()['fingerprint']},headers={'Idempotency-Key':uuid.uuid4().hex})
        self.assertEqual(result.status_code,200,result.text)
        with reading() as conn:
            o=one(conn,'SELECT * FROM online_orders WHERE id=?',(result.json()['id'],))
            self.assertEqual(o['province_code'],province['code']);self.assertIn(ward['name'],o['address']);self.assertNotIn('NOT TRUSTED',o['address'])
            self.assertEqual(one(conn,'SELECT COUNT(*) n FROM delivery_zones')['n'],1)
        account.close()

    def test_reference_assets_match_recorded_checksums_and_taxonomy(self):
        names={name for group in taxonomy() for name in group['categories']}
        skus=set()
        for p in self.manifest['products']:
            self.assertNotIn(p['sku'],skus);skus.add(p['sku'])
            self.assertIn(p['category'],names)
            self.assertLessEqual(len(p['unit']),30)
            path=config.BASE_DIR/p['image_path'].lstrip('/')
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),p['image_sha256'])
            self.assertGreater(p['price'],0)


if __name__=='__main__':unittest.main()

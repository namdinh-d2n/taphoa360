"""Idempotent import: reference retail prices/photos and explicitly sample suppliers.

New products have ZERO stock. Existing receipts, allocations, balances and stock
are never rewritten. Manually edited prices become STORE and survive re-import.
"""
from datetime import datetime
from pathlib import Path
import argparse,json,sqlite3,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


LEGACY={
 'SKU-SUA-01':('Sữa tươi','DRY','', 'milk'),
 'SKU-BM-02':('Bánh tươi & sandwich','DRY','', 'bread'),
 'SKU-COCA-03':('Nước ngọt','DRY','Coca-Cola', 'cola'),
 'SKU-MI-04':('Mì ăn liền','DRY','Hảo Hảo', 'noodle'),
 'SKU-SC-05':('Sữa chua ăn','CHILLED','Vinamilk', 'yogurt'),
 'SKU-BIA-06':('Bia & đồ uống có cồn','DRY','Heineken', 'beer')}


def import_catalog(conn,manifest):
    from retail.common import audit
    from retail.catalog_data import group_for
    suppliers={};added=updated=0
    for item in manifest['products']:
        name='NCC mẫu — '+item['group']
        supplier=conn.execute('SELECT id FROM suppliers WHERE name=? AND is_sample=1',(name,)).fetchone()
        if not supplier:
            ident=conn.execute('INSERT INTO suppliers(name,phone,address,is_sample,note) VALUES(?,?,?,?,?)',
                (name,'','Chưa có địa chỉ thực tế',1,'Dữ liệu minh họa. Không đại diện nhà phân phối/nhãn hàng. Giá nhập ước tính 80% giá bán tham khảo, cần thay bằng báo giá thật.')).lastrowid
        else:ident=supplier[0]
        suppliers[item['group']]=ident
        old=conn.execute('SELECT * FROM products WHERE sku=?',(item['sku'],)).fetchone()
        if old and old['catalog_origin']!='REFERENCE':continue
        if old:pid=old['id'];updated+=1
        else:
            pid=conn.execute('''INSERT INTO products(product_name,sku,barcode,price,cost_price,unit,zone_code,shelf_location,min_stock,active,stock)
                VALUES(?,?,'',?,?,?,'CHUA-XEP','',5,1,0)''',
                (item['product_name'],item['sku'],item['price'],item['sample_cost_price'],item['unit'])).lastrowid;added+=1
        conn.execute('''UPDATE products SET product_name=?,price=?,cost_price=?,unit=?,category=?,storage_kind=?,description=?,image_path=?,brand=?,
            catalog_origin='REFERENCE',reference_price=?,reference_source=?,reference_checked_at=? WHERE id=?''',
            (item['product_name'],item['price'],item['sample_cost_price'],item['unit'],item['category'],item['storage_kind'],
             'Quy cách: '+item['unit']+'. Bảo quản theo hướng dẫn trên bao bì. Giá tham khảo bán lẻ; chưa có tồn thực tế.',
             item['image_path'],item['brand'],item['price'],item['source_url'],item['checked_at'],pid))
        conn.execute('''INSERT INTO supplier_products(supplier_id,product_id,cost_price,supplier_sku,is_sample_price) VALUES(?,?,?,?,1)
            ON CONFLICT(supplier_id,product_id) DO UPDATE SET cost_price=CASE WHEN is_sample_price=1 THEN excluded.cost_price ELSE cost_price END''',
            (ident,pid,item['sample_cost_price'],item['sku']))
    for sku,(category,storage,brand,art) in LEGACY.items():
        old=conn.execute('SELECT * FROM products WHERE sku=?',(sku,)).fetchone()
        if not old:continue
        if old['category']=='Thiết yếu':conn.execute('UPDATE products SET category=?,storage_kind=?,brand=? WHERE id=?',(category,storage,brand,old['id']))
        if not old['image_path']:conn.execute('UPDATE products SET image_path=? WHERE id=?',('/static/catalog-images/store-'+art+'.svg',old['id']))
    audit(conn,None,'IMPORT_REFERENCE_CATALOG','catalog',{'added':added,'updated':updated,'reference_date':manifest['checked_at'],'sample_suppliers':len(suppliers),'stock_created':0})
    return {'added':added,'updated':updated,'sample_suppliers':len(suppliers),'stock_created':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--database');parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    import config
    from retail.database import migrate
    if args.database:config.SQLITE_PATH=str(Path(args.database).resolve())
    if not args.apply:
        data=json.loads((ROOT/'data/catalog-reference.json').read_text(encoding='utf-8'))
        print('Ready:',len(data['products']),'reference products; no writes. Use --apply.');return
    migrate()
    conn=sqlite3.connect(config.SQLITE_PATH);conn.row_factory=sqlite3.Row
    folder=Path(config.SQLITE_PATH).parent/'backups';folder.mkdir(exist_ok=True)
    target=sqlite3.connect(folder/('before-catalog-import-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db'))
    try:conn.backup(target)
    finally:target.close()
    conn.execute('PRAGMA foreign_keys=ON');conn.execute('BEGIN IMMEDIATE')
    try:
        manifest=json.loads((ROOT/'data/catalog-reference.json').read_text(encoding='utf-8'))
        result=import_catalog(conn,manifest);conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()

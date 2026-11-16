"""Build factual catalogue snapshot from saved public product cards and download photos.

No browser credentials or APIs are used. Prices are reference retail observations;
estimated purchase prices and suppliers must be labelled as sample data on import.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime
from io import BytesIO
from pathlib import Path
import argparse,hashlib,json,re,urllib.request

ROOT=Path(__file__).resolve().parents[1]
MAPPING={
 'snack':'Snack & bim bim','banh-quy':'Bánh quy','banh-gao':'Bánh gạo','banh-xop':'Bánh xốp','banh-que':'Bánh quế','banh-dua':'Bánh que',
 'banh-chocopie-kitkat':'Bánh Chocopie','banh-bong-lan':'Bánh bông lan','banh-ngot':'Bánh tươi & sandwich','keo-cung':'Kẹo cứng','keo-mem':'Kẹo dẻo & marshmallow',
 'singum-keo-cao-su':'Kẹo cao su','socola':'Socola','cac-loai-hat':'Hạt dinh dưỡng','trai-cay-say':'Trái cây sấy','rau-cau':'Rau câu & thạch',
 'trung':'Trứng','ca-tom-muc-ech':'Cá & hải sản tươi','thit-heo':'Thịt heo','thit-bo':'Thịt bò','thit-ga':'Thịt gà & vịt','rau-sach':'Rau lá','trai-cay-tuoi-ngon':'Trái cây tươi',
 'sua-bot-cong-thuc':'Sữa bột & dinh dưỡng','sua-tuoi':'Sữa tươi','sua-chua':'Sữa chua uống','sua-tu-hat':'Sữa hạt & sữa đậu','sua-dac':'Sữa đặc','sua-chua-an':'Sữa chua ăn',
 'nuoc-ngot':'Nước ngọt','nuoc-tra':'Trà đóng chai','nuoc-suoi-khoang':'Nước suối & khoáng','nuoc-tang-luc':'Nước tăng lực & thể thao','nuoc-ep-trai-cay':'Nước ép & nước trái cây','bia':'Bia & đồ uống có cồn',
 'gao-gao-nep':'Gạo & nếp','ca-phe-hoa-tan':'Cà phê hòa tan','mi-chay':'Mì ăn liền','bot-che-bien-san':'Bột các loại','dau-cac-loai':'Đậu & thực phẩm khô',
 'dau-an':'Dầu ăn','nuoc-mam':'Nước mắm','nuoc-tuong':'Nước tương','duong':'Muối, đường & tiêu','hat-nem':'Hạt nêm & bột ngọt',
 'ca-hop':'Cá hộp','thit-heo-hop':'Thịt hộp & pate','xuc-xich':'Xúc xích ăn liền','kem':'Kem',
 'nuoc-giat':'Nước giặt & bột giặt','nuoc-xa':'Nước xả vải','nuoc-rua-chen':'Nước rửa chén','kem-danh-rang':'Kem đánh răng','dau-goi':'Dầu gội & dầu xả',
 'khan-giay':'Khăn ướt & khăn giấy','khan-giay-uot':'Khăn ướt & khăn giấy','tui-dung-rac':'Túi rác & túi đựng','pin-tieu':'Pin & đồ điện nhỏ',
 'ban-chai-danh-rang-cho-be':'Chăm sóc răng cho bé','kem-danh-rang-cho-be':'Chăm sóc răng cho bé','nuoc-xa-vai-cho-be':'Giặt xả cho bé',
 'tam-goi-2-trong-1-cho-be':'Tắm gội & chăm sóc bé','phan-thom-cham-soc-da-be':'Tắm gội & chăm sóc bé'
}
BRANDS=['Vinamilk','Dutch Lady','TH true MILK','TH true','Nutifood','Nestlé','Milo','Abbott','Ensure','Dielac','Friso','PediaSure','Anlene','GrowPLUS',
 'Oishi','Orion','Mentos','Alpenliebe','Chupa Chups','Haribo','Sugus','Chupa','Lay\'s','Lay’s','Poca','O\'Star','Swing','Tao Kae Noi','Bento','Enaak','Mplus','Richy',
 'Hữu Nghị','Kinh Đô','Cosy','Oreo','Ritz','ChocoPie','Danisa','LU','AFC','Goute','Tài Tài','Tân Tân','Lotte','KitKat','Meiji','Otto','Staff','Bobby','Huggies',
 'Coca-Cola','Coca Cola','Pepsi','7 Up','7Up','Sprite','Fanta','Aquafina','La Vie','Lavie','Vĩnh Hảo','Revive','Sting','Red Bull','Number 1','Twister','TEA+','Ô Long',
 'Heineken','Tiger','Sài Gòn','Budweiser','Strongbow','1664','Hảo Hảo','Handy','Acecook','Vifon','Omachi','Gấu Đỏ','Kokomi','Cung Đình','Knorr','Ajinomoto','Aji-ngon',
 'Simply','Tường An','Neptune','Meizan','Chin-su','Chinsu','Nam Ngư','Tam Thái Tử','Maggi','DH Foods','C.P','Vissan','Ponnie','Unif','Seaspimex','Three Lady Cooks',
 'G7','Nescafé','Nescafe','Trung Nguyên','Vinacafé','Wake-up','Omo','Ariel','Tide','Comfort','Downy','Lix','Surf','P/S','Colgate','Closeup','Sensodyne',
 'Clear','Sunsilk','Dove','Head & Shoulders','Pantene','Romano','X-Men','Rejoice','Sunlight','Vim','Lifebuoy','Enchanteur','Puri','Pulppy','Tempo','Bless You','Energizer','Panasonic']


def build(source,limit=10):
    pages=json.loads(Path(source).read_text(encoding='utf-8'))
    tree=json.loads((ROOT/'data/categories.json').read_text(encoding='utf-8'))
    groups={leaf:group for group in tree for leaf in group['categories']}
    seen=set();counts={};items=[]
    for page in pages:
        for raw in page['items']:
            if raw['id'] in seen or not raw.get('name') or not raw.get('image'):continue
            path=raw['url'].split('.com/')[-1].split('/')[0];category=MAPPING.get(path)
            if not category:continue
            if counts.get(category,0)>=limit:continue
            prices=re.findall(r'(?<!\d)(\d{1,3}(?:[.,]\d{3})+|\d+)\s*đ',raw.get('text',''))
            if not prices:continue
            price=int(re.sub('[.,]','',prices[0]))
            if not 500<=price<=10_000_000:continue
            spec=next((line.strip().lstrip('/').strip() for line in raw['text'].splitlines() if line.strip().startswith('/')),'')
            if not spec:
                match=re.search(r'(?:gói|hộp|túi|lon|chai|bịch|thùng|lốc|khay|hũ|cây)\s+[^,]{1,35}$',raw['name'],re.I)
                spec=match.group() if match else '1 sản phẩm theo tên/quy cách'
            spec=re.sub(r'\s*\(giao.*','',spec,flags=re.I).strip()[:30]
            group=groups[category]
            storage=group['storage']
            if category=='Sữa chua ăn':storage='CHILLED'
            if category in {'Thịt heo','Thịt bò','Thịt gà & vịt','Cá & hải sản tươi'} and 'đông lạnh' in raw['name'].lower():
                category='Thịt & hải sản đông lạnh';group=groups[category];storage='FROZEN'
            brand=next((brand for brand in BRANDS if brand.lower() in raw['name'].lower()),'')
            product_id=raw['id'].removeprefix('product_')
            item={'sku':'REF-BHX-'+product_id,'source_id':product_id,'product_name':raw['name'],'unit':spec,'price':price,
                  'sample_cost_price':max(500,int(price*.80/500)*500),'category':category,'group':group['name'],'storage_kind':storage,'brand':brand,
                  'source_url':raw['url'],'image_url':raw['image'],'checked_at':'2026-11-13'}
            items.append(item);seen.add(raw['id']);counts[category]=counts.get(category,0)+1
    return items


def photo(item):
    from PIL import Image,ImageOps
    target=ROOT/'static/catalog-images'/(item['sku'].lower()+'.webp')
    if not target.exists():
        request=urllib.request.Request(item['image_url'],headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(request,timeout=25) as response:data=response.read(4*1024*1024)
        img=Image.open(BytesIO(data));img.load();img=img.convert('RGB');img.thumbnail((480,480))
        canvas=Image.new('RGB',(480,480),'white');canvas.paste(img,((480-img.width)//2,(480-img.height)//2));canvas.save(target,'WEBP',quality=85)
    item['image_path']='/static/catalog-images/'+target.name
    item['image_sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
    return item


def main():
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('--limit',type=int,default=10)
    args=parser.parse_args();items=build(args.source,args.limit)
    (ROOT/'static/catalog-images').mkdir(exist_ok=True)
    errors=[];completed=[]
    with ThreadPoolExecutor(max_workers=5) as pool:
        tasks={pool.submit(photo,item):item for item in items}
        for future in as_completed(tasks):
            try:completed.append(future.result())
            except Exception as exc:errors.append({'sku':tasks[future]['sku'],'error':str(exc)})
            if (len(completed)+len(errors))%50==0:print('Photos:',len(completed),'errors:',len(errors),flush=True)
    completed.sort(key=lambda item:(item['group'],item['category'],item['product_name']))
    result={'checked_at':'2026-11-13','source':'https://www.bachhoaxanh.com/','price_kind':'PUBLIC_RETAIL_REFERENCE',
            'sample_cost_rule':'80% giá tham khảo, làm tròn xuống 500đ. Chỉ là dữ liệu mẫu, không phải báo giá nhà cung cấp.',
            'inventory_policy':'Không tạo tồn, lô, phiếu nhập hoặc công nợ.','products':completed}
    (ROOT/'data/catalog-reference.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'.local/catalog-source/photo-errors.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Saved',len(completed),'products,',len({i['category'] for i in completed}),'categories. Errors:',len(errors),flush=True)
    if errors:raise SystemExit(1)


if __name__=='__main__':main()

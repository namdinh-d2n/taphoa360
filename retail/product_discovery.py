"""Read-only product details and local, explainable merchandising suggestions."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import re

from .common import fail
from .database import rows
from . import commerce


def brand_key(value):
    return ' '.join(str(value or '').casefold().split())


def intent(product):
    category=commerce.normalize(product['category'])
    name=commerce.normalize(product['product_name'])
    group=product['category_group']
    combined=category+' '+name
    if re.search(r'\b(bia|beer)\b',combined): return 'beer'
    if re.search(r'\btrung\b',category) or re.search(r'\btrung (ga|vit|cut)\b',name): return 'eggs'
    if re.search(r'\b(sandwich|banh mi|banh tuoi|banh bong lan)\b',combined): return 'bread'
    if group=='Sữa & chế phẩm sữa' or re.search(r'\b(sua|pho mai)\b',combined): return 'dairy'
    if group=='Gia vị & nấu ăn': return 'seasoning'
    if group=='Rau, củ & nấm': return 'vegetables'
    if group in {'Thịt, cá & trứng','Thực phẩm đông lạnh','Thực phẩm mát'}: return 'protein'
    if re.search(r'\b(mi|pho|bun|mien|chao)\b',category): return 'noodles'
    if group in {'Đồ uống','Cà phê, trà & ngũ cốc'}: return 'drinks'
    if group=='Bánh kẹo & ăn vặt': return 'snacks'
    return ''


COMPLEMENTS={
    'eggs':{'vegetables','seasoning'}, 'vegetables':{'eggs','protein','seasoning'},
    'protein':{'vegetables','seasoning'}, 'seasoning':{'vegetables','protein','eggs'},
    'bread':{'dairy','drinks'}, 'dairy':{'bread','snacks'},
    'noodles':{'drinks','eggs','vegetables'}, 'snacks':{'drinks','dairy'},
    'drinks':{'snacks','bread'}, 'beer':{'snacks'},
}


def recent_baskets(conn,product_id):
    today=datetime.fromisoformat(commerce.clock()).date()
    start=(today-timedelta(days=27)).isoformat()
    end=(today+timedelta(days=1)).isoformat()
    values=rows(conn,'''SELECT DISTINCT o.id,i.product_id FROM orders o JOIN order_items i ON i.order_id=o.id
        WHERE o.managed=1 AND o.status IN ('COMPLETED','PARTIAL_RETURN') AND o.created_at>=? AND o.created_at<?
        AND i.quantity>i.returned_qty''',(start,end))
    baskets=defaultdict(set)
    for value in values:baskets[value['id']].add(value['product_id'])
    pairs=Counter();popular=Counter()
    for ids in baskets.values():
        popular.update(ids)
        if product_id in ids:pairs.update(ids-{product_id})
    return pairs,popular


def product_details(conn,ident):
    catalog=commerce.public_catalog(conn)
    product=next((p for p in catalog['products'] if p['id']==ident),None)
    if product is None:fail('Sản phẩm không còn bán trên cửa hàng online.',404)
    others=[p for p in catalog['products'] if p['id']!=ident]
    pairs,popular=recent_baskets(conn,ident)
    wanted=COMPLEMENTS.get(intent(product),set())
    add_ons=[]
    for candidate in others:
        if candidate['stock']<1:continue
        support=pairs[candidate['id']]
        complementary=intent(candidate) in wanted
        if support<3 and not complementary:continue
        if support<3 and candidate['price']>max(100000,product['price']*3):continue
        entry={**candidate,'suggestion_basis':'history' if support>=3 else 'complement',
               'suggestion_reason':f'Có trong {support} đơn mua chung đã hoàn tất trong 28 ngày.' if support>=3
                   else 'Gợi ý dùng cùng theo loại hàng; chưa đủ lịch sử mua chung.',
               'co_orders':support if support>=3 else None}
        score=(support if support>=3 else 0)*10000+int(complementary)*100+min(popular[candidate['id']],50)
        add_ons.append((score,entry))
    add_ons.sort(key=lambda pair:(-pair[0],pair[1]['product_name']))
    cross_sell=[entry for _,entry in add_ons[:3]]
    cross_ids={p['id'] for p in cross_sell}
    related=[]
    for candidate in others:
        same_category=candidate['category']==product['category']
        same_group=candidate['category_group']==product['category_group'] and product['category_group']!='Danh mục khác của tiệm'
        same_brand=bool(brand_key(product['brand'])) and brand_key(candidate['brand'])==brand_key(product['brand'])
        if candidate['id'] in cross_ids or not (same_category or same_group or same_brand):continue
        similarity=SequenceMatcher(None,commerce.normalize(product['product_name']),commerce.normalize(candidate['product_name'])).ratio()
        score=int(same_category)*1000+int(same_brand)*300+int(same_group)*100+similarity*50
        related.append((score,{**candidate,'suggestion_reason':'Cùng danh mục '+product['category'] if same_category else 'Cùng thương hiệu '+product['brand'] if same_brand else 'Cùng nhóm '+product['category_group']}))
    related.sort(key=lambda pair:(pair[1]['stock']<=0,-pair[0],pair[1]['product_name']))
    relevant_brands=defaultdict(list)
    for candidate in catalog['products']:
        if not brand_key(candidate['brand']):continue
        if candidate['category']==product['category'] or (candidate['category_group']==product['category_group'] and product['category_group']!='Danh mục khác của tiệm') or (brand_key(product['brand']) and brand_key(candidate['brand'])==brand_key(product['brand'])):
            relevant_brands[brand_key(candidate['brand'])].append(candidate)
    brands=[]
    for key,products in relevant_brands.items():
        current=key==brand_key(product['brand'])
        brands.append({'name':products[0]['brand'],'product_count':len(products),'available_count':sum(p['stock']>0 for p in products),
                       'current':current,'reason':'Thương hiệu của sản phẩm đang xem' if current else 'Có sản phẩm cùng nhóm hàng'})
    brands.sort(key=lambda b:(not b['current'],b['available_count']==0,-b['product_count'],b['name']))
    return {'product':product,'cross_sell':cross_sell,'related':[p for _,p in related[:6]],'brands':brands[:6],
            'server_time':catalog['server_time'],'recommendation_note':'Gợi ý từ dữ liệu cửa hàng. Mua kèm là giá từng món, không tự áp dụng giảm giá.'}

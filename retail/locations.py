"""Vietnam province/ward snapshot. Customer addresses do not expand delivery zones."""
import json
from functools import lru_cache
from pathlib import Path
from .common import fail,required


@lru_cache(maxsize=1)
def dataset():
    return json.loads((Path(__file__).resolve().parents[1]/'data'/'vietnam-addresses.json').read_text(encoding='utf-8'))


def provinces():
    data=dataset()
    return {'provinces':[{'code':p['code'],'name':p['name']} for p in data['provinces']],
            'source':data['source'],'checked_at':data['checked_at'],'ward_count':sum(len(p['wards']) for p in data['provinces'])}


def wards(province_code):
    province=next((p for p in dataset()['provinces'] if p['code']==province_code),None)
    if not province:fail('Tỉnh/thành không có trong danh sách.',404)
    return {'province':{'code':province['code'],'name':province['name']},'wards':province['wards']}


def address_snapshot(data):
    mode=data.get('address_mode','MANUAL')
    if mode=='MANUAL':
        return {'address':required(data,'address','Địa chỉ đầy đủ',500),'address_mode':mode,'province_code':None,'ward_code':None,'address_line':''}
    if mode!='SELECT':fail('Chọn địa chỉ từ danh sách hoặc tự nhập.')
    pc,wc=data.get('province_code'),data.get('ward_code')
    if isinstance(pc,bool) or isinstance(wc,bool) or not isinstance(pc,int) or not isinstance(wc,int):fail('Cần chọn tỉnh/thành và phường/xã hợp lệ.')
    province=next((p for p in dataset()['provinces'] if p['code']==pc),None)
    ward=next((w for w in province['wards'] if w['code']==wc),None) if province else None
    if not ward:fail('Phường/xã không thuộc tỉnh/thành đã chọn.')
    line=required(data,'address_line','Số nhà / căn hộ / đường',300)
    full=f"{line}, {ward['name']}, {province['name']}"
    if len(full)>500:fail('Địa chỉ đầy đủ tối đa 500 ký tự.')
    return {'address':full,'address_mode':mode,'province_code':pc,'ward_code':wc,'address_line':line}

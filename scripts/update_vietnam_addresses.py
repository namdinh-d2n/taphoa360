"""Refresh the offline province/ward snapshot. Restart the app after updating."""
import hashlib,json,urllib.request
from datetime import datetime,timezone,timedelta
from pathlib import Path

URL='https://provinces.open-api.vn/api/v2/?depth=2'
ROOT=Path(__file__).resolve().parents[1]


def main():
    with urllib.request.urlopen(URL,timeout=40) as response:raw=response.read(5*1024*1024)
    values=json.loads(raw)
    if not isinstance(values,list) or not 30<=len(values)<=64:raise ValueError('Unexpected province data; existing snapshot was preserved.')
    provinces=[];codes=set()
    for p in values:
        wards=[]
        for w in p['wards']:
            if not isinstance(w['code'],int) or w['code'] in codes:raise ValueError('Invalid or duplicate ward code.')
            codes.add(w['code']);wards.append({'code':w['code'],'name':w['name'],'type':w['division_type']})
        provinces.append({'code':p['code'],'name':p['name'],'wards':wards})
    if len(codes)<3000:raise ValueError('Incomplete ward data; existing snapshot was preserved.')
    result={'source':URL,'documentation':'https://provinces.open-api.vn/','checked_at':datetime.now(timezone(timedelta(hours=7))).date().isoformat(),
            'structure':'province-ward','source_sha256':hashlib.sha256(raw).hexdigest(),'provinces':provinces}
    target=ROOT/'data/vietnam-addresses.json';pending=target.with_suffix('.download')
    pending.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf-8');pending.replace(target)
    print('Saved',len(provinces),'provinces and',len(codes),'wards. Restart the app to use the new snapshot.')


if __name__=='__main__':main()

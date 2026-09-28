import sys,json,struct,re,collections
from pathlib import Path
from port_mltd_stage import read_cstring,mltd_lookup,localization_hash
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'work/poc/full_english_20260906'

def parse_logo(data):
    assert data[:4]==b'LOGO' and int.from_bytes(data[4:8],'big')==len(data)
    n,t,nn,base,m,mt=struct.unpack_from('>6I',data,0x40)
    assert n==nn and t+n*4<=mt and mt+m*4<=base
    tables=[]
    for count,table in [(n,t),(m-1,mt)]:
        offsets=struct.unpack_from('>'+str(count)+'I',data,table)
        strings=[read_cstring(data,base+x) for x in offsets]
        assert all(base+x+len(s.encode('utf8'))<len(data) for x,s in zip(offsets,strings))
        tables.append(dict(count=count,table=table,offsets=offsets,strings=strings))
    assert tables[0]['offsets'][0]==0
    return base,tables

def probe():
    lookup=collections.defaultdict(list)
    for f in (ROOT/'work/extracted/ps4_lang/Dat/MultiLanguage/@En/MapLogic').glob('*.mltd'):
        for key,text in mltd_lookup(f.read_bytes()).items():lookup[key].append((f.stem,text.text))
    reports=[]
    for f in sorted((ROOT/'work/extracted/ps3_logic/Dat/logic').glob('scr*.bin')):
        d=f.read_bytes();base,tables=parse_logo(d);rows=[]
        for ti,table in enumerate(tables):
            for i,t in enumerate(table['strings']):
                if re.search('[ぁ-んァ-ヶ一-鿿]',t):rows.append(dict(table=ti,index=i,text=t,english=lookup.get(localization_hash(t),[])))
        reports.append(dict(file=f.name,size=len(d),base=base,tables=[dict(count=x['count'],table=x['table']) for x in tables],header=d[:128].hex(),rows=rows))
    (OUT/'map_script_probe.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(files=len(reports),mapped=sum(bool(x['english']) for r in reports for x in r['rows']),unmapped=sum(not x['english'] for r in reports for x in r['rows']),sample=[x for r in reports for x in r['rows'] if not x['english'] and not x['text'].startswith('[')][:12])))

if __name__=='__main__':probe()

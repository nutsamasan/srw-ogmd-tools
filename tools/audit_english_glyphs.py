import json,struct,collections,unicodedata
from pathlib import Path
from ogmd_text_formats import parse_ldbi_table,read_cstring,parse_fixed
from port_mltd_roll import parse_csb
from port_battle_corpus import parse_bmd
from probe_map_scripts import parse_logo
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'work/poc/full_english_20260906'
FONT=(ROOT/'work/poc/text_layout_20260905/ps3_font_original.bin').read_bytes()

def glyph_missing(c):
    if c in '\r\n\t':return False
    n=ord(c)
    if n>65535:return True
    page=struct.unpack_from('>I',FONT,0x54+(n>>8)*4)[0]
    return not page or FONT[page+(n&255)*4:page+(n&255)*4+4]==bytes(4)

def strings(path):
    data=path.read_bytes()
    if data[:4]==b'LDBI':return [read_cstring(data,o) for o in parse_ldbi_table(data)[2]]
    if data[:4]==b'FIXH':return parse_fixed(data).strings
    if data[:4]==b'CSB ':return [s for r in parse_csb(data)[2] for s in r['arguments']]
    if data[:4]==b'LOGO':return [s for t in parse_logo(data)[1] for s in t['strings']]
    if data[:2]==b'\x03\0' and path.suffix=='.bmd':return [s for s in parse_bmd(data)[3] if s]
    if path.suffix=='.wtd':return [r['english'] for r in json.loads((OUT/'wtd_report.json').read_text(encoding='utf8'))['rows'] if r['english']]
    if data[:4]==b'MPTI':return [data[12+i*84:12+i*84+64].split(b'\0')[0].decode('utf8').split('@')[0] for i in range(1024)]
    return []

def main():
    result={}
    for folder in ['story','fixed','ui','battle']:
        for p in (OUT/folder).rglob('*'):
            if not p.is_file() or p.suffix not in ('.dat','.csb','.bin','.bmd','.wtd','.mti') or p.name=='WeaponData_Temp.dat':continue
            for s in strings(p):
                for c in set(s):
                    if glyph_missing(c):
                        item=result.setdefault(c,dict(name=unicodedata.name(c,'unknown'),count=0,files=set(),examples=[]))
                        item['count']+=s.count(c);item['files'].add(str(p.relative_to(OUT)))
                        if len(item['examples'])<3:item['examples'].append(s)
    for item in result.values():item['files']=sorted(item['files'])
    (OUT/'unsupported_glyphs.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result))

if __name__=='__main__':main()

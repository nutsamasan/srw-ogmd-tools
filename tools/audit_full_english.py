"""Audit the built full corpus before archive packaging."""
import sys,json,re,struct,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'work/poc/full_english_20260906'
sys.path.insert(0,str(ROOT/'work/analysis_pydeps'))
from ogmd_text_formats import dialogue_grid,parse_fixed
from verify_ogmd_line_measurement import native_width,NATIVE_FONT
from port_mltd_stage import parse_ldbi_table,read_cstring

def build():
    rows=[];overflow=[];bad=[];missing=collections.Counter();maxlines=collections.Counter()
    for path in sorted((OUT/'story').glob('ls*.bin')):
        data=path.read_bytes();grid=dialogue_grid(data)
        count,_,offsets=parse_ldbi_table(data)
        for p,index,_,text in grid:
            assert '\n' not in text and '\r' not in text
            if re.search('[ぁ-んァ-ヶ一-鿿]',text):bad.append(dict(file=path.name,record=p,text=text))
            clean=re.sub(r'</?C(?:=[^>]*)?>','',text).replace('<','').replace('>','')
            lines=clean.split('@');maxlines[len(lines)]+=1
            widths=[native_width(line,24) for line in lines]
            if max(widths,default=0)>768 or len(lines)>3:overflow.append(dict(file=path.name,record=p,text=text,widths=widths,lines=len(lines)))
            for c in clean.replace('@',''):
                code=ord(c)
                if code>65535 or not struct.unpack_from('>I',NATIVE_FONT,0x54+(code>>8)*4)[0]:missing[c]+=1
            nameindex=struct.unpack_from('>I',data,p+8)[0];name=read_cstring(data,offsets[nameindex])
            assert not re.search('[ぁ-んァ-ヶ一-鿿]',name),(path.name,p,name)
        rows.append(dict(file=path.name,dialogues=len(grid)))
    fixed=[]
    for path in sorted((OUT/'fixed').glob('*.dat')):
        if path.name=='WeaponData_Temp.dat':continue
        data=parse_fixed(path.read_bytes())
        fixed.append(dict(file=path.name,records=len(data.records),strings=len(data.strings),japanese_pool_strings=sum(bool(re.search('[ぁ-んァ-ヶ一-鿿]',t)) for t in data.strings)))
    report=dict(stages=rows,total_dialogue_commands=sum(r['dialogues'] for r in rows),line_counts=dict(maxlines),layout_review=overflow,japanese_dialogue=bad,missing_font_pages=dict(missing),fixed=fixed)
    (OUT/'full_text_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(stages=len(rows),dialogues=report['total_dialogue_commands'],line_counts=dict(maxlines),layout_review=len(overflow),missing_font_pages=dict(missing),japanese_dialogue=len(bad),fixed_files=len(fixed))))
    assert len(rows)==76 and not bad

if __name__=='__main__':build()

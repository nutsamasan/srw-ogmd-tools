"""Read-only source inventory for battle layout and additional editable text."""
from pathlib import Path
import hashlib,json,re,shutil,struct,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from core import atomic_json,Corpus
from fixed_data import parse_fixed
from vendor.psarc import Psarc


def name_hash(raw):
    value=0
    for char in raw:value=(value*137+char)&0xffffffff
    return (value+value//0xffffffff)&0xffffffff


def main():
    out=ROOT/'work/poc/editor_v39_20260914';out.mkdir(exist_ok=False)
    for folder in ('script_editor','full_patcher'):
        dest=out/'backups'/folder;dest.mkdir(parents=True)
        for file in (ROOT/folder).iterdir():
            if file.is_file() and file.suffix in ('.py','.ps1','.md','.exe'):shutil.copy2(file,dest/file.name)
    project=ROOT/'script_editor/edits/project.json';shutil.copy2(project,out/'backups/project.json')
    atomic_json(out/'baseline.json',dict(project_sha256=hashlib.sha256(project.read_bytes()).hexdigest(),project_mtime_ns=project.stat().st_mtime_ns))
    data=(ROOT/'work/poc/backlog_margin_20260913/windowdataMain.wtd').read_bytes()
    elf=(ROOT/'work/poc/text_layout_20260905/EBOOT.elf').read_bytes()
    labels={}
    for match in re.finditer(rb'[A-Za-z_][A-Za-z_0-9]{2,95}\0',elf):
        raw=match[0][:-1];labels.setdefault(name_hash(raw),set()).add(raw.decode())
    windows=[];at=0x718
    for i in range(403):
        size,h=struct.unpack_from('>II',data,at)
        windows.append(dict(index=i,offset=at,size=size,hash=hex(h),names=sorted(labels.get(h,[]))))
        at+=size
    atomic_json(out/'windows.json',windows)
    print('Battle/dialogue window candidates:')
    print(json.dumps([w for w in windows if any(re.search('battle|talk|message|serif',n,re.I) for n in w['names'])],indent=2))
    arc=Psarc(ROOT/'work/poc/full_release_20260910_v12/Logic.psarc')
    tables={}
    for table in ('SpiritData','WeaponData','WeaponData_Temp'):
        raw=arc._read_file(next(e for e in arc.entries if e.name=='/Dat/FixedData/'+table+'.dat'))
        fixed=parse_fixed(raw)
        tables[table]=dict(records=len(fixed.records),stride=len(fixed.records[0]),logical=len(fixed.logical_indices),strings=len(fixed.strings),sample=fixed.strings[:12])
    print(json.dumps(tables,ensure_ascii=False,indent=2));atomic_json(out/'tables.json',tables)
    corpus=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
    matching=[]
    for c in corpus.collections:
        for r in corpus.load(c['key'])[0]['rows']:
            if 'where it belongs' in (r.get('en') or ''):matching.append(dict(key=c['key'],row=r))
    print(json.dumps(matching,ensure_ascii=False,indent=2));atomic_json(out/'screenshot_rows.json',matching)


if __name__=='__main__':main()

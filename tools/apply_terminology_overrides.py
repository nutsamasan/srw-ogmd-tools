"""Apply user-approved terminology to parsed build text, preserving native control data."""
import argparse,json,re,shutil,struct
from collections import Counter
from pathlib import Path
from audit_english_glyphs import OUT,ROOT,strings
from ogmd_text_formats import parse_ldbi_table,read_cstring,rebuild_ldbi_pool,parse_fixed,rebuild_fixed
from port_battle_corpus import parse_bmd
from port_mltd_stage import sha256

RULES=ROOT/'reports/terminology_overrides.json'
REVISION=ROOT/'work/poc/terminology_irm_20260907'


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    rules=json.loads(RULES.read_text(encoding='utf8'))['rules']
    replacements={r['from'].lower():r['to'] for r in rules}
    pattern=re.compile(r'(?<![A-Za-z])(?:'+ '|'.join(re.escape(r['from']) for r in rules)+r')(?![A-Za-z])',re.I)
    counts=Counter()
    def replace(text):
        def sub(m):
            old=m.group();new=replacements[old.lower()]
            if old.isupper():return new.upper()
            if old.islower():return new.lower()
            return new
        return pattern.sub(sub,text)
    manifest_path=OUT/'build_manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf8'))
    changes=[];pending=[]
    for item in manifest['overrides']:
        path=Path(item['file']);before=strings(path)
        if not any(pattern.search(t) for t in before):continue
        source=path.read_bytes();assert sha256(source)==item['sha256']
        after=[replace(t) for t in before]
        for t in before:counts.update(m.group() for m in pattern.finditer(t))
        if source[:4]==b'LDBI':
            texts=[read_cstring(source,o) for o in parse_ldbi_table(source)[2]]
            result,validation=rebuild_ldbi_pool(source,{i:replace(t) for i,t in enumerate(texts) if replace(t)!=t})
            assert validation['structural_bytes_preserved'] and validation['all_pointers_verified']
        elif source[:4]==b'FIXH':
            data=parse_fixed(source)
            result=rebuild_fixed(data,{i:replace(t) for i,t in enumerate(data.strings) if replace(t)!=t})
            parsed=parse_fixed(result)
            assert parsed.records==data.records and parsed.logical_indices==data.logical_indices
        elif path.suffix=='.bmd':
            sizes,start,pool,texts=parse_bmd(source)
            body=bytearray(source[:pool]);payload=bytearray();offsets={}
            for k,t in enumerate(texts):
                if t is None:continue
                t=replace(t)
                if t not in offsets:
                    offsets[t]=len(payload);payload.extend(t.encode('utf8')+b'\0')
                struct.pack_into('>I',body,start+k*20+16,offsets[t])
            result=bytes(body+payload)
            assert parse_bmd(result)[3]==[replace(t) if t is not None else None for t in texts]
            assert result[:start]==source[:start]
            assert all(result[start+k*20:start+k*20+16]==source[start+k*20:start+k*20+16] for k in range(sizes[2]))
        else:raise ValueError('Matching text needs a supported structured writer: '+str(path))
        changed=[dict(index=i,before=a,after=b) for i,(a,b) in enumerate(zip(before,after)) if a!=b]
        changes.append(dict(archive=item['archive'],entry=item['entry'],file=str(path),
                            before_sha256=sha256(source),after_sha256=sha256(result),strings=changed))
        pending.append((path,source,result,after))
    assert replace("Irum's Irmgult Irmkult IRUM OtherIrum") == "Irm's Irmgard Irmgard IRM OtherIrum"
    report=dict(applied=args.apply,counts=dict(counts),files=len(changes),changed_strings=sum(len(r['strings']) for r in changes),
                archives=sorted({r['archive'] for r in changes}),changes=changes)
    REVISION.mkdir(parents=True,exist_ok=True)
    if args.apply and pending:
        assert not (REVISION/'changes.json').exists(),'Revision already recorded; inspect before repeating.'
        backup=REVISION/'before';backup.mkdir()
        shutil.copy2(manifest_path,backup/'build_manifest.json')
        for archive in report['archives']:
            shutil.copy2(OUT/'archives'/(archive+'.verification.json'),backup/(archive+'.verification.json'))
        for path,source,result,after in pending:
            original=backup/'payloads'/path.relative_to(OUT);original.parent.mkdir(parents=True,exist_ok=True)
            original.write_bytes(source)
        try:
            for path,source,result,after in pending:
                assert path.read_bytes()==source
                path.write_bytes(result);assert strings(path)==after
            remaining=[]
            for item in manifest['overrides']:
                for t in strings(Path(item['file'])):
                    if pattern.search(t):remaining.append(dict(entry=item['entry'],text=t))
            assert not remaining
            report.update(remaining_old_names=0,all_nontext_fields_preserved=True)
        except Exception:
            for path,source,_,_ in pending:path.write_bytes(source)
            raise
        (REVISION/'changes.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    else:(REVISION/'preview.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='changes'},ensure_ascii=True))


if __name__=='__main__':main()

"""Add a versioned menu/glossary extension without rewriting the script corpus."""
from pathlib import Path
import json, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from core import atomic_json, sha
from fixed_data import SCHEMAS,parse_fixed,structure_hash
from vendor.psarc import Psarc


def main():
    corpus=ROOT/'script_export/OGMD_EN_JP_20260908'
    source=ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc'
    english=ROOT/'work/poc/full_release_20260909/Logic.psarc'
    arcs=[Psarc(source),Psarc(english)];index=[]
    info={'PilotData':('Pilot_names','Pilot names','Pilot names'),
          'UnitData':('Mech_names','Mech names','Mech names'),
          'KeyWordData':('Glossary','Glossary terms and definitions','Glossary')}
    for table,(folder,title,group) in info.items():
        entry='/Dat/FixedData/'+table+'.dat'
        raw=[arc._read_file(next(e for e in arc.entries if e.name==entry)) for arc in arcs]
        jp,en=map(parse_fixed,raw)
        fingerprint=structure_hash(jp,table)
        assert structure_hash(en,table)==fingerprint,table
        first={}
        for logical,physical in enumerate(jp.logical_indices):
            if physical!=0xffffffff:first.setdefault(physical,logical)
        rows=[]
        for physical,logical in sorted(first.items()):
            def value(f,field):
                o,w=SCHEMAS[table][1][field]
                return f.strings[int.from_bytes(f.records[physical][o:o+w],'big')]
            main_field='short_name' if table=='PilotData' else 'name' if table=='UnitData' else 'term'
            for field in SCHEMAS[table][1]:
                label=field.replace('_',' ').title()
                rows.append(dict(id=f'{table}_{field}:{logical:04d}',en=value(en,field),jp=value(jp,field),
                    block=label,label_en=value(en,main_field),label_jp=value(jp,main_field),
                    fixed_table=table,fixed_field=field,fixed_record=physical,fixed_logical=logical,
                    fixed_structure_sha256=fingerprint))
        key='06_Game_data/'+folder
        doc=dict(metadata=dict(title_en=title,script_id=table,native_entry=entry.lstrip('/'),
                description='English patch baseline and original Japanese. Names and glossary definitions share the edit project.',
                native_format='FIXH',source_jp_sha256=sha(raw[0]),source_en_sha256=sha(raw[1])),rows=rows)
        path=corpus/key/'script.json'
        if path.exists():assert json.loads(path.read_text(encoding='utf8'))==doc,'Immutable extension already differs'
        else:atomic_json(path,doc)
        for label,languages in [('EN',['en']),('JP',['jp']),('Bilingual',['en','jp'])]:
            text=[title,'Edited script export','']
            for row in rows:
                for lang in languages:text += [f'[{row["id"]}] {lang.upper()} ',row[lang],'']
            dest=corpus/key/(label+'.txt')
            if not dest.exists():dest.write_text('\n'.join(text),encoding='utf-8-sig')
        index.append(dict(folder=key,title_en=title,group=group,sha256=sha(path.read_bytes()),records=len(first),fields=len(rows)))
    manifest=dict(version=1,collections=index,source_jp=str(source),source_en=str(english))
    target=corpus/'data/fixed_index.json'
    if target.exists():assert json.loads(target.read_text(encoding='utf8'))==manifest
    else:atomic_json(target,manifest)
    print(json.dumps(index))

if __name__=='__main__':main()

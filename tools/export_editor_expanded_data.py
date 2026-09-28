"""Add immutable location, Spirit Command and weapon collections to the editor."""
from pathlib import Path
import json,struct,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from core import Corpus,atomic_json,sha
from fixed_data import SCHEMAS,parse_fixed,structure_hash
from native_formats import parse_ldbi_table,read_cstring,location_signature,LDBI_TEXT_FIELDS
from vendor.psarc import Psarc


def main():
    corpus=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
    sources=[ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc',ROOT/'work/poc/full_release_20260910_v12/Logic.psarc']
    arcs=[Psarc(p) for p in sources];indices=[{e.name:e for e in a.entries} for a in arcs]
    def read(entry):return [a._read_file(index[entry]) for a,index in zip(arcs,indices)]
    index=[]
    def save(key,title,group,doc,records):
        path=corpus.root/key/'script.json'
        if path.exists():assert json.loads(path.read_text(encoding='utf8'))==doc,'Immutable extension differs'
        else:atomic_json(path,doc)
        for label,languages in [('EN',['en']),('JP',['jp']),('Bilingual',['en','jp'])]:
            text=[title,'Edited script export','']
            for row in doc['rows']:
                for lang in languages:text.extend([f'[{row["id"]}] {lang.upper()} ',row[lang],''])
            dest=path.with_name(label+'.txt')
            if not dest.exists():dest.write_text('\n'.join(text),encoding='utf-8-sig')
        index.append(dict(folder=key,title_en=title,group=group,sha256=sha(path.read_bytes()),records=records,fields=len(doc['rows'])))
    units=[parse_fixed(raw) for raw in read('/Dat/FixedData/UnitData.dat')]
    for table,folder,group in [('SpiritData','Spirit_commands','Spirit Commands'),('WeaponData','Weapon_names','Weapon names')]:
        entry='/Dat/FixedData/'+table+'.dat';raw=read(entry);jp,en=map(parse_fixed,raw)
        fingerprint=structure_hash(jp,table);assert structure_hash(en,table)==fingerprint
        first={}
        for logical,physical in enumerate(jp.logical_indices):
            if physical!=0xffffffff:first.setdefault(physical,logical)
        rows=[]
        for physical,logical in sorted(first.items()):
            def value(f,field):
                o,w=SCHEMAS[table][1][field]
                return f.strings[int.from_bytes(f.records[physical][o:o+w],'big')]
            extra={}
            if table=='WeaponData':
                unit,slot=struct.unpack_from('>HB',jp.records[physical]);extra.update(weapon_unit=unit,weapon_slot=slot)
                for lang,f in zip(('jp','en'),units):
                    if unit==0:owner='Replacement weapon' if lang=='en' else '換装武器'
                    elif unit<len(f.logical_indices) and f.logical_indices[unit]!=0xffffffff:
                        record=f.records[f.logical_indices[unit]];owner=f.strings[int.from_bytes(record[2:4],'big')]
                    else:owner=f'Unit ID {unit}'
                    extra['weapon_owner_'+lang]=owner
            for field in SCHEMAS[table][1]:
                rows.append(dict(id=f'{table}_{field}:{logical:04d}',en=value(en,field),jp=value(jp,field),
                    block=(f'Unit {extra["weapon_unit"]:03d} · slot {extra["weapon_slot"]}' if extra else field.title()),
                    label_en=value(en,'name'),label_jp=value(jp,'name'),fixed_table=table,fixed_field=field,
                    fixed_record=physical,fixed_logical=logical,fixed_structure_sha256=fingerprint,**extra))
        doc=dict(metadata=dict(title_en=group,script_id=table,native_entry=entry[1:],native_format='FIXH',
            description='English release baseline and original Japanese. Text fields only; gameplay records are preserved.',
            source_jp_sha256=sha(raw[0]),source_en_sha256=sha(raw[1])),rows=rows)
        save('06_Game_data/'+folder,group,group,doc,len(first))
    rows=[];source_inventory=[]
    for c in corpus.collections:
        document=corpus.load(c['key'])[0];entry=document['metadata'].get('native_entry','')
        if document['metadata'].get('native_format')!='LDBI' and not entry.startswith('Dat/logic/'):continue
        if '/'+entry not in indices[0]:continue
        raw=read('/'+entry)
        if raw[0][:4]!=b'LDBI':continue
        offsets=[parse_ldbi_table(r)[2] for r in raw];number,start=struct.unpack_from('>II',raw[0],0x20)
        assert struct.unpack_from('>II',raw[1],0x20)==(number,start)
        prefix=document['metadata']['script_id'];used=0
        for command in range(number):
            p=start+command*196;opcode=struct.unpack_from('>I',raw[0],p)[0]
            if opcode not in (9,20):continue
            for field,(expected,offset) in LDBI_TEXT_FIELDS.items():
                if opcode!=expected:continue
                ids=[struct.unpack_from('>I',r,p+offset)[0] for r in raw]
                if ids[0]==0xffffffff:assert ids[1]==0xffffffff;continue
                assert all(i<len(o) for i,o in zip(ids,offsets)),(prefix,command,field,ids)
                texts=[read_cstring(r,o[i]) for r,o,i in zip(raw,offsets,ids)]
                # Empty labels clear the banner and remain editable with stable IDs.
                signature=location_signature(raw[0][p:p+196]);assert signature==location_signature(raw[1][p:p+196])
                rows.append(dict(id=f'Location_{prefix}_{field}:{command:04d}',jp=texts[0],en=texts[1],
                    block=f'{prefix} · {field.replace("_"," ")}',label_en=c['title'],label_jp=c['title'],
                    native_entry=entry,location_field=field,command_index=command,command_offset=p,
                    location_metadata_hex=signature,source_collection=c['key']))
                used+=1
        if used:source_inventory.append(dict(entry=entry,jp_sha256=sha(raw[0]),en_sha256=sha(raw[1]),fields=used))
    doc=dict(metadata=dict(title_en='Location and scene banners',script_id='LocationBanners',native_format='LDBI-location',
        description='Story location headers, map locations and scene labels. Search by place or stage; repeated uses are separate editable events.',
        sources=source_inventory),rows=rows)
    save('07_Location_banners/Locations','Location and scene banners','Location banners',doc,len(rows))
    manifest=dict(version=1,collections=index,source_jp=str(sources[0]),source_en=str(sources[1]))
    target=corpus.root/'data/expanded_index.json'
    if target.exists():assert json.loads(target.read_text(encoding='utf8'))==manifest
    else:atomic_json(target,manifest)
    print(json.dumps(index,indent=2))


if __name__=='__main__':main()

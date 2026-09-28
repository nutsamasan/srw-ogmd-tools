"""Real native archives, isolated installations and ISO/full-patcher correction paths."""
from pathlib import Path
import sys,json,shutil
from core import Corpus,EditProject,NativeMetrics,atomic_json
from patcher import prepare_patch,install_patch
from iso_patcher import prepare_iso_patch
from full_patch import prepare_full_patch
from archive_patch import digest
from edit_bundle import export_bundle
from fixed_data import parse_fixed,SCHEMAS
from vendor import sdat
from vendor.psarc import Psarc

ROOT=Path(__file__).resolve().parents[1]

def main():
    out=Path(sys.argv[1]).resolve()
    if out.exists():raise ValueError('Choose a fresh QA directory.')
    out.mkdir(parents=True);corpus=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
    project=EditProject(corpus,out/'project.json');metrics=NativeMetrics(ROOT/'script_editor/assets/font.bin')
    choices=[('Pilot_names','given_name','Irmgard','QA Irmgard'),('Mech_names','name','Grungust Kai','QA Grungust'),('Glossary','definition_1',None,'QA glossary line one.\nSecond line.')]
    for folder,field,value,replacement in choices:
        key='06_Game_data/'+folder;rows=corpus.load(key)[0]['rows']
        row=next(r for r in rows if r['fixed_field']==field and (r['en']==value if value else r['fixed_record']==45))
        project.set(key,row,'en',replacement)
    project.save();export_bundle(project,out/'patch_edits.json')
    source=ROOT/'work/ps3_disc/PS3_GAME';target=out/'fixture/PS3_GAME/USRDIR/PSARC';target.mkdir(parents=True)
    shutil.copy2(source/'PARAM.SFO',target.parent.parent/'PARAM.SFO');shutil.copy2(source/'USRDIR/PSARC/Logic.psarc.sdat',target/'Logic.psarc.sdat')
    original=digest(target/'Logic.psarc.sdat')
    manifest=prepare_patch(project,'en',[target],out/'folder_patch',metrics,progress=print)
    install_patch(manifest,closed_check=lambda:None);installed=digest(target/'Logic.psarc.sdat')
    assert installed!=original
    install_patch(manifest,restore=True,closed_check=lambda:None);assert digest(target/'Logic.psarc.sdat')==original
    iso=ROOT/'PS3/Super Robot Taisen OG - The Moon Dwellers (Japan).iso'
    iso_manifest=prepare_iso_patch(project,'en',iso,out/'iso_patch',metrics,progress=print)
    full=prepare_full_patch(ROOT/'full_patcher/data_v12',source.parent,out/'full_patch',print,edits=out/'patch_edits.json')
    doc=json.loads(full.read_text(encoding='utf8'));assert len(doc['editor_corrections_review'])==3
    encrypted=full.parent/'native/Logic.psarc.sdat';plain=out/'full_logic.psarc';sdat.decrypt(encrypted,plain,verbose=False)
    arc=Psarc(plain)
    for key,collection in project.data['collections'].items():
        rows={r['id']:r for r in corpus.load(key)[0]['rows']}
        for rid,edits in collection['rows'].items():
            row=rows[rid];table=row['fixed_table'];f=parse_fixed(arc._read_file(next(e for e in arc.entries if e.name=='/Dat/FixedData/'+table+'.dat')))
            offset,width=SCHEMAS[table][1][row['fixed_field']]
            assert f.strings[int.from_bytes(f.records[row['fixed_record']][offset:offset+width],'big')]==edits['en']
    atomic_json(out/'verification.json',dict(status='passed',fixed_formats=3,folder_install_restore=True,
        iso_build=str(iso_manifest),full_build=str(full),portable_corrections_verified=True,real_game_files_modified=False))
    print('PASSED: fixed-data folder, ISO and vanilla full-patcher integration.')

if __name__=='__main__':main()

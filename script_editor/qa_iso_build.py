"""Real ISO integration check using a separate imported QA edit project."""
import argparse
import json
import tempfile
from pathlib import Path
from core import Corpus,EditProject,NativeMetrics,atomic_json
from script_import import ScriptImporter
from iso_patcher import prepare_iso_patch,write_patched_iso
from iso_image import DiscImage
from archive_patch import digest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args()
    home=Path(__file__).resolve().parent;root=home.parent;corpus=Corpus(root/'script_export/OGMD_EN_JP_20260908')
    source=root/'PS3/Super Robot Taisen OG - The Moon Dwellers (Japan).iso'
    original_user=digest(home/'edits/project.json');args.output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory() as tmp:
        project=EditProject(corpus,Path(tmp)/'input.json');selected=set()
        for c in corpus.collections:
            doc,_=corpus.load(c['key']);entry=doc['metadata'].get('native_entry','')
            kind='story' if doc['metadata'].get('script_id')=='S000' else 'battle' if '/Battle/' in entry else 'recap' if '/Archive/' in entry else None
            if kind is None or kind in selected:continue
            row=next((r for r in doc['rows'] if not r.get('null_text') and r.get('en')),None)
            if row is None:continue
            project.set(c['key'],row,'en','ISO import QA.');selected.add(kind)
        assert len(selected)==3;project.save();project.export(Path(tmp)/'export')
        imported=EditProject(corpus,Path(tmp)/'imported.json');result=ScriptImporter(imported).preview(Path(tmp)/'export')
        imported.apply_replacements(result['plan']);assert imported.data==project.data
        manifest=prepare_iso_patch(imported,'en',source,args.output/'build',NativeMetrics(home/'assets/font.bin'),True,lambda s:print(s,flush=True))
        result=write_patched_iso(manifest,args.output/'OGMD_ISO_QA.iso',lambda s:print(s,flush=True))
    assert original_user==digest(home/'edits/project.json')
    with DiscImage(source) as iso:split=len(iso.file('/PS3_GAME/USRDIR/PSARC/Battle.psarc.sdat').extents)
    result.update(import_round_trip=True,multi_extent_battle_parts=split,user_edits_unchanged=True,game_boot_tested=False)
    atomic_json(home/'qa/iso_v3_verification.json',result);print(json.dumps(result,ensure_ascii=True),flush=True)

if __name__=='__main__':main()

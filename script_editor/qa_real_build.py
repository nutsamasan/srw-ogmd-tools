"""Build a real native patch in QA storage without installing or editing user data."""
import argparse,json,tempfile
from pathlib import Path
from core import Corpus,EditProject,NativeMetrics,atomic_json
from patcher import prepare_patch,default_targets
from archive_patch import digest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args()
    home=Path(__file__).resolve().parent;corpus=Corpus(home.parent/'script_export/OGMD_EN_JP_20260908')
    targets=default_targets(corpus);before={str(t/(a+'.psarc.sdat')):digest(t/(a+'.psarc.sdat')) for t in targets for a in ('Logic','Common','Battle')}
    with tempfile.TemporaryDirectory() as tmp:
        project=EditProject(corpus,Path(tmp)/'project.json');selected=set()
        for c in corpus.collections:
            doc,_=corpus.load(c['key']);meta=doc['metadata'];entry=meta.get('native_entry','');sid=meta.get('script_id')
            kind='defeat' if sid=='DEAD' else 'story' if sid=='S000' else 'map' if '/scr' in entry else 'battle' if '/Battle/' in entry else 'recap' if '/Archive/' in entry else 'narration' if '/Roll/' in entry else None
            if kind is None or kind in selected:continue
            row=next((r for r in doc['rows'] if not r.get('null_text') and r.get('en')),None)
            if row is None:continue
            project.set(c['key'],row,'en',row['en']+' [QA]')
            if kind=='story':project.set(c['key'],row,'speaker_en','QA Speaker')
            selected.add(kind)
        assert len(selected)==6;project.save()
        output=prepare_patch(project,'en',targets,args.output,NativeMetrics(home/'assets/font.bin'),True,lambda s:print(s,flush=True))
    after={p:digest(p) for p in before};assert before==after
    doc=json.loads(output.read_text(encoding='utf8'))
    result=dict(status='passed',manifest=str(output),categories=sorted(selected),archives=len(doc['archives']),native_fields=len(doc['review']),all_active_game_files_unchanged=True,active_hashes=after)
    atomic_json(home/'qa/real_build_check.json',result);print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()

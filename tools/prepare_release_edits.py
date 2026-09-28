"""Snapshot accepted edits for packaging; never write the active editor project."""
from pathlib import Path
import sys,copy,json,re
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'script_editor'))
from core import Corpus,EditProject,atomic_json,sha

def main():
    corpus=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908');source=ROOT/'script_editor/edits/project.json'
    before=sha(source.read_bytes());out=ROOT/'work/poc/release_edits_20260910_v12';out.mkdir(exist_ok=True)
    path=out/'project.json'
    if path.exists():raise ValueError('Release snapshot already exists; inspect before replacing.')
    p=EditProject(corpus,source);p.path=path;p.file_hash=None;p.dirty=True;excluded=[];rules={}
    for key,item in list(p.data['collections'].items()):
        rows={r['id']:r for r in corpus.load(key)[0]['rows']}
        for rid,changes in list(item['rows'].items()):
            value=changes.get('speaker_en')
            if value and value.endswith(' TEST'):
                excluded.append(dict(key=key,id=rid,from_text=value,to_text=value[:-5]));p.set(key,rows[rid],'speaker_en',value[:-5])
            elif value and value!=rows[rid].get('speaker_en'):
                rules.setdefault(rows[rid]['speaker_en'],set()).add(value)
    rules={k:next(iter(v)) for k,v in rules.items() if len(v)==1}
    corrections=EditProject(corpus,ROOT/'script_editor/imports/menu_glossary_corrections_20260910.json')
    inventory=[]
    for key in corpus.fixed_hashes:
        for row in corpus.load(key)[0]['rows']:
            old=row['en'];new=old
            for a,b in rules.items():new=re.sub(r'(?<![A-Za-z])'+re.escape(a)+r'(?![A-Za-z])',lambda m:b,new)
            if new!=old:
                p.set(key,row,'en',new);corrections.set(key,row,'en',new)
                inventory.append(dict(id=row['id'],before=old,after=new))
    p.save();corrections.save()
    assert sha(source.read_bytes())==before
    atomic_json(out/'review.json',dict(source_project_sha256=before,edited_rows=p.count(),excluded_test_labels=excluded,
        confirmed_speaker_rules=rules,menu_glossary_changes=inventory,active_project_preserved=True))
    print(json.dumps(dict(project=str(path),edited_rows=p.count(),excluded_test_labels=len(excluded),menu_glossary_fields=len(inventory),rules=rules)))

if __name__=='__main__':main()

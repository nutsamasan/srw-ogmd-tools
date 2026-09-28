"""Build a portable vanilla-to-English release from verified assets and saved edits."""
from pathlib import Path
import argparse,hashlib,json,re,shutil,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'script_editor'))
from core import Corpus,EditProject,NativeMetrics,atomic_json
from patcher import collect_changes,compile_entry
from archive_patch import repack,digest
from vendor.psarc import Psarc
from vendor import sdat
from release_delta import build_recipe,apply_recipe,sdat_metadata
from backlog_layout import ENTRY as BACKLOG_ENTRY, FEATURE as BACKLOG_FEATURE, patch_backlog
from ogmd_text_formats import parse_fixed,rebuild_fixed

BASE=ROOT/'work/poc/full_english_20260906'
STAGE=ROOT/'work/poc/full_release_20260909'
DATA=ROOT/'full_patcher/data'


def main():
    global STAGE,DATA
    parser=argparse.ArgumentParser();parser.add_argument('--stage',type=Path,default=STAGE);parser.add_argument('--data',type=Path,default=DATA)
    parser.add_argument('--project',type=Path,default=ROOT/'script_editor/edits/project.json');args=parser.parse_args()
    STAGE=args.stage.resolve();DATA=args.data.resolve()
    DATA.mkdir(parents=True,exist_ok=True);STAGE.mkdir(parents=True,exist_ok=True)
    baseline=json.loads((BASE/'build_manifest.json').read_text(encoding='utf8'))
    corpus=Corpus(ROOT/'script_export/OGMD_EN_JP_20260908')
    project=EditProject(corpus,args.project)
    project_hash=digest(project.path);groups=collect_changes(project,'en')
    metrics=NativeMetrics(ROOT/'script_editor/assets/font.bin')
    rules=json.loads((ROOT/'reports/terminology_overrides.json').read_text(encoding='utf8'))['rules']
    words={r['from'].lower():r['to'] for r in rules}
    pattern=re.compile(r'(?<![A-Za-z])(?:'+'|'.join(map(re.escape,words))+r')(?![A-Za-z])',re.I)
    def replace(text):
        def sub(m):
            value=words[m[0].lower()]
            return value.upper() if m[0].isupper() else value.lower() if m[0].islower() else value
        return pattern.sub(sub,text)
    report=dict(version=1,release='OGMD Full English 1.4',title_id='BLJS10335',game_version='01.00',corpus_identity=corpus.identity,
                status='building',edited_rows=project.count(),project_sha256=project_hash,
                baseline_overrides=len(baseline['overrides']),archives=[],review=[],fixed_terminology=[],
                eboot_sha256='38ac2f2cac4d2ce76423bb800ea46c7d8c80bad874298dfd11954936685add09',
                features=['Complete story, speakers, locations and battle dialogue','English menus, pilot/mech data, objectives and sort order',
                          'English images, tutorials, encyclopedias and rolling recaps','Saved script and menu/glossary corrections; test labels excluded',
                          'Optional exported editor corrections when building from a vanilla game',
                          'Confirmed line breaks, proportional spacing and apostrophe correction','RPCS3 startup settings and installed-data icon synchronization',BACKLOG_FEATURE],
                backlog_margin_width=720,backlog_user_confirmed=True,
                runtime_note='VWF and apostrophe spacing are embedded in EBOOT. No font YAML is required. RPCS3 only; console support is not included.')
    for meta in baseline['archives']:
        name=meta['name'];print(name+': checking accepted full-English build',flush=True)
        base=BASE/'archives'/(name+'.psarc');vr=json.loads((BASE/'archives'/(name+'.verification.json')).read_text())
        assert digest(base)==vr['plain_sha256'] and vr['sdat_all_block_hashes_and_plaintext_verified']
        assert digest(meta['source'])==meta['source_sha256']
        arc=Psarc(base);index={e.name:e for e in arc.entries};overrides={}
        if name=='General2d':
            raw=arc._read_file(index[BACKLOG_ENTRY]);fixed,_=patch_backlog(raw)
            if fixed!=raw:overrides[BACKLOG_ENTRY]=fixed
        for e in arc.entries:
            if not e.name.lower().endswith('.dat'):continue
            raw=arc._read_file(e)
            if raw[:4]!=b'FIXH':continue
            fixed=parse_fixed(raw);changes={i:replace(t) for i,t in enumerate(fixed.strings) if replace(t)!=t}
            if changes:
                overrides[e.name]=rebuild_fixed(fixed,changes)
                report['fixed_terminology'].append(dict(archive=name,entry=e.name,strings=len(changes)))
        for (archive,entry),items in groups.items():
            if archive!=name:continue
            raw=overrides.get(entry,arc._read_file(index[entry]));result,review=compile_entry(raw,items,'en',metrics)
            if result!=raw:overrides[entry]=result
            report['review'].extend(dict(archive=name,entry=entry,**r) for r in review)
        plain=STAGE/(name+'.psarc');encrypted=STAGE/(name+'.psarc.sdat')
        stamp=STAGE/(name+'.built.json')
        key=hashlib.sha256(json.dumps({k:hashlib.sha256(v).hexdigest() for k,v in overrides.items()},sort_keys=True).encode()).hexdigest()
        cached=json.loads(stamp.read_text()) if stamp.exists() else {}
        if cached.get('overrides')==key and plain.exists() and digest(plain)==cached['plain_sha256'] and encrypted.exists() and digest(encrypted)==cached['sdat_sha256']:
            print(name+': reusing verified release archive',flush=True)
        else:
            if plain.exists() or encrypted.exists():raise ValueError('Review existing partial release files: '+name)
            if overrides:verification=repack(base,plain,overrides,lambda m:print(name+': '+m,flush=True))
            else:shutil.copy2(base,plain);verification=dict(all_entries_verified=True,unchanged_baseline=True)
            original=Path(meta['source']).with_suffix('.psarc.sdat')
            print(name+': encrypting and verifying release archive',flush=True)
            sdat.encrypt(plain,encrypted,original,verbose=False)
            assert sdat.verify(encrypted,expect_plain=plain,verbose=False)
            cached=dict(overrides=key,plain_sha256=digest(plain),sdat_sha256=digest(encrypted),verification=verification)
            atomic_json(stamp,cached)
        blob=DATA/(name+'.delta');recipe_path=DATA/(name+'.recipe.json')
        if recipe_path.exists():
            recipe=json.loads(recipe_path.read_text());assert recipe['target_sha256']==cached['plain_sha256'] and digest(blob)==recipe['blob_sha256']
        else:
            print(name+': packaging vanilla COPY/DATA delta',flush=True)
            recipe=build_recipe(meta['source'],plain,blob)
            check=STAGE/(name+'.recipe-check.psarc');apply_recipe(meta['source'],blob,recipe,check)
            assert digest(check)==cached['plain_sha256'];check.unlink()
            atomic_json(recipe_path,recipe)
        metadata=DATA/(name+'.sdatmeta');metadata.write_bytes(sdat_metadata(encrypted))
        report['archives'].append(dict(name=name,source_sdat_sha256=meta['template_sha256'],
            target_sdat_sha256=cached['sdat_sha256'],size=encrypted.stat().st_size,plain_size=plain.stat().st_size,
            recipe=recipe_path.name,recipe_sha256=digest(recipe_path),blob=blob.name,blob_sha256=digest(blob),metadata=metadata.name,metadata_sha256=digest(metadata),
            changed_native_entries=len(overrides),baseline_verified=True))
        atomic_json(DATA/'release.json',report)
    icon=BASE/'ui/Common/Dat/SaveData/sys_icon.png';shutil.copy2(icon,DATA/'install_icon.png')
    from native_eboot import load_asset,MODE
    native_info,_=load_asset(ROOT/'script_editor/assets/native_eboot')
    shutil.copytree(ROOT/'script_editor/assets/native_eboot',DATA/'native_eboot',dirs_exist_ok=True)
    shutil.copy2(ROOT/'script_editor/assets/font.bin',DATA/'font.bin')
    report.update(status='ready',install_icon_sha256=digest(DATA/'install_icon.png'),font_mode=MODE,
                  embedded_eboot_sha256=native_info['sha256'],embedded_elf_sha256=native_info['elf_sha256'],
                  embedded_ppu=native_info['ppu'],rpcs3_only=True,
                  font_sha256=digest(DATA/'font.bin'),spacing_user_confirmed=True,package_bytes=sum(p.stat().st_size for p in DATA.rglob('*') if p.is_file()))
    assert digest(project.path)==project_hash
    atomic_json(DATA/'release.json',report)
    print(json.dumps(dict(status='ready',archives=len(report['archives']),edited_rows=project.count(),
          fixed_terminology=report['fixed_terminology'],native_fields=len(report['review']),package_bytes=report['package_bytes'])),flush=True)


if __name__=='__main__':main()

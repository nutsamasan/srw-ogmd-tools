"""Portable full-English patching from a hash-checked vanilla ISO or game folder."""
from pathlib import Path
from contextlib import nullcontext
import json,os,shutil,tempfile
from core import atomic_json
from archive_patch import digest
from release_delta import apply_recipe,sdat_metadata
from vendor import sdat
from iso_image import DiscImage,canonical
from iso_patcher import signature,write_patched_iso
from native_eboot import MODE as EMBEDDED,load_asset,prepare as prepare_eboot,validate_prepared
from movie_patch import package_movie,prepare_movie,validate_movie

NAMES=('Logic','Common','General2d','Battle','General3d')


def package_info(data):
    data=Path(data).resolve()
    doc=json.loads((data/'release.json').read_text(encoding='utf8'))
    if doc.get('version') not in (1,2) or doc.get('status')!='ready' or doc.get('title_id')!='BLJS10335':
        raise ValueError('Choose the data folder from a verified full-English release.')
    if len(doc['archives'])!=5 or {a['name'] for a in doc['archives']}!=set(NAMES):raise ValueError('Incomplete full-English package.')
    for a in doc['archives']:
        name=a['name']
        if a['recipe']!=name+'.recipe.json' or a['blob']!=name+'.delta' or a['metadata']!=name+'.sdatmeta':raise ValueError('Invalid package filename.')
        for key in ('recipe','blob','metadata'):
            if digest(data/a[key])!=a[key+'_sha256']:raise ValueError('Release payload checksum failed: '+a[key])
    support=[('install_icon.png','install_icon_sha256')]
    if doc.get('font_mode')==EMBEDDED:
        info,_=load_asset(data/'native_eboot')
        if info['sha256']!=doc.get('embedded_eboot_sha256'):raise ValueError('Release EBOOT checksum failed.')
    else:support.append(('spacing.yml','spacing_sha256'))
    for file,key in support:
        if digest(data/file)!=doc[key]:raise ValueError('Release asset checksum failed: '+file)
    if doc.get('font_sha256') and digest(data/'font.bin')!=doc['font_sha256']:raise ValueError('Release font checksum failed.')
    package_movie(data,doc)
    return doc


def copy_runtime_assets(data,build,embedded=False):
    release=json.loads((data/'release.json').read_text(encoding='utf8'))
    (build/'runtime').mkdir(exist_ok=True)
    names=['install_icon.png'] if embedded else ['install_icon.png','spacing.yml']
    for name in names:shutil.copy2(data/name,build/'runtime'/name)
    info={key:release[key] for key in ('install_icon_sha256',) if key in release}
    if not embedded:info['spacing_sha256']=release['spacing_sha256']
    else:info['font_mode']=EMBEDDED
    atomic_json(build/'runtime/assets.json',info)


def prepare_font_patch(data,source,build,progress=lambda text:None):
    """Upgrade only EBOOT in an existing game, preserving its current text."""
    data,source,build=map(lambda p:Path(p).resolve(),(data,source,build))
    load_asset(data/'native_eboot')
    is_iso=source.is_file() and source.suffix.lower()=='.iso'
    game=None if is_iso else source_folder(source)
    if build.exists() or build.is_relative_to(data) or (game and build.is_relative_to(source)):
        raise ValueError('Choose a new build folder outside the game and release data.')
    start=signature(source) if is_iso else None
    build.mkdir(parents=True)
    report=dict(version=1,kind='ogmd-iso' if is_iso else 'ogmd-full-folder',profile='font-only',status='building',
        font_mode=EMBEDDED,source=str(source),source_corpus=str(data),archives=[],review=[])
    manifest=build/('iso_patch.json' if is_iso else 'full_patch.json');atomic_json(manifest,report)
    try:
        with DiscImage(source) if is_iso else nullcontext() as iso:
            if iso:
                item=iso.file('/PS3_GAME/USRDIR/EBOOT.BIN');iso.check_patch_files([item])
                raw=b''.join(iso.chunks(item));stamp=iso.views['ISO9660'][canonical(item.path)].mtime_ns
                if stamp is None:raise ValueError('The ISO has no usable EBOOT timestamp.')
                report.update(views=list(iso.views),source_size=start[0],source_mtime_ns=start[1])
            else:
                path=game/'USRDIR/EBOOT.BIN';raw=path.read_bytes();stamp=path.stat().st_mtime_ns;report['game_root']=str(game)
            report['eboot']=prepare_eboot(raw,data/'native_eboot',build/'native/EBOOT.BIN',stamp)
            if iso:
                progress('Fingerprinting the source ISO; all game text will be preserved…')
                report['source_sha256']=digest(source)
                if signature(source)!=start:raise ValueError('The source ISO changed during preparation.')
        copy_runtime_assets(data,build,True)
        report['status']='ready';atomic_json(manifest,report);return manifest
    except Exception as exc:
        report.update(status='failed',error=str(exc));atomic_json(manifest,report);raise


def source_folder(source):
    source=Path(source).resolve()
    if source.name.lower()=='psarc':
        raise ValueError('This is a PSARC archive folder. Full English builds need the original Japanese ISO or complete disc folder containing PS3_GAME. For font / battle text fix only, choose the ISO or complete game folder you boot. Use the editor\'s Patch edits for installed PSARC data.')
    game=source/'PS3_GAME' if (source/'PS3_GAME').is_dir() else source
    sfo=game/'PARAM.SFO'
    if not sfo.is_file() or sfo.stat().st_size>1024*1024 or b'BLJS10335' not in sfo.read_bytes():
        raise ValueError('Choose a complete OGMD disc folder containing PS3_GAME, or PS3_GAME itself with PARAM.SFO and USRDIR/EBOOT.BIN. Installed PSARC data is only supported by the editor\'s Patch edits.')
    if not (game/'USRDIR/EBOOT.BIN').is_file():
        raise ValueError('This folder has no USRDIR/EBOOT.BIN. Choose the original Japanese ISO or complete disc folder for full translation, or the game you boot for font / battle text fix only. Use the editor\'s Patch edits for installed game data.')
    return game


def prepare_full_patch(data,source,build,progress=lambda text:None,edits=None):
    data,source,build=map(lambda p:Path(p).resolve(),(data,source,build))
    release=package_info(data);is_iso=source.is_file() and source.suffix.lower()=='.iso'
    from edit_bundle import read_bundle
    from patcher import compile_entry
    from archive_patch import repack
    from vendor.psarc import Psarc
    from core import NativeMetrics
    groups,edits_hash=read_bundle(edits,release) if edits else ({},None)
    metrics=NativeMetrics(data/'font.bin') if groups else None
    game=None if is_iso else source_folder(source)
    if build.exists() or build.is_relative_to(data) or (game and build.is_relative_to(source)):
        raise ValueError('Choose a new build folder outside the source and release data.')
    parent=build.parent
    while not parent.exists():parent=parent.parent
    required=sum(a['size'] for a in release['archives'])+max(a['size'] for a in release['archives'])*3
    if release.get('movie'):required+=release['movie']['size']*(2 if is_iso else 1)
    if shutil.disk_usage(parent).free<required:raise ValueError(f'Building needs about {required/1024**3:.1f} GB free.')
    start=signature(source) if is_iso else None
    build.mkdir(parents=True);(build/'native').mkdir();(build/'runtime').mkdir()
    report=dict(version=2 if release.get('movie') else 1,kind='ogmd-iso' if is_iso else 'ogmd-full-folder',profile='full-english',status='building',
                source=str(source),source_corpus=str(data),release=release['release'],release_manifest_sha256=digest(data/'release.json'),
                edited_rows=release['edited_rows'],archives=[],review=release['review'],features=release['features'],
                runtime_assets=str(build/'runtime'),project_sha256=release['project_sha256'])
    embedded=release.get('font_mode')==EMBEDDED
    if embedded:report['font_mode']=EMBEDDED
    manifest=build/('iso_patch.json' if is_iso else 'full_patch.json')
    atomic_json(manifest,report)
    if edits:
        report['editor_corrections_sha256']=edits_hash
        report['editor_corrections_review']=[]
        shutil.copy2(edits,build/'patch_edits.json')
        if read_bundle(build/'patch_edits.json',release)[1]!=edits_hash:raise ValueError('Editor corrections changed while being copied.')
    try:
        with DiscImage(source) if is_iso else nullcontext() as iso:
            eboot='/PS3_GAME/USRDIR/EBOOT.BIN'
            actual=iso.checksum(iso.file(eboot)) if iso else digest(game/'USRDIR/EBOOT.BIN')
            if actual!=release['eboot_sha256']:raise ValueError('Vanilla EBOOT revision does not match BLJS10335 01.00.')
            if embedded:
                item=iso.file(eboot) if iso else None
                raw=b''.join(iso.chunks(item)) if iso else (game/'USRDIR/EBOOT.BIN').read_bytes()
                stamp=iso.views['ISO9660'][canonical(eboot)].mtime_ns if iso else (game/'USRDIR/EBOOT.BIN').stat().st_mtime_ns
                if stamp is None:raise ValueError('The ISO has no usable EBOOT timestamp.')
                report['eboot']=prepare_eboot(raw,data/'native_eboot',build/'native/EBOOT.BIN',stamp)
                if iso:iso.check_patch_files([item]+[iso.file('/PS3_GAME/USRDIR/PSARC/'+n+'.psarc.sdat') for n in NAMES])
            if iso:
                iso.check_patch_files([iso.file('/PS3_GAME/USRDIR/PSARC/'+n+'.psarc.sdat') for n in NAMES])
                report.update(views=list(iso.views),source_size=start[0],source_mtime_ns=start[1])
            else:report['game_root']=str(game)
            for a in release['archives']:
                name=a['name'];filename=name+'.psarc.sdat';progress('Checking vanilla '+name+'…')
                item=iso.file('/PS3_GAME/USRDIR/PSARC/'+filename) if iso else None
                original=build/(name+'.source.sdat') if iso else game/'USRDIR/PSARC'/filename
                before=iso.checksum(item) if iso else digest(original)
                if before!=a['source_sdat_sha256']:raise ValueError(name+' is not the supported vanilla revision. Select the untouched Japanese source.')
                if iso:
                    stamp=iso.views['ISO9660'][canonical(item.path)].mtime_ns
                    if stamp is None:raise ValueError('The ISO has no usable archive timestamp.')
                    if iso.extract(item,original)!=before:raise ValueError('ISO source changed during extraction.')
                else:stamp=original.stat().st_mtime_ns
                plain=build/(name+'.source.psarc');patched=build/(name+'.english.psarc');output=build/'native'/filename
                progress('Decrypting '+name+'…');sdat.decrypt(original,plain,verbose=False)
                if not sdat.verify(original,expect_plain=plain,verbose=False):raise ValueError('Source SDAT verification failed: '+name)
                recipe=json.loads((data/a['recipe']).read_text(encoding='utf8'))
                progress('Rebuilding complete English '+name+'…');apply_recipe(plain,data/a['blob'],recipe,patched)
                customized=False
                if any(archive==name for archive,entry in groups):
                    arc=Psarc(patched);index={e.name:e for e in arc.entries};overrides={}
                    for (archive,entry),items in groups.items():
                        if archive!=name:continue
                        if entry not in index:raise ValueError('Correction entry is missing: '+entry)
                        original_text=arc._read_file(index[entry]);changed,review=compile_entry(original_text,items,'en',metrics)
                        if changed!=original_text:overrides[entry]=changed
                        report['editor_corrections_review'].extend(dict(archive=name,entry=entry,**r) for r in review)
                    if overrides:
                        custom=build/(name+'.custom.psarc');verification=repack(patched,custom,overrides,progress,optimize_images=any('/SceneTitle/' in e for e in overrides))
                        patched.unlink();custom.rename(patched);customized=True
                        report.setdefault('custom_archive_verification',{})[name]=verification
                progress('Encrypting and verifying every '+name+' block…');sdat.encrypt(patched,output,original,verbose=False)
                if not customized:sdat_metadata(output,(data/a['metadata']).read_bytes())
                if output.stat().st_size!=a['size'] or (not customized and digest(output)!=a['target_sdat_sha256']) or not sdat.verify(output,expect_plain=patched,verbose=False):
                    raise ValueError('Full-English output verification failed: '+name)
                if digest(original)!=before:raise ValueError('Source changed during build: '+name)
                os.utime(output,ns=(stamp,stamp))
                report['archives'].append(dict(name=name,file='native/'+filename,before=before,after=digest(output),size=a['size'],mtime_ns=stamp))
                atomic_json(manifest,report)
                plain.unlink();patched.unlink()
                if iso:original.unlink()
            movie=prepare_movie(data,release,game,iso,build,progress)
            if movie:report['movie']=movie;atomic_json(manifest,report)
            if iso:
                progress('Verifying the entire source ISO…');report['source_sha256']=digest(source)
                if signature(source)!=start:raise ValueError('Source ISO changed during build.')
        copy_runtime_assets(data,build,embedded)
        report['status']='ready';atomic_json(manifest,report)
        return manifest
    except Exception as exc:
        report.update(status='failed',error=str(exc));atomic_json(manifest,report);raise


def write_full_game(manifest,output,progress=lambda text:None):
    manifest,output=Path(manifest).resolve(),Path(output).resolve()
    doc=json.loads(manifest.read_text(encoding='utf8'));folder=manifest.parent
    if doc.get('profile') not in ('full-english','font-only') or doc.get('status')!='ready':raise ValueError('Build and verify a game patch first.')
    if doc.get('version',1) not in (1,2):raise ValueError('Unsupported game build format.')
    if doc.get('font_mode')==EMBEDDED:validate_prepared(folder,doc['eboot'])
    if doc.get('profile')=='font-only' and (doc.get('font_mode')!=EMBEDDED or doc['archives']):raise ValueError('Invalid font-only build.')
    if doc['kind']=='ogmd-iso':
        result=write_patched_iso(manifest,output,progress)
        doc.update(output=str(output),output_sha256=result['output_sha256']);atomic_json(manifest,doc)
        return result
    validate_movie(folder,doc)
    source=Path(doc['source']).resolve();game=Path(doc['game_root']).resolve()
    if output.exists() or output.is_relative_to(source) or output.is_relative_to(folder) or source.is_relative_to(output):
        raise ValueError('Choose a new output folder outside the source and build folders.')
    if not output.parent.is_dir():raise ValueError('Create the output parent folder first.')
    files=[p for p in source.rglob('*') if p.is_file()]
    if any(p.is_symlink() or p.is_junction() for p in source.rglob('*')):raise ValueError('Linked source folders are not supported.')
    required=sum(p.stat().st_size for p in files)
    if shutil.disk_usage(output.parent).free<required:raise ValueError('Not enough space for the full game copy.')
    replacements={str((game/'USRDIR/PSARC'/(a['name']+'.psarc.sdat')).relative_to(source)):a for a in doc['archives']}
    if doc.get('movie'):replacements[str((game/'USRDIR/PSARC/Movie.psarc').relative_to(source))]=doc['movie']
    if doc.get('font_mode')==EMBEDDED:replacements[str((game/'USRDIR/EBOOT.BIN').relative_to(source))]={**doc['eboot'],'name':'EBOOT'}
    for rel,a in replacements.items():
        if digest(source/rel)!=a['before'] or (source/rel).stat().st_mtime_ns!=a['mtime_ns'] or digest(folder/a['file'])!=a['after']:
            raise ValueError('Source or prepared archive changed: '+a['name'])
    temporary=Path(tempfile.mkdtemp(prefix=output.name+'.partial-',dir=output.parent));checks=[]
    # On failure this clearly named partial folder is retained for inspection;
    # no existing user folder is ever deleted or replaced.
    for i,path in enumerate(files):
        rel=path.relative_to(source);a=replacements.get(str(rel));payload=folder/a['file'] if a else path
        before=signature(path);expected=a['after'] if a else digest(path)
        dest=temporary/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        progress(f'Copying and checking {i+1}/{len(files)}: {rel}')
        shutil.copy2(payload,dest)
        if a:os.utime(dest,ns=(a['mtime_ns'],a['mtime_ns']))
        if digest(dest)!=expected or signature(path)!=before or dest.stat().st_mtime_ns!=(a['mtime_ns'] if a else before[1]):raise ValueError('Copy changed during verification: '+str(path))
        checks.append(dict(file=rel.as_posix(),sha256=expected,size=dest.stat().st_size))
    os.rename(temporary,output)
    result=dict(status='verified',output=str(output),source=str(source),source_preserved=True,files=checks,patch_manifest=str(manifest))
    if doc.get('font_mode')==EMBEDDED:result['embedded_font_code']=True
    atomic_json(output.with_name(output.name+'.verification.json'),result)
    doc['output']=str(output);atomic_json(manifest,doc)
    return result

"""Build reviewed text edits from an ISO, then write and verify a separate ISO."""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from core import atomic_json
from archive_patch import digest
from iso_image import DiscImage,CHUNK
from patcher import collect_changes,prepare_patch,ARCHIVE_NAMES
from backlog_layout import patch_archives

def signature(path):
    s=Path(path).stat();return (s.st_size,s.st_mtime_ns,s.st_ino)

def prepare_iso_patch(project,language,source,destination,metrics=None,normalize=True,progress=lambda text:None,backlog=True):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Choose a new ISO patch build folder.')
    if destination.is_relative_to(project.corpus.root):raise ValueError('Build outside the original script corpus.')
    names=patch_archives(collect_changes(project,language),backlog)
    if not names:raise ValueError('There are no edits in the selected language to patch.')
    start=signature(source)
    with DiscImage(source) as iso:
        items=[iso.file('/PS3_GAME/USRDIR/PSARC/'+name+'.psarc.sdat') for name in names]
        iso.check_patch_files(items)
        parent=destination.parent
        while not parent.exists():parent=parent.parent
        required=sum(x.size for x in items)*5
        if shutil.disk_usage(parent).free<required:raise ValueError(f'Building needs about {required/1024**3:.1f} GB free in the build drive.')
        destination.mkdir(parents=True)
        target=destination/'source/PS3_GAME/USRDIR/PSARC';target.mkdir(parents=True)
        (target.parent.parent/'PARAM.SFO').write_bytes(iso.content(iso.file('/PS3_GAME/PARAM.SFO')))
        for name,item in zip(names,items):
            progress('Reading '+name+' from the ISO…');iso.extract(item,target/(name+'.psarc.sdat'))
        # Folder builder validates Logic even when only Common/Battle is edited.
        if 'Logic' not in names:iso.extract(iso.file('/PS3_GAME/USRDIR/PSARC/Logic.psarc.sdat'),target/'Logic.psarc.sdat')
        views=list(iso.views)
    native=prepare_patch(project,language,[target],destination/'native',metrics,normalize,progress,backlog=backlog)
    doc=json.loads(native.read_text(encoding='utf8'))
    progress('Fingerprinting the entire source ISO…');source_hash=digest(source)
    if signature(source)!=start:raise ValueError('The ISO changed during the build. Build again.')
    report=dict(version=1,kind='ogmd-iso',status='ready',source=str(source),source_sha256=source_hash,
        source_size=start[0],source_mtime_ns=start[1],source_corpus=str(project.corpus.root),
        language=language,project_sha256=doc['project_sha256'],views=views,
        archives=[{**a,'file':'native/'+a['file']} for a in doc['archives']],review=doc['review'],layout_fixes=doc.get('layout_fixes',[]))
    atomic_json(destination/'iso_patch.json',report)
    # Only generated input copies are removed; the original image stays open read-only.
    for file in target.iterdir():file.unlink()
    (target.parent.parent/'PARAM.SFO').unlink()
    return destination/'iso_patch.json'

def write_patched_iso(manifest,output,progress=lambda text:None):
    manifest=Path(manifest).resolve();folder=manifest.parent
    doc=json.loads(manifest.read_text(encoding='utf8'))
    if doc.get('version') not in (1,2) or doc.get('kind')!='ogmd-iso' or doc.get('status')!='ready':
        raise ValueError('Select a verified ISO patch build.')
    source=Path(doc['source']).resolve();output=Path(output).resolve()
    if output==source or output.exists():raise ValueError('Choose a new output ISO; existing files are never overwritten.')
    if output.suffix.lower()!='.iso':raise ValueError('The output must use the .iso extension.')
    if output.is_relative_to(Path(doc['source_corpus']).resolve()):raise ValueError('Write the ISO outside the script corpus.')
    if not output.parent.is_dir():raise ValueError('Choose an existing output folder.')
    sidecar=output.with_suffix('.iso.verification.json')
    if sidecar.exists():raise ValueError('A verification report already exists for that output name.')
    start=signature(source)
    if start[:2]!=(doc['source_size'],doc['source_mtime_ns']):raise ValueError('Source ISO changed after the preview. Build again.')
    if shutil.disk_usage(output.parent).free<start[0]+CHUNK:raise ValueError(f'The output drive needs {start[0]/1024**3:.1f} GB free.')
    patches=[];opened=[];temporary=None
    try:
        with DiscImage(source) as iso:
            items=[];names=set()
            allowed=(*ARCHIVE_NAMES,'General3d') if doc.get('profile')=='full-english' else ARCHIVE_NAMES
            for archive in doc['archives']:
                name=archive['name']
                if name not in allowed or name in names or archive['file']!='native/'+name+'.psarc.sdat':raise ValueError('Invalid ISO patch archive.')
                names.add(name);payload=folder/archive['file'];item=iso.file('/PS3_GAME/USRDIR/PSARC/'+name+'.psarc.sdat');items.append(item)
                if item.size!=archive['size'] or payload.stat().st_size!=item.size or digest(payload)!=archive['after']:
                    raise ValueError('Prepared archive changed: '+name)
                if iso.checksum(item)!=archive['before']:raise ValueError('ISO archive changed since the preview: '+name)
                reader=payload.open('rb');opened.append(reader);file_offset=0
                for offset,length in item.extents:
                    patches.append((offset,offset+length,reader,file_offset));file_offset+=length
            from movie_patch import validate_movie,DISC_PATH
            movie_payload=validate_movie(folder,doc)
            if movie_payload:
                movie=doc['movie'];item=iso.file(DISC_PATH);items.append(item)
                if item.size!=movie['size'] or iso.checksum(item)!=movie['before']:raise ValueError('ISO movie changed since the preview.')
                reader=movie_payload.open('rb');opened.append(reader);file_offset=0
                for offset,length in item.extents:
                    patches.append((offset,offset+length,reader,file_offset));file_offset+=length
            if doc.get('font_mode')=='embedded-eboot':
                from native_eboot import validate_prepared
                record=doc['eboot'];payload=validate_prepared(folder,record)
                item=iso.file('/PS3_GAME/USRDIR/EBOOT.BIN');items.append(item)
                if item.size!=record['size'] or iso.checksum(item)!=record['before']:raise ValueError('ISO EBOOT changed since the preview.')
                reader=payload.open('rb');opened.append(reader);file_offset=0
                for offset,length in item.extents:
                    patches.append((offset,offset+length,reader,file_offset));file_offset+=length
            if doc.get('profile')=='font-only' and (doc.get('font_mode')!='embedded-eboot' or doc['archives']):raise ValueError('Invalid font-only ISO build.')
            if not patches:raise ValueError('The ISO patch has no files.')
            if doc.get('profile')=='full-english' and names!=set(allowed):raise ValueError('Full English ISO requires all five archives.')
            iso.check_patch_files(items)
            fd,tmp=tempfile.mkstemp(prefix=output.name+'.',suffix='.partial',dir=output.parent);temporary=Path(tmp)
            expected_hash=hashlib.sha256();source_hash=hashlib.sha256()
            with os.fdopen(fd,'wb') as out:
                for offset in range(0,iso.size,CHUNK):
                    block=iso.read(offset,min(CHUNK,iso.size-offset));source_hash.update(block);block=bytearray(block)
                    for a,b,reader,base in patches:
                        lo,hi=max(offset,a),min(offset+len(block),b)
                        if lo<hi:
                            reader.seek(base+lo-a);replacement=reader.read(hi-lo)
                            if len(replacement)!=hi-lo:raise ValueError('Prepared archive became truncated.')
                            block[lo-offset:hi-offset]=replacement
                    out.write(block);expected_hash.update(block)
                    if offset%(128*1024*1024)==0:progress(f'Writing patched ISO: {100*offset/iso.size:.0f}%')
                out.flush();os.fsync(out.fileno())
            if source_hash.hexdigest()!=doc['source_sha256'] or signature(source)!=start:
                raise ValueError('Source ISO changed after the build; output discarded.')
            progress('Verifying the complete output ISO…')
            actual=digest(temporary)
            if actual!=expected_hash.hexdigest() or temporary.stat().st_size!=iso.size:raise ValueError('Output ISO verification failed.')
            with DiscImage(temporary) as check:
                for archive in doc['archives']:
                    item=check.file('/PS3_GAME/USRDIR/PSARC/'+archive['name']+'.psarc.sdat')
                    if check.checksum(item)!=archive['after']:raise ValueError('ISO payload verification failed.')
                if doc.get('font_mode')=='embedded-eboot' and check.checksum(check.file('/PS3_GAME/USRDIR/EBOOT.BIN'))!=doc['eboot']['after']:
                    raise ValueError('ISO embedded EBOOT verification failed.')
                if doc.get('movie') and check.checksum(check.file(DISC_PATH))!=doc['movie']['after']:
                    raise ValueError('ISO English intro verification failed.')
            if signature(source)!=start:raise ValueError('Source ISO changed during output verification.')
            # Windows rename fails if the target exists, including one created during the job.
            if os.name=='nt':os.rename(temporary,output)
            else:os.link(temporary,output);temporary.unlink()
            temporary=None
            result=dict(status='verified',source=str(source),output=str(output),size=iso.size,
                source_sha256=source_hash.hexdigest(),output_sha256=actual,source_preserved=True,
                outside_archive_bytes_unchanged=not bool(doc.get('eboot')),outside_patched_files_unchanged=True,filesystem_views=doc['views'],patch_manifest=str(manifest),
                archives=[{k:a[k] for k in ('name','before','after','size')} for a in doc['archives']])
            if doc.get('font_mode')=='embedded-eboot':result.update(embedded_font_code=True,eboot=doc['eboot'])
            if doc.get('movie'):result['movie']=doc['movie']
            atomic_json(sidecar,result);progress('Patched ISO created and verified: '+str(output));return result
    finally:
        for reader in opened:reader.close()
        if temporary is not None and temporary.exists():temporary.unlink()

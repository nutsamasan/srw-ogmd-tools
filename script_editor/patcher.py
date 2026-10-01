"""Prepare, verify, install and restore text-only PS3 patches from editor changes."""
from __future__ import annotations
import copy
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from core import atomic_json,sha
from archive_patch import digest,repack
from vendor.psarc import Psarc
from vendor import sdat
from backlog_layout import ARCHIVE as BACKLOG_ARCHIVE, ENTRY as BACKLOG_ENTRY, patch_backlog, patch_archives
from native_formats import (parse_ldbi_table,read_cstring,parse_logo,parse_bmd,parse_csb,
                            patch_ldbi,patch_logo,patch_bmd,rebuild_csb)

ARCHIVE_NAMES=('Logic','Common','Battle','General2d')


def default_targets(corpus):
    # Development copies are not safe defaults for a user's current game.
    return []


def archive_name(entry):
    if re.fullmatch(r'Dat/SceneTitle/Dds/@Ja/(st|sn)_\d{3}\.dds',entry):return 'Common'
    if entry.startswith('Dat/Archive/'):return 'Common'
    if entry.startswith('Dat/Battle/'):return 'Battle'
    if entry.startswith(('Dat/logic/','Dat/Roll/')):return 'Logic'
    if entry in ('Dat/FixedData/PilotData.dat','Dat/FixedData/UnitData.dat','Dat/FixedData/KeyWordData.dat','Dat/FixedData/SpiritData.dat','Dat/FixedData/WeaponData.dat'):return 'Logic'
    raise ValueError('Unsupported native script location: '+entry)


def collect_changes(project,language):
    if language not in ('en','jp'):raise ValueError('Select one patch language.')
    gathered=defaultdict(list);shared={}
    for key,collection in project.data['collections'].items():
        doc,expected=project.corpus.load(key)
        if digest(project.corpus.root/key/'script.json')!=expected:raise ValueError('Source export changed: '+key)
        rows={r['id']:r for r in doc['rows']}
        for rid,edits in collection['rows'].items():
            selected={f:edits[f] for f in (language,'speaker_'+language) if f in edits}
            if not selected:continue
            row=rows[rid]
            if row.get('null_text'):raise ValueError('Cannot patch a battle record with no subtitle: '+rid)
            item=dict(key=key,row=row,edits=selected)
            if doc['metadata'].get('script_id')=='DEAD':shared[rid]=item
            else:
                entry=row.get('native_entry') if row.get('location_field') else doc['metadata'].get('native_entry')
                if not entry:raise ValueError('No native mapping for '+rid)
                gathered[(archive_name(entry),'/'+entry)].append(item)
    if shared:
        for collection in project.corpus.collections:
            doc,_=project.corpus.load(collection['key'])
            for ref in doc.get('shared_defeat_references',[]):
                if ref['shared_id'] in shared:
                    item=copy.deepcopy(shared[ref['shared_id']]);item['row'].update(command_index=ref['command_index'],command_offset=ref['command_offset'])
                    gathered[('Logic','/'+doc['metadata']['native_entry'])].append(item)
    from title_cards import project_cards
    gathered.update(project_cards(project).groups(language))
    return gathered


def supported_text(text,metrics,normalize):
    special={'≥':'≧','≤':'≦','｢':'"','｣':'"','〜':'～','Ι':'I','❝':'“','❞':'”'}
    result=[]
    for c in text:
        if c in '\n\r\t' or metrics is None or metrics.descriptor(c) is not None:result.append(c);continue
        replacement=special.get(c)
        if replacement is None and unicodedata.name(c,'').startswith('LATIN '):
            replacement=''.join(x for x in unicodedata.normalize('NFKD',c) if not unicodedata.combining(x))
        if not normalize or not replacement or any(metrics.descriptor(x) is None for x in replacement):
            raise ValueError(f'The native font has no glyph for {c!r}. Edit that character before patching.')
        result.append(replacement)
    return ''.join(result)


def compile_entry(source,items,language,metrics=None,normalize=True):
    """Verify stable native record mapping and change only selected fields."""
    if any(item['row'].get('title_card') for item in items):
        from title_cards import compile_card
        return compile_card(source,items,language)
    kind=source[:4];edits=[];changes={};review=[];seen={}
    if kind==b'FIXH':
        from fixed_data import compile_fixed
        return compile_fixed(source,items,language,metrics,normalize)
    if kind==b'LDBI':
        _,_,offsets=parse_ldbi_table(source);number,start=struct.unpack_from('>II',source,0x20)
    elif kind==b'LOGO':_,tables=parse_logo(source)
    elif kind==b'CSB ':records=parse_csb(source)[2]
    elif source[:2]==b'\x03\0':counts,start,pool,texts=parse_bmd(source)
    else:raise ValueError('Unrecognized native text format')
    for item in items:
        row=item['row']
        for field,text in item['edits'].items():
            native=supported_text(text,metrics,normalize)
            if source[:2]==b'\x03\0':
                from text_layout import battle_storage
                native=battle_storage(native)
            elif kind!=b'CSB ':native=native.replace('\r\n','\n').replace('\r','\n').replace('\n','@')
            if kind==b'LDBI':
                command=row['command_index'];p=start+command*196
                if not 0<=command<number or p!=row['command_offset']:
                    raise ValueError('Dialogue command mapping changed: '+row['id'])
                from native_formats import LDBI_TEXT_FIELDS,location_signature
                if row.get('location_field'):
                    native_field=row['location_field']
                    if native_field not in ('location','map_location','map_label') or field.startswith('speaker_'):
                        raise ValueError('Unsupported location field.')
                    if any(c in native for c in '@<>'):
                        raise ValueError('Location labels must be one line without control markers: '+row['id'])
                    if location_signature(source[p:p+196])!=row['location_metadata_hex']:raise ValueError('Location event data differs: '+row['id'])
                else:
                    native_field='speaker' if field.startswith('speaker_') else 'text'
                    if source[p+20:p+196].hex()!=row['command_metadata_hex']:raise ValueError('Dialogue event data differs: '+row['id'])
                opcode,offset=LDBI_TEXT_FIELDS[native_field]
                if struct.unpack_from('>I',source,p)[0]!=opcode:raise ValueError('Native text event type changed: '+row['id'])
                index=struct.unpack_from('>I',source,p+offset)[0]
                before=read_cstring(source,offsets[index]);identity=(command,native_field)
                edits.append((command,native_field,native))
            elif field.startswith('speaker_'):raise ValueError('No native speaker field: '+row['id'])
            elif kind==b'LOGO':
                identity=row['native_string_index'];before=tables[1]['strings'][identity];changes[identity]=native
            elif kind==b'CSB ':
                command=row['command_index'];args=records[command]['arguments']
                arg=1 if row['id'].startswith('Roll_01_cnv:') else 3
                opcode='0' if arg==1 else '19' if row['id'].startswith('Roll_20_cnv:') else '42'
                if args[0]!=opcode:raise ValueError('Narration command mapping changed: '+row['id'])
                identity=(command,arg);before=args[arg];changes[identity]=native
            else:
                identity=row['message_index'];before=texts[identity]
                if source[start+identity*20:start+identity*20+16].hex()!=row['record_metadata_hex']:
                    raise ValueError('Battle voice/event metadata differs: '+row['id'])
                changes[identity]=native
            if identity in seen and seen[identity]!=native:raise ValueError('Conflicting changes to a shared native field: '+row['id'])
            seen[identity]=native
            if before is None:raise ValueError('Record has no native text field.')
            # Numeric insertion tokens must remain valid in mission objectives.
            if sorted(re.findall(r'#\d+',before))!=sorted(re.findall(r'#\d+',native)):
                raise ValueError('Keep the #number insertion tokens in '+row['id'])
            marker='/' if source[:2]==b'\x03\0' else '@'
            review.append(dict(id=row['id'],field=field,before=before.replace(marker,'\n') if kind!=b'CSB ' else before,
                               after=native.replace(marker,'\n') if kind!=b'CSB ' else native,normalized=native!=text.replace('\n',marker) if kind!=b'CSB ' else native!=text))
    if kind==b'LDBI':result=patch_ldbi(source,edits)
    elif kind==b'LOGO':result=patch_logo(source,changes)
    elif kind==b'CSB ':result=rebuild_csb(source,changes)
    else:result=patch_bmd(source,changes)
    return result,review


def validate_target(path,corpus=None):
    path=Path(path).resolve()
    if path.name.casefold()!='psarc' or path.parent.name.casefold()!='usrdir':
        raise ValueError('Choose the PSARC folder inside the game USRDIR folder.')
    sfo=path.parent.parent/'PARAM.SFO'
    if not sfo.is_file() or b'BLJS10335' not in sfo.read_bytes():raise ValueError('Target must be OGMD PS3 (BLJS10335).')
    if corpus:
        manifest=json.loads((corpus.root/'SOURCE_MANIFEST.json').read_text(encoding='utf8'))
        protected={Path(v['path']).resolve().parent for k,v in manifest['archives'].items() if k.startswith('jp_')}
        if path in protected:raise ValueError('This is the pristine extraction source. Choose the installed game copy.')
    if not (path/'Logic.psarc.sdat').is_file():raise ValueError('The target has no Logic.psarc.sdat.')
    return path


def game_closed():
    if os.name!='nt':return
    result=subprocess.run(['tasklist.exe','/FI','IMAGENAME eq rpcs3.exe','/FO','CSV','/NH'],capture_output=True,creationflags=0x08000000)
    if result.returncode!=0 or b'rpcs3.exe' in result.stdout.lower():
        raise ValueError('Close RPCS3 before installing or restoring game archives. Building a patch can be done while it is open.')


def prepare_patch(project,language,targets,destination,metrics=None,normalize=True,progress=lambda text:None,keep_plain=False,backlog=True):
    targets=[validate_target(p,project.corpus) for p in targets if str(p).strip()]
    if not targets or len(set(targets))!=len(targets):raise ValueError('Choose distinct game archive folders.')
    groups=collect_changes(project,language)
    if not groups and not backlog:raise ValueError('There are no '+('English' if language=='en' else 'Japanese')+' edits to patch.')
    names=patch_archives(groups,backlog);destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Choose a new patch output folder.')
    if destination.is_relative_to(project.corpus.root) or any(destination.is_relative_to(t.parent.parent) for t in targets):
        raise ValueError('Store patch builds outside the source corpus and game folders.')
    required=sum((targets[0]/(a+'.psarc.sdat')).stat().st_size for a in names)*4
    parent=destination.parent
    while not parent.exists():parent=parent.parent
    if shutil.disk_usage(parent).free<required:raise ValueError(f'Patch building needs about {required/1024**3:.1f} GB free.')
    destination.mkdir(parents=True)
    from title_cards import project_fingerprint,project_cards
    report=dict(version=1,status='building',language=language,project_sha256=project_fingerprint(project),
                source_corpus=str(project.corpus.root),targets=[str(t) for t in targets],archives=[],review=[],layout_fixes=[])
    atomic_json(destination/'edits.json',project.data);atomic_json(destination/'patch.json',report)
    if project_cards(project).count():atomic_json(destination/'title_cards.json',project_cards(project).data)
    try:
        for name in names:
            progress('Checking '+name+' in every target…');filename=name+'.psarc.sdat';original=targets[0]/filename
            before=digest(original);stamp=original.stat().st_mtime_ns;size=original.stat().st_size
            for target in targets:
                file=target/filename
                if digest(file)!=before or file.stat().st_mtime_ns!=stamp:
                    raise ValueError(name+' differs between the selected copies (content or timestamp).\n\n'+str(original)+'\n'+str(file)+
                        '\n\nFor an ISO game, choose Use installed game data to patch only the selected RPCS3 installation. Otherwise choose two matching copies of the same game build.')
            base=destination/(name+'.source.psarc');plain=destination/(name+'.patched.psarc');encrypted=destination/filename
            progress('Decrypting '+name+'…');sdat.decrypt(original,base,verbose=False)
            if not sdat.verify(original,expect_plain=base,verbose=False):raise ValueError(name+' source SDAT verification failed.')
            arc=Psarc(base);index={e.name:e for e in arc.entries};overrides={}
            if backlog and name==BACKLOG_ARCHIVE:
                if BACKLOG_ENTRY not in index:raise ValueError('The selected game has no supported backlog layout.')
                raw=arc._read_file(index[BACKLOG_ENTRY]);result,layout=patch_backlog(raw)
                report['layout_fixes'].append(layout)
                if result!=raw:overrides[BACKLOG_ENTRY]=result
            for (archive,entry),items in groups.items():
                if archive!=name:continue
                progress('Compiling '+Path(entry).name+'…')
                try:result,review=compile_entry(arc._read_file(index[entry]),items,language,metrics,normalize)
                except Exception as exc:raise ValueError(name+' '+entry+': '+str(exc)) from exc
                overrides[entry]=result
                report['review'].extend(dict(archive=name,entry=entry,**r) for r in review)
            if not overrides:
                if digest(original)!=before:raise ValueError(name+' changed during the build. Build again.')
                progress('Backlog margin is already fixed; keeping '+name+' unchanged.')
                atomic_json(destination/'patch.json',report)
                if not keep_plain:base.unlink()
                continue
            verification=repack(base,plain,overrides,lambda message:progress(name+': '+message),optimize_images=any('/SceneTitle/' in e for e in overrides))
            progress('Encrypting and checking every '+name+' SDAT block…')
            sdat.encrypt(plain,encrypted,original,verbose=False)
            if encrypted.stat().st_size!=size or not sdat.verify(encrypted,expect_plain=plain,verbose=False):raise ValueError(name+' output verification failed.')
            if digest(original)!=before:raise ValueError(name+' changed during the build. Build again.')
            report['archives'].append(dict(name=name,file=filename,before=before,after=digest(encrypted),size=size,mtime_ns=stamp,verification=verification))
            atomic_json(destination/'patch.json',report)
            if not keep_plain:base.unlink();plain.unlink()
        report['status']='ready';atomic_json(destination/'patch.json',report)
        return destination/'patch.json'
    except Exception as exc:
        report.update(status='failed',error=str(exc));atomic_json(destination/'patch.json',report);raise


def atomic_copy(source,target,expected,mtime_ns):
    source=Path(source);target=Path(target);fd,tmp=tempfile.mkstemp(prefix=target.name+'.editor-',suffix='.tmp',dir=target.parent)
    try:
        with os.fdopen(fd,'wb') as out,source.open('rb') as src:
            shutil.copyfileobj(src,out,1024*1024);out.flush();os.fsync(out.fileno())
        if digest(tmp)!=expected:raise ValueError('Copy verification failed: '+str(target))
        os.utime(tmp,ns=(mtime_ns,mtime_ns));os.replace(tmp,target)
        if digest(target)!=expected or target.stat().st_mtime_ns!=mtime_ns:raise ValueError('Installed file verification failed: '+str(target))
    finally:
        if Path(tmp).exists():Path(tmp).unlink()


def install_patch(manifest,restore=False,progress=lambda text:None,closed_check=game_closed):
    """Recheck all inputs, back up before writes, and recover all completed writes on error."""
    manifest=Path(manifest).resolve();folder=manifest.parent;doc=json.loads(manifest.read_text(encoding='utf8'))
    if doc.get('version')!=1 or doc.get('status')!='ready':raise ValueError('Patch build has not passed verification.')
    if not doc.get('archives'):raise ValueError('No game files need changing.')
    closed_check();journal_path=folder/'installation.json'
    old_journal=json.loads(journal_path.read_text(encoding='utf8')) if journal_path.exists() else None
    if restore and (not old_journal or old_journal.get('status') not in ('installed','installing','restoring','recovery_failed')):raise ValueError('This patch has no installed backup to restore.')
    if not restore and old_journal:raise ValueError('This patch already has an installation record. Build a fresh patch.')
    targets=[validate_target(t) for t in doc['targets']];items=[]
    protected=json.loads((Path(doc['source_corpus'])/'SOURCE_MANIFEST.json').read_text(encoding='utf8'))
    pristine={Path(v['path']).resolve().parent for k,v in protected['archives'].items() if k.startswith('jp_')}
    if any(t in pristine for t in targets):raise ValueError('Cannot install into a pristine source archive folder.')
    for archive in doc['archives']:
        name=archive['name'];filename=name+'.psarc.sdat'
        if name not in ARCHIVE_NAMES or archive['file']!=filename:raise ValueError('Invalid patch archive name.')
        build=folder/filename;backup=folder/'backups'/filename
        if digest(build)!=archive['after']:raise ValueError('Prepared patch file changed: '+filename)
        if restore and digest(backup)!=archive['before']:raise ValueError('Backup checksum does not match: '+filename)
        for target in targets:
            path=target/filename;current=digest(path)
            expected={archive['before'],archive['after']} if restore and old_journal.get('status')!='installed' else {archive['after'] if restore else archive['before']}
            if current not in expected or path.stat().st_mtime_ns!=archive['mtime_ns'] or path.stat().st_size!=archive['size'] or build.stat().st_size!=archive['size']:
                raise ValueError('Game file changed since this patch was built/installed: '+str(path))
            items.append(dict(target=str(path),build=str(build),backup=str(backup),starting_hash=current,**archive))
    if not restore:
        backup_dir=folder/'backups';backup_dir.mkdir(exist_ok=False)
        for archive in doc['archives']:
            filename=archive['file'];progress('Backing up '+filename+'…')
            atomic_copy(targets[0]/filename,backup_dir/filename,archive['before'],archive['mtime_ns'])
    record=dict(status='restoring' if restore else 'installing',items=items,completed=[],started=datetime.now().isoformat())
    atomic_json(journal_path,record);attempted=[]
    try:
        for item in items:
            closed_check();target=Path(item['target']);expected=item['starting_hash']
            if digest(target)!=expected:raise ValueError('Game changed during installation: '+str(target))
            attempted.append(item);progress(('Restoring ' if restore else 'Installing ')+str(target))
            atomic_copy(item['backup'] if restore else item['build'],target,item['before'] if restore else item['after'],item['mtime_ns'])
            record['completed'].append(str(target));atomic_json(journal_path,record)
    except Exception as exc:
        errors=[]
        for item in reversed(attempted):
            try:atomic_copy(item['build'] if item['starting_hash']==item['after'] else item['backup'],Path(item['target']),item['starting_hash'],item['mtime_ns'])
            except Exception as recovery:errors.append(str(recovery))
        record.update(status='recovery_failed' if errors or restore and old_journal.get('status')!='installed' else 'installed' if restore else 'recovered',error=str(exc),recovery_errors=errors)
        atomic_json(journal_path,record);raise
    record.update(status='restored' if restore else 'installed',finished=datetime.now().isoformat());atomic_json(journal_path,record)
    return record

"""Backed-up RPCS3 patch/configuration and installed-game synchronization."""
from pathlib import Path
import copy,hashlib,json,os,subprocess,tempfile
import yaml
from core import atomic_json
from archive_patch import digest
from patcher import atomic_copy

PPU='PPU-e429bb11d03c2e6a046775179d21169cba555c47'
GAME='Super Robot Wars OG The Moon Dwellers'
PATCH='OGMD English dialogue native spacing v3 (apostrophe)'
KNOWN=('OGMD English dialogue native spacing v1','OGMD English dialogue native spacing v2',PATCH)
PATCH_FILE='BLJS10335_patch.yml'
SETUP_VERSION=2
HEX_OFFSET_TYPES={'alloc','calloc','jump','jumpl','jumpf','byte','le16','le32','le64',
                  'lef32','lef64','be16','be32','bd32','be64','bd64','bef32','bef64',
                  'bpex','utf8','cutf8'}


class HexOffset(int):
    pass


class PatchDumper(yaml.SafeDumper):
    pass


PatchDumper.add_representer(HexOffset,lambda dumper,value:dumper.represent_scalar('tag:yaml.org,2002:int',f'0x{value:08x}'))


def dump_patch_yaml(value):
    # RPCS3 requires address scalars to begin with 0x. A normal YAML dump
    # changes them to decimal, which is numerically equal but is rejected.
    def convert(item):
        if isinstance(item,dict):return {key:convert(value) for key,value in item.items()}
        if isinstance(item,list):
            result=[convert(value) for value in item]
            if len(result)>=3 and isinstance(result[0],str) and result[0] in HEX_OFFSET_TYPES and type(result[1]) is int:
                result[1]=HexOffset(result[1])
            return result
        return item
    return yaml.dump(convert(value),Dumper=PatchDumper,sort_keys=False,allow_unicode=True)


def verify_patch_address_format(text):
    def walk(node):
        if isinstance(node,yaml.MappingNode):
            for _,value in node.value:walk(value)
        elif isinstance(node,yaml.SequenceNode):
            if len(node.value)>=3 and isinstance(node.value[0],yaml.ScalarNode) and node.value[0].value in HEX_OFFSET_TYPES:
                offset=node.value[1]
                if not isinstance(offset,yaml.ScalarNode) or not offset.value.startswith('0x'):
                    raise ValueError('RPCS3 requires hexadecimal patch addresses starting with 0x.')
            for value in node.value:walk(value)
    walk(yaml.compose(text))


def merge_settings(base,override):
    result=copy.deepcopy(base)
    for key,value in override.items():
        result[key]=merge_settings(result[key],value) if isinstance(value,dict) and isinstance(result.get(key),dict) else copy.deepcopy(value)
    return result


def require_closed(runtime):
    if os.name!='nt':return
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
        'Get-CimInstance Win32_Process -Filter "Name=\'rpcs3.exe\'" | Select-Object -ExpandProperty ExecutablePath | ConvertTo-Json -Compress'],
        capture_output=True,text=True,creationflags=0x08000000)
    if result.returncode:raise ValueError('Could not check the selected RPCS3 process.')
    paths=json.loads(result.stdout) if result.stdout.strip() else []
    if isinstance(paths,str):paths=[paths]
    if paths is None or any(p is None or Path(p).resolve()==Path(runtime).resolve()/'rpcs3.exe' for p in paths):
        raise ValueError('Close the selected RPCS3, then run setup again. The game output is already saved.')


def load_yaml(path):
    data=yaml.safe_load(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    if data is None:return {}
    if not isinstance(data,dict):raise ValueError('Invalid RPCS3 settings file: '+str(path))
    return data


def prepare_setup(runtime,manifest,assets,progress=lambda text:None,font_mode=None):
    runtime,manifest,assets=map(lambda p:Path(p).resolve(),(runtime,manifest,assets))
    if not (runtime/'rpcs3.exe').is_file():raise ValueError('Choose the folder containing rpcs3.exe.')
    doc=json.loads(manifest.read_text(encoding='utf8'))
    if doc.get('status')!='ready':raise ValueError('Game patch has not passed verification.')
    font_mode=font_mode or doc.get('font_mode','yaml')
    if font_mode not in ('yaml','embedded-eboot','compatibility-only'):raise ValueError('Unknown font setup mode.')
    if font_mode=='embedded-eboot':
        from native_eboot import validate_prepared
        validate_prepared(manifest.parent,doc['eboot'])
    info=json.loads((assets/'assets.json').read_text(encoding='utf8'))
    support=[('install_icon.png','install_icon_sha256')]
    if font_mode=='yaml':support.append(('spacing.yml','spacing_sha256'))
    for file,key in support:
        if digest(assets/file)!=info[key]:raise ValueError('Runtime support file changed: '+file)
    if font_mode=='yaml':
        spacing=load_yaml(assets/'spacing.yml')
        if list(spacing.get(PPU,{}))!=[PATCH]:raise ValueError('Unexpected spacing patch.')
    stage=manifest.parent/'runtime_setup'
    if stage.exists():stage=Path(tempfile.mkdtemp(prefix='attempt_',dir=stage))
    else:stage.mkdir()
    # Preserve every attempt and its backups. A previous success or failed
    # preparation must not prevent a fresh check of the chosen destination.
    persistent_assets=stage/'assets';persistent_assets.mkdir()
    for name in ['assets.json']+[file for file,key in support]:
        p=assets/name;atomic_copy(p,persistent_assets/name,digest(p),p.stat().st_mtime_ns)
    assets=persistent_assets
    operations=[]
    def add(path,payload,stamp=None):
        path=Path(path).resolve();payload=Path(payload).resolve()
        if path==payload:raise ValueError('Runtime source and destination coincide.')
        before=digest(path) if path.exists() else None
        after=digest(payload)
        if stamp is None:stamp=path.stat().st_mtime_ns if path.exists() else payload.stat().st_mtime_ns
        if before==after and path.stat().st_mtime_ns==stamp:return
        # PyInstaller resources live in a temporary directory. Keep rollback
        # inputs persistent even after that process exits.
        if not payload.is_relative_to(manifest.parent):
            persistent=stage/('payload-'+str(len(operations)))
            atomic_copy(payload,persistent,after,stamp);payload=persistent
        operations.append(dict(target=str(path),payload=str(payload),before=before,after=after,
            before_mtime_ns=path.stat().st_mtime_ns if path.exists() else None,mtime_ns=stamp,
            backup=str(stage/'backups'/str(len(operations)))))
    def edit_yaml(path,value,patch_file=False):
        text=dump_patch_yaml(value) if patch_file else yaml.safe_dump(value,sort_keys=False,allow_unicode=True)
        if patch_file:verify_patch_address_format(text)
        payload=stage/(str(len(operations))+'.yml');payload.write_text(text,encoding='utf8')
        add(path,payload)
    # Remove just the known OGMD spacing entries from other patch files so
    # RPCS3 never loads duplicate definitions for the same branch addresses.
    for path in sorted((runtime/'patches').glob('*.yml')) if font_mode!='compatibility-only' else []:
        if (path.name==PATCH_FILE and font_mode=='yaml') or (path.name!='patch.yml' and not path.name.endswith('_patch.yml')):continue
        # RPCS3's community catalog may reuse YAML anchor names between
        # games. Do not parse or rewrite files unrelated to our spacing fix.
        raw=path.read_text(encoding='utf-8-sig')
        if PPU not in raw or not any(name in raw for name in KNOWN):continue
        value=load_yaml(path)
        if any(n in value.get(PPU,{}) for n in KNOWN):
            for name in KNOWN:value[PPU].pop(name,None)
            if not value[PPU]:value.pop(PPU)
            edit_yaml(path,value,patch_file=True)
    # Boot loads patch.yml, imported_patch.yml, and <TITLE_ID>_patch.yml.
    # A descriptive arbitrary filename is invisible to the patch engine.
    own=runtime/'patches'/PATCH_FILE
    if font_mode=='yaml':
        value=load_yaml(own)
        value.setdefault('Version',spacing['Version'])
        section=value.setdefault(PPU,{})
        for name in KNOWN:section.pop(name,None)
        section[PATCH]=spacing[PPU][PATCH]
        edit_yaml(own,value,patch_file=True)
    if font_mode!='compatibility-only':
        path=runtime/'config/patch_config.yml';config=load_yaml(path)
        section=config.get(PPU,{})
        for name in KNOWN:section.pop(name,None)
        if font_mode=='yaml':
            section[PATCH]={GAME:{'BLJS10335':{'01.00':{'Enabled':True}}}}
            config[PPU]=section
        elif not section:config.pop(PPU,None)
        if path.exists() or font_mode=='yaml':edit_yaml(path,config)
    path=runtime/'config/custom_configs/config_BLJS10335.yml'
    global_path=runtime/'config/config.yml'
    if not global_path.exists():global_path=runtime/'config.yml'
    config=merge_settings(load_yaml(global_path),load_yaml(path))
    core=config.setdefault('Core',{});core['SPU Cache']=False
    libraries=core.setdefault('Libraries Control',[])
    if not isinstance(libraries,list):raise ValueError('Unexpected RPCS3 Libraries Control setting.')
    core['Libraries Control']=[x for x in libraries if not str(x).startswith('libvdec.sprx:')]+['libvdec.sprx:lle']
    config.setdefault('Savestate',{})['Compatible Savestate Mode']=True
    edit_yaml(path,config)
    if doc.get('profile') in ('full-english','font-only') and doc.get('output'):
        output=Path(doc['output']).resolve()
        if not output.exists():raise ValueError('The verified game output is missing.')
        if output.is_file() and digest(output)!=doc.get('output_sha256'):raise ValueError('The verified output ISO changed.')
        if font_mode=='embedded-eboot' and output.is_dir():
            game_output=output/'PS3_GAME' if (output/'PS3_GAME').is_dir() else output
            if digest(game_output/'USRDIR/EBOOT.BIN')!=doc['eboot']['after']:raise ValueError('The output embedded EBOOT changed.')
        path=runtime/'config/games.yml';games=load_yaml(path)
        games['BLJS10335']=str(output).replace('\\','/')
        edit_yaml(path,games)
    vfs=load_yaml(runtime/'config/vfs.yml');emulator=str(runtime)+os.sep
    if vfs.get('$(EmulatorDir)'):emulator=str(Path(vfs['$(EmulatorDir)']).resolve())+os.sep
    location=vfs.get('/dev_hdd0/','$(EmulatorDir)dev_hdd0/').replace('$(EmulatorDir)',emulator)
    if '$(' in location:raise ValueError('Unsupported RPCS3 virtual HDD path.')
    hdd=Path(location)
    if not hdd.is_absolute():hdd=runtime/hdd
    installed=hdd.resolve()/'game/BLJS10335'
    # A clean runtime installs disc data and its English icon on first boot.
    # Existing data must be synchronized so it cannot shadow patched disc data.
    sync=installed.exists() and doc.get('profile')=='full-english'
    source=Path(doc.get('source','')).resolve() if doc.get('source') else None
    if source and source.is_dir() and (installed.is_relative_to(source) or source.is_relative_to(installed)):
        raise ValueError('The RPCS3 HDD location overlaps the source game. The vanilla source must be preserved.')
    if sync:
        sfo=installed/'PARAM.SFO'
        if not sfo.exists() or sfo.stat().st_size>1024*1024 or b'BLJS10335' not in sfo.read_bytes():
            raise ValueError('The existing OGMD HDD installation is incomplete; inspect it before synchronization.')
        for a in doc['archives']:
            payload=manifest.parent/a['file']
            if digest(payload)!=a['after'] or payload.stat().st_size!=a['size']:raise ValueError('Prepared game archive changed.')
            add(installed/'USRDIR/PSARC'/(a['name']+'.psarc.sdat'),payload,a['mtime_ns'])
        common=next((a for a in doc['archives'] if a['name']=='Common'),None)
        if doc.get('profile')=='full-english':
            if common is None:raise ValueError('The full release is missing Common.')
            add(installed/'ICON0.PNG',assets/'install_icon.png',common['mtime_ns'])
        # For script-only patches, the installed Common retains its own icon.
    result=dict(status='prepared',setup_version=SETUP_VERSION,font_mode=font_mode,patch_path=str(own) if font_mode=='yaml' else None,runtime=str(runtime),game_manifest=str(manifest),assets=str(assets),
                installed_game=str(installed),sync_installed_data=sync,operations=operations)
    atomic_json(stage/'setup.json',result)
    progress(f'Prepared RPCS3 setup: {len(operations)} file changes with rollback backups.')
    return stage/'setup.json'


def verify_runtime(runtime,assets,font_mode='yaml'):
    runtime,assets=Path(runtime),Path(assets)
    path=runtime/'patches'/PATCH_FILE
    if font_mode=='yaml':
        expected=load_yaml(assets/'spacing.yml')[PPU][PATCH]
        if load_yaml(path).get(PPU,{}).get(PATCH)!=expected:
            raise ValueError('RPCS3 cannot load the expected spacing patch: '+str(path))
        verify_patch_address_format(path.read_text(encoding='utf8'))
        enabled=load_yaml(runtime/'config/patch_config.yml').get(PPU,{}).get(PATCH,{})
        if enabled.get(GAME,{}).get('BLJS10335',{}).get('01.00',{}).get('Enabled') is not True:
            raise ValueError('The OGMD spacing patch is not enabled in RPCS3.')
    elif font_mode=='embedded-eboot':
        for file in (runtime/'patches').glob('*.yml'):
            if file.name!='patch.yml' and not file.name.endswith('_patch.yml'):continue
            raw=file.read_text(encoding='utf-8-sig')
            if PPU in raw and any(name in raw for name in KNOWN):
                if any(name in load_yaml(file).get(PPU,{}) for name in KNOWN):raise ValueError('A legacy OGMD font patch remains installed.')
        if any(name in load_yaml(runtime/'config/patch_config.yml').get(PPU,{}) for name in KNOWN):raise ValueError('A legacy OGMD font patch remains enabled.')
    config=load_yaml(runtime/'config/custom_configs/config_BLJS10335.yml')
    if (config.get('Core',{}).get('SPU Cache') is not False
            or 'libvdec.sprx:lle' not in config.get('Core',{}).get('Libraries Control',[])
            or config.get('Savestate',{}).get('Compatible Savestate Mode') is not True):
        raise ValueError('The OGMD compatibility settings were not installed.')
    return dict(patch_path=str(path) if font_mode=='yaml' else None,patch_enabled=font_mode=='yaml',font_mode=font_mode,compatibility_settings_verified=True)


def setup_runtime(runtime,manifest,assets,progress=lambda text:None,closed_check=require_closed,font_mode=None):
    closed_check(runtime)
    plan=prepare_setup(runtime,manifest,assets,progress,font_mode)
    result=apply_setup(plan,progress,closed_check=closed_check)
    result['setup_plan']=str(plan)
    progress('Installed and enabled: '+result['patch_path'] if result['patch_path'] else 'RPCS3 compatibility setup verified; no font YAML installed.')
    return result


def apply_setup(plan,progress=lambda text:None,closed_check=require_closed):
    plan=Path(plan).resolve();doc=json.loads(plan.read_text(encoding='utf8'))
    if doc.get('status')!='prepared':raise ValueError('Prepare a fresh RPCS3 setup plan.')
    closed_check(doc['runtime'])
    for op in doc['operations']:
        p=Path(op['target'])
        if (digest(p) if p.exists() else None)!=op['before'] or digest(op['payload'])!=op['after']:
            raise ValueError('RPCS3 files changed since review: '+str(p))
        if p.exists() and p.stat().st_mtime_ns!=op['before_mtime_ns']:raise ValueError('RPCS3 file timestamp changed: '+str(p))
    backup_dir=plan.parent/'backups';backup_dir.mkdir(exist_ok=False)
    for op in doc['operations']:
        if op['before'] is not None:atomic_copy(op['target'],op['backup'],op['before'],op['before_mtime_ns'])
    doc.update(status='installing',completed=[]);atomic_json(plan,doc);attempted=[]
    try:
        for op in doc['operations']:
            closed_check(doc['runtime']);target=Path(op['target'])
            if (digest(target) if target.exists() else None)!=op['before']:raise ValueError('RPCS3 files changed during setup.')
            target.parent.mkdir(parents=True,exist_ok=True);attempted.append(op)
            progress('Setting up '+str(target));atomic_copy(op['payload'],target,op['after'],op['mtime_ns'])
            doc['completed'].append(str(target));atomic_json(plan,doc)
        game=json.loads(Path(doc['game_manifest']).read_text(encoding='utf8'))
        if doc['sync_installed_data'] and game.get('profile')=='full-english':
            installed=Path(doc['installed_game']);icon=installed/'ICON0.PNG'
            required=sum((a['size']+1023)//1024 for a in game['archives'])+(icon.stat().st_size+1023)//1024
            actual=sum((p.stat().st_size+1023)//1024 for p in installed.rglob('*') if p.is_file())
            if actual<=required:raise ValueError('Native installed-data size check did not pass.')
            doc.update(required_kb=required,installed_kb=actual)
        if doc.get('setup_version')==SETUP_VERSION:
            doc.update(verify_runtime(doc['runtime'],doc['assets'],doc.get('font_mode','yaml')))
    except Exception as exc:
        errors=[]
        for op in reversed(attempted):
            try:
                if op['before'] is None:
                    p=Path(op['target'])
                    if p.exists() and digest(p)==op['after']:p.unlink()
                else:atomic_copy(op['backup'],op['target'],op['before'],op['before_mtime_ns'])
            except Exception as error:errors.append(str(error))
        doc.update(status='recovery_failed' if errors else 'recovered',error=str(exc),recovery_errors=errors);atomic_json(plan,doc);raise
    doc['status']='installed';atomic_json(plan,doc);return doc


def restore_setup(plan,progress=lambda text:None,closed_check=require_closed):
    plan=Path(plan);doc=json.loads(plan.read_text(encoding='utf8'));closed_check(doc['runtime'])
    if doc.get('status')!='installed':raise ValueError('Select an installed RPCS3 setup backup.')
    for op in doc['operations']:
        if digest(op['target'])!=op['after'] or Path(op['target']).stat().st_mtime_ns!=op['mtime_ns']:raise ValueError('RPCS3 has later changes; do not overwrite them.')
        if op['before'] is not None and digest(op['backup'])!=op['before']:raise ValueError('Rollback backup changed.')
    attempted=[];doc['status']='restoring';atomic_json(plan,doc)
    try:
        for op in reversed(doc['operations']):
            closed_check(doc['runtime']);progress('Restoring '+op['target'])
            if digest(op['target'])!=op['after']:raise ValueError('RPCS3 changed during restore.')
            attempted.append(op)
            if op['before'] is None:Path(op['target']).unlink()
            else:atomic_copy(op['backup'],op['target'],op['before'],op['before_mtime_ns'])
    except Exception as exc:
        errors=[]
        for op in reversed(attempted):
            try:atomic_copy(op['payload'],op['target'],op['after'],op['mtime_ns'])
            except Exception as error:errors.append(str(error))
        doc.update(status='recovery_failed' if errors else 'installed',error=str(exc),recovery_errors=errors);atomic_json(plan,doc);raise
    doc['status']='restored';atomic_json(plan,doc);return doc

"""Resolve one installed OGMD target from the selected RPCS3 folder."""
from pathlib import Path
from runtime_setup import load_yaml
from patcher import validate_target


def installed_target(runtime):
    runtime=Path(runtime).resolve()
    if not (runtime/'rpcs3.exe').is_file():raise ValueError('Choose the folder containing rpcs3.exe.')
    vfs=load_yaml(runtime/'config/vfs.yml')
    emulator=Path(vfs['$(EmulatorDir)']).resolve() if vfs.get('$(EmulatorDir)') else runtime
    location=vfs.get('/dev_hdd0/','$(EmulatorDir)dev_hdd0/').replace('$(EmulatorDir)',str(emulator)+'/')
    if '$(' in location:raise ValueError('Unsupported RPCS3 virtual HDD path.')
    hdd=Path(location)
    if not hdd.is_absolute():hdd=runtime/hdd
    target=hdd/'game/BLJS10335/USRDIR/PSARC'
    if not target.is_dir():raise ValueError('This RPCS3 has no installed OGMD data. Start the English game once to install its data, then try again.')
    return validate_target(target)


def runtime_hint(home,config):
    if config.get('runtime'):return config['runtime']
    for target in config.get('targets',[]):
        for parent in Path(target).parents:
            if (parent/'rpcs3.exe').is_file():return str(parent)
    import json
    path=Path(home).parent/'full_patcher/settings.json'
    try:return json.loads(path.read_text(encoding='utf8')).get('runtime','')
    except (OSError,ValueError):return ''

"""End-to-end verification on disposable copies; original archives stay read-only."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
from weapon_editor import weapon_patch as core

ROOT=Path(__file__).resolve().parent.parent
TARGETS=[ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc.sdat',
    Path('local_data/rpcs3/dev_hdd0/game/BLJS10335/USRDIR/PSARC/Logic.psarc.sdat'),
    ROOT/'native_eboot_test/runtime/dev_hdd0/game/BLJS10335/USRDIR/PSARC/Logic.psarc.sdat']


def main():
    report=dict(archives=[],in_game_test=False)
    originals={p:core.snapshot(p) for p in TARGETS}
    for path in TARGETS:
        print('Verifying disposable copy:',path,flush=True)
        with tempfile.TemporaryDirectory(prefix='ogmd-weapons-qa-') as folder:
            target=Path(folder)/path.name;shutil.copy2(path,target);sessions=[]
            def read():
                s=core.Session(target);sessions.append(s);return s
            try:
                first=read();keys=(1,80,855)
                updates={k:replace(first.weapons[k].settings,power=60000,minimum_range=1,maximum_range=255,en_cost=0,ammo=255) for k in keys}
                receipt=first.install(updates);changed=read()
                assert {k:changed.weapons[k].settings for k in keys}==updates
                a,b=core.Psarc(first.plain),core.Psarc(changed.plain)
                differences=[x.name for x,y in zip(a.entries,b.entries) if a._read_file(x)!=b._read_file(y)]
                assert differences==[core.WEAPON_ENTRY]
                assert core.snapshot(Path(receipt['backup']))==originals[path]
                changed.restore_backup(receipt['manifest']);assert core.snapshot(target)==originals[path]
                again=read();again.install(updates);modified=read()
                modified.install({k:first.weapons[k].settings for k in keys})
                assert read().weapon==first.weapon
                report['archives'].append(dict(path=str(path),snapshot=originals[path],weapons=len(first.weapons),
                    changed_entries=differences,unchanged_entries=len(a.entries)-1,only_intended_fields=True,
                    exact_backup_restore=True,stats_restore=True,sdat_verified=True))
            finally:
                for s in sessions:s.close()
    assert {p:core.snapshot(p) for p in TARGETS}==originals
    report['original_archives_unchanged']=True
    (Path(__file__).parent/'qa/weapon_archives.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print('Three archive copies verified; originals unchanged.',flush=True)


if __name__=='__main__':main()

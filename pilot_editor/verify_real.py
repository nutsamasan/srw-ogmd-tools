"""Disposable archive/save roundtrips; never modifies the original targets."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import tempfile
import pilot_patch as core
import will_save as saves

ROOT=Path(__file__).resolve().parent.parent
TARGETS=[ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/Logic.psarc.sdat',
    Path('local_data/rpcs3/dev_hdd0/game/BLJS10335/USRDIR/PSARC/Logic.psarc.sdat'),
    ROOT/'native_eboot_test/runtime/dev_hdd0/game/BLJS10335/USRDIR/PSARC/Logic.psarc.sdat']


def main():
    report=dict(archives=[],saves=[],in_game_test=False,original_archives_unchanged=False,original_saves_unchanged=False)
    original_archives={p:core.snapshot(p) for p in TARGETS}
    slots=saves.discover_saves()
    original_saves={s.slot_path:saves.snapshot_slot(s.slot_path) for s in slots}
    for path in TARGETS:
        print('Archive copy:',path,flush=True)
        with tempfile.TemporaryDirectory(prefix='ogmd-pilot-qa-') as folder:
            target=Path(folder)/path.name; shutil.copy2(path,target)
            sessions=[]
            def read():
                s=core.Session(target); sessions.append(s); return s
            try:
                first=read(); pid=97; p=first.pilots[pid]; slots=list(p.settings.spirits)
                slots[0]=replace(slots[0],cost=15 if slots[0].cost!=15 else 20)
                update=replace(p.settings,personality=(p.settings.personality+1)%12,spirits=tuple(slots))
                receipt=first.install({pid:update})
                changed=read(); assert changed.pilots[pid].settings==update
                old,new=core.Psarc(first.plain),core.Psarc(changed.plain)
                differences=[a.name for a,b in zip(old.entries,new.entries) if old._read_file(a)!=new._read_file(b)]
                assert differences==[core.PILOT_ENTRY]
                assert core.snapshot(Path(receipt['backup']))==original_archives[path]
                changed.restore_backup(receipt['manifest']); assert core.snapshot(target)==original_archives[path]
                again=read(); again.install({pid:update}); changed_again=read()
                changed_again.install({pid:p.settings}); restored=read()
                assert restored.pilot==first.pilot
                report['archives'].append(dict(path=str(path),source=original_archives[path],pilots=len(first.pilots),
                    entries=len(old.entries),unchanged_entries=len(old.entries)-1,changed_entries=differences,
                    exact_backup_restoration=True,settings_restoration=True,sdat_blocks_verified=True))
            finally:
                for s in sessions:s.close()
    for path,before in original_saves.items():
        print('Save copy:',path.name,flush=True)
        with tempfile.TemporaryDirectory(prefix='ogmd-will-qa-') as folder:
            target=Path(folder)/path.name; shutil.copytree(path,target)
            pilots=saves.load_will(target); selected=(pilots[0],pilots[-1])
            updates={p.pilot.pilot_id:150 if p.will!=150 else 100 for p in selected}
            raw=(target/'PARMDAT.SAV').read_bytes()
            result=saves.write_will(target,updates,expected_snapshot=before)
            assert saves.snapshot_slot(result.backup_path)==before
            changed={i for i,(a,b) in enumerate(zip(raw,(target/'PARMDAT.SAV').read_bytes())) if a!=b}
            allowed={saves.PILOT_RECORD_BASE+p.pilot.slot_index*72+saves.WILL_OFFSET for p in selected}
            assert changed==allowed
            assert {k for k in before if before[k]!=result.snapshot[k]}=={'PARMDAT.SAV'}
            restore=saves.backup_will_updates(target,result.backup_path)
            saves.write_will(target,restore,expected_snapshot=result.snapshot)
            assert saves.snapshot_slot(target)==before
            report['saves'].append(dict(path=str(path),source=before,pilots=len(pilots),changed_offsets=sorted(changed),
                only_intended_bytes=True,full_backup_verified=True,will_restore_identical=True))
    assert {p:core.snapshot(p) for p in original_archives}==original_archives
    assert {p:saves.snapshot_slot(p) for p in original_saves}==original_saves
    report.update(original_archives_unchanged=True,original_saves_unchanged=True)
    (Path(__file__).parent/'qa/real_verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(f"Verified {len(report['archives'])} archive copies and {len(report['saves'])} save copies; originals unchanged.",flush=True)


if __name__=='__main__':main()

"""Exercise real save copies only; retain exact-byte and original-hash evidence."""
import json
from pathlib import Path
import shutil
import tempfile

from discovery import discover_saves
import ogmd_save as core
import mech_skills as feature


def main():
    report={'original_saves_unchanged':True,'in_game_load_test':False,'saves':[]}
    for info in discover_saves():
        before=core.snapshot_slot(info.slot_path)
        with tempfile.TemporaryDirectory(prefix='ogmd-mech-verify-') as temp:
            slot=Path(temp)/info.directory_name
            shutil.copytree(info.slot_path,slot)
            assert core.snapshot_slot(slot)==before
            mechs=feature.load_mechs(slot)
            equipment=next((m for m in mechs if len(m.shared_slots)>1 and any(m.equipped)),None)
            if equipment is None:
                equipment=next(m for m in mechs if any(m.equipped))
            values=list(equipment.equipped)
            selected=next(i for i,v in enumerate(values) if v)
            ability_id=values[selected];values[selected]=0
            builtin=next(m for m in mechs if any(m.builtins))
            switches=list(builtin.enabled)
            selected=next(i for i,v in enumerate(builtin.builtins) if v)
            switches[selected]=not switches[selected]
            original={p.name:p.read_bytes() for p in slot.iterdir() if p.is_file()}
            abilities=core.load_abilities(slot)
            result=feature.write_mech_changes(slot,{equipment.slot_index:values},{builtin.slot_index:switches},expected_snapshot=before)
            assert core.snapshot_slot(result.backup_path)==before
            allowed_param={feature.UNIT_BASE+i*feature.UNIT_STRIDE+o for i in equipment.shared_slots for o in range(0x23,0x26)}
            offset=feature.UNIT_BASE+builtin.slot_index*feature.UNIT_STRIDE+feature.FLAGS_OFFSET
            allowed_param.update(range(offset,offset+4))
            offset=core.ABILITY_AVAILABLE_OFFSET+2*(ability_id-1)
            allowed={core.PARMDAT_NAME:allowed_param,core.SYSDATA_NAME:set(range(offset,offset+2))}
            changes={}
            for name,payload in original.items():
                current=(slot/name).read_bytes()
                changed={i for i,(a,b) in enumerate(zip(payload,current)) if a!=b}
                assert len(current)==len(payload) and changed<=allowed.get(name,set()),name
                changes[name]=sorted(changed)
            assert changes[core.PARMDAT_NAME] and changes[core.SYSDATA_NAME]
            assert result.abilities[ability_id-1].available==abilities[ability_id-1].available+1
            assert [a.total_owned for a in abilities]==[a.total_owned for a in result.abilities]
            restored=feature.write_mech_changes(slot,{equipment.slot_index:equipment.equipped},{builtin.slot_index:builtin.enabled},expected_snapshot=result.snapshot)
            assert restored.snapshot==before
            assert core.snapshot_slot(info.slot_path)==before
            report['saves'].append({'path':str(info.slot_path),'scenario':info.subtitle,'sha256':before,
                'mech_count':len(mechs),'shared_slots':equipment.shared_slots,'equipped_mech':equipment.name,
                'builtin_mech':builtin.name,'changed_offsets':changes,'backup_matches_original':True,
                'unrelated_bytes_preserved':True,'inventory_totals_preserved':True,'restore_matches_original':True})
    assert report['saves']
    destination=Path(__file__).parent/'qa/mech_skills_verification.json'
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(f"Verified combined mech writes and byte-identical restoration on {len(report['saves'])} real save copies. Originals unchanged.")


if __name__=='__main__':
    main()

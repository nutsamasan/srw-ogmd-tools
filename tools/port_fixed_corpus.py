"""Apply official fixed-data overlays through verified native record fields."""
from collections import defaultdict
from pathlib import Path
import json
import struct

from ogmd_text_formats import parse_fixed, rebuild_fixed
from port_mltd_stage import parse_mltd, sha256, has_japanese

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'work/extracted/ps3_logic/Dat/FixedData'
LANG = ROOT / 'work/extracted/ps4_lang/Dat/MultiLanguage/@En/FixedData'
OUT = ROOT / 'work/poc/full_english_20260906'

# filename: expected stride, fields (official table, byte offset, index width).
# Small tables use byte-sized IDs; larger tables use big-endian halfwords.
SCHEMA = {
    'AbilityData': (12, [('SpecialAbilityName',1,1),('SpecialAbilityDivision',2,1),('SecialAbilityDescription',10,1)]),
    'AbilityElementData': (68, [('AbilityName',1,1),('AbilityDescription',64,1)]),
    'ACEBonusData': (48, [('AceBonusName',1,1),('AceBonusDescription',45,1)]),
    'AceFullTuneBonusData': (428, [('AceFullTuneBonusName',2,2),('AceFullTuneBonusDescription',424,2)]),
    'AntiFieldTypeData': (4, [('SpecialEffect2',1,1)]),
    'BGMData': (12, [('BGM',1,1)]),
    'HelpData': (4, [('HelpDescription',2,2)]),
    'KeyWordData': (12, [('Terminology',2,2),('TerminologyDescription1',8,2),('TerminologyDescription2',10,2)]),
    'MAXChangeBonusData': (60, [('MaximumRemodelBonusName',1,1),('MaximumRemodelBonusDescription',56,1)]),
    'PartsData': (64, [('StrengtheningPartsName',1,1),('StrengtheningPartsDescription',62,1)]),
    'PilotData': (336, [('PilotNickName',2,2),('PilotFamilyName',12,2),('PilotName',14,2),('PilotCharaVoiceName',306,2)]),
    'PilotDictionaryData': (4, [('CharaDicitonaryDescription1',2,1),('CharaDicitonaryDescription2',3,1)]),
    'PlayEndMessageData': (16, [('EndMessageTitleName',3,1)]),
    'ProgStrData': (4, [('ProgStrData',2,2)]),
    'SkillData': (32, [('SpecialSkillName',1,1),('SpecialSkillDescription',28,1)]),
    'SpecialEffectData': (20, [('SpecialEffect1',1,1)]),
    'SpiritData': (12, [('MindCommandName',1,1),('MindCommandDescription',10,1)]),
    'StageData': (20, [('StageName',3,1),('StageName',5,1),('RootName',6,1)]),
    'TrophyData': (12, [('Trophy',4,1),('TrophyDescription',5,1)]),
    'UnitData': (216, [('MachineName',2,2)]),
    'UnitDictionaryData': (4, [('RobotLergeBookDescription1',2,1),('RobotLergeBookDescription2',3,1)]),
}


def build():
    (OUT/'fixed').mkdir(exist_ok=True)
    (OUT/'fixed_reports').mkdir(exist_ok=True)
    inventory = []
    for filename, (stride, fields) in SCHEMA.items():
        source = (SOURCE/(filename+'.dat')).read_bytes()
        fixed = parse_fixed(source)
        assert all(len(r) == stride for r in fixed.records)
        tables = {name: parse_mltd((LANG/(name+'.mltd')).read_bytes())[0] for name,_,_ in fields}
        # Stage's DOFS is sparse by scenario ID; the official table follows
        # the 81 physical records, including alternate routes between IDs.
        order = list(range(len(fixed.records))) if filename == 'StageData' else fixed.logical_indices
        assert all(len(es) == len(order) for es in tables.values()), filename
        assignments, rows, choices = [], [], defaultdict(list)
        for logical, physical in enumerate(order):
            if physical == 0xFFFFFFFF:
                continue
            for name, offset, width in fields:
                index = int.from_bytes(fixed.records[physical][offset:offset+width], 'big')
                assert index < len(fixed.strings), (filename,logical,offset,index)
                jp = fixed.strings[index]
                en = tables[name][logical].text.replace('\r\n','\n').replace('\r','\n')
                if filename == 'ProgStrData':
                    from pilot_development_text_fix import DESCRIPTIONS
                    en = DESCRIPTIONS.get(logical, en)
                assignments.append((physical,offset,width,en))
                if en not in choices[index]: choices[index].append(en)
                rows.append(dict(logical=logical,physical=physical,offset=offset,width=width,
                                 table=name,index=index,japanese=jp,english=en))
        replacements = {i: options[0] for i,options in choices.items()}
        try:
            result = rebuild_fixed(fixed, replacements, assignments)
            if filename == 'ProgStrData':
                from pilot_development_text_fix import fix_descriptions
                result, _ = fix_descriptions(result)
            actual = parse_fixed(result)
            report = dict(file=filename, source_sha256=sha256(source),output_sha256=sha256(result),
                          source_size=len(source),output_size=len(result),rows=rows,
                          strings_before=len(fixed.strings),strings_after=len(actual.strings),
                          conflicts=[dict(index=i,english=es) for i,es in choices.items() if len(es)>1],
                          remaining=[dict(index=i,text=t) for i,t in enumerate(actual.strings) if has_japanese(t)],
                          all_field_mappings_verified=True, non_text_record_bytes_preserved=True)
            (OUT/'fixed'/(filename+'.dat')).write_bytes(result)
            (OUT/'fixed_reports'/(filename+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            inventory.append(dict(file=filename,status='converted',fields=len(rows),remaining=len(report['remaining']),
                                  added_strings=len(actual.strings)-len(fixed.strings),size_change=len(result)-len(source)))
        except Exception as exc:
            inventory.append(dict(file=filename,status='needs_work',error=str(exc)))
    (OUT/'fixed_inventory.json').write_text(json.dumps(inventory,indent=2),encoding='utf8')
    print(json.dumps(inventory,indent=2))


def build_weapons():
    normal = parse_mltd((LANG/'WeaponName.mltd').read_bytes())[0]
    option = parse_mltd((LANG/'ReplacementWeaponName.mltd').read_bytes())[0]
    assert len(normal) == 255 * 10 and len(option) == 55
    reports = []
    for filename in ['WeaponData','WeaponData_Temp']:
        source = (SOURCE/(filename+'.dat')).read_bytes()
        fixed = parse_fixed(source)
        rows,assignments,replacements,missing = [],[],{},[]
        for physical,record in enumerate(fixed.records):
            unit,slot = int.from_bytes(record[:2],'big'),record[2]
            index = int.from_bytes(record[4:6],'big')
            logical = slot if unit == 0 else (unit - 1)*10 + slot
            table = option if unit == 0 else normal
            assert slot < (55 if unit == 0 else 10)
            assert logical < len(table)
            english = table[logical].text
            if not english:
                missing.append(dict(physical=physical,unit=unit,slot=slot,japanese=fixed.strings[index]))
                continue
            replacements.setdefault(index,english)
            assignments.append((physical,4,2,english))
            rows.append(dict(physical=physical,unit=unit,slot=slot,index=index,
                             japanese=fixed.strings[index],english=english,english_index=logical))
        result = rebuild_fixed(fixed,replacements,assignments)
        report = dict(file=filename,source_sha256=sha256(source),output_sha256=sha256(result),
                      source_size=len(source),output_size=len(result),rows=rows,missing=missing,
                      weapon_stats_and_attack_references_preserved=True)
        (OUT/'fixed'/(filename+'.dat')).write_bytes(result)
        (OUT/'fixed_reports'/(filename+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        reports.append(dict(file=filename,mapped=len(rows),missing=missing,size_change=len(result)-len(source)))
    (OUT/'weapons_inventory.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(reports,ensure_ascii=True))


if __name__ == '__main__':
    build()
    build_weapons()

from __future__ import annotations

import struct
from pathlib import Path
import tempfile
import unittest

from ogmd_save import (
    ABILITY_AVAILABLE_OFFSET,
    ABILITY_STOCK_TARGET,
    ABILITY_TOTAL_OFFSET,
    CURRENT_FUNDS_OFFSET,
    MAX_ABILITIES,
    MAX_KILLS,
    MAX_PP,
    MAX_PARTS,
    PARMDAT_SIZE,
    PART_AVAILABLE_OFFSET,
    PART_LOCKED,
    PART_TOTAL_OFFSET,
    PILOT_EXPERIENCE_IN_RECORD,
    PILOT_ID_IN_RECORD,
    PILOT_KILLS_IN_RECORD,
    PILOT_PP_IN_RECORD,
    PILOT_RECORD_BASE,
    PILOT_RECORD_COUNT,
    PILOT_RECORD_STRIDE,
    TOTAL_FUNDS_OFFSET,
    SYSDATA_SIZE,
    WEAPON_MASK_OFFSET,
    WEAPON_MASK_WORD_COUNT,
    WEAPON_SLOT_BASE,
    WEAPON_SLOT_COUNT,
    WEAPON_SLOT_STRIDE,
    WEAPON_TARGET_COPIES,
    SaveFormatError,
    load_abilities,
    load_pilots,
    load_parts,
    load_save,
    load_weapons,
    write_funds,
    write_abilities,
    write_pilot_kills,
    write_pilot_pp,
    write_parts,
    write_weapon_totals,
)


def _align(value: int, alignment: int = 4) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def _make_sfo(directory: str, funds: int) -> bytes:
    values = [
        ("DETAIL", f"●ルート：Lune\n●資金：{funds}　／　●総ターン数：20\n", 1024),
        ("SAVEDATA_DIRECTORY", directory, 64),
        ("SUB_TITLE", "シナリオ:04　 『The Battle for Dank』", 128),
        ("TITLE", "第２次スーパーロボット大戦ＯＧ", 128),
    ]
    key_blob = b"".join(key.encode("ascii") + b"\0" for key, _, _ in values)
    header_size = 20
    index_size = 16 * len(values)
    key_start = header_size + index_size
    data_start = _align(key_start + len(key_blob))
    payload = bytearray(data_start + sum(max_length for _, _, max_length in values))
    struct.pack_into("<4sIIII", payload, 0, b"\0PSF", 0x00000101, key_start, data_start, len(values))
    payload[key_start : key_start + len(key_blob)] = key_blob

    key_offset = 0
    data_offset = 0
    for index, (key, value, max_length) in enumerate(values):
        encoded = value.encode("utf-8") + b"\0"
        struct.pack_into(
            "<HHIII", payload, header_size + index * 16, key_offset, 0x0204, len(encoded), max_length, data_offset
        )
        start = data_start + data_offset
        payload[start : start + len(encoded)] = encoded
        key_offset += len(key.encode("ascii")) + 1
        data_offset += max_length
    return bytes(payload)


def _make_slot(root: Path, funds: int = 284_394, total_funds: int = 3_967_894) -> Path:
    name = "BLJS10335_OMI-SCN26073114592846"
    slot = root / name
    slot.mkdir()
    sysdata = bytearray(SYSDATA_SIZE)
    struct.pack_into(">I", sysdata, CURRENT_FUNDS_OFFSET, funds)
    struct.pack_into(">I", sysdata, TOTAL_FUNDS_OFFSET, total_funds)
    sysdata[PART_AVAILABLE_OFFSET : PART_AVAILABLE_OFFSET + 3] = bytes((0, PART_LOCKED, 2))
    sysdata[PART_TOTAL_OFFSET : PART_TOTAL_OFFSET + 3] = bytes((3, PART_LOCKED, 4))
    struct.pack_into(">2H", sysdata, ABILITY_AVAILABLE_OFFSET, 0, 1)
    struct.pack_into(">2H", sysdata, ABILITY_TOTAL_OFFSET, 3, 4)
    (slot / "SYSDATA.SAV").write_bytes(sysdata)
    (slot / "PARAM.SFO").write_bytes(_make_sfo(name, funds))
    parmdat = bytearray(PARMDAT_SIZE)
    pilot_records = (
        (0x35, 61, 21_170, 8),
        (0x36, 31, 20_515, 251),
    )
    for slot_index, (pilot_id, kills, experience, pp) in enumerate(pilot_records):
        record = PILOT_RECORD_BASE + slot_index * PILOT_RECORD_STRIDE
        struct.pack_into(">H", parmdat, record + PILOT_ID_IN_RECORD, pilot_id)
        struct.pack_into(">H", parmdat, record + PILOT_KILLS_IN_RECORD, kills)
        struct.pack_into(">H", parmdat, record + PILOT_EXPERIENCE_IN_RECORD, experience)
        struct.pack_into(">H", parmdat, record + PILOT_PP_IN_RECORD, pp)
    struct.pack_into(">I", parmdat, WEAPON_MASK_OFFSET, 0x00000007)
    weapon_records = (
        (0x10, 0xA8, 0),
        (0x14, 0x00, 0),
        (0x1F, 0x04, 0),
    )
    for slot_index, record_data in enumerate(weapon_records):
        record = WEAPON_SLOT_BASE + slot_index * WEAPON_SLOT_STRIDE
        parmdat[record : record + WEAPON_SLOT_STRIDE] = bytes(record_data)
    (slot / "PARMDAT.SAV").write_bytes(parmdat)
    return slot


class SaveEditorTests(unittest.TestCase):
    def test_load_and_update_with_complete_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            before = load_save(slot)
            self.assertEqual(before.funds, 284_394)
            self.assertEqual(before.total_funds, 3_967_894)
            self.assertEqual(before.spent_funds, 3_683_500)

            result = write_funds(slot, 9_999_999)

            self.assertEqual(result.save.funds, 9_999_999)
            self.assertEqual(result.save.total_funds, 13_683_499)
            self.assertEqual(result.save.spent_funds, 3_683_500)
            backup = load_save(result.backup_path)
            self.assertEqual(backup.funds, 284_394)
            self.assertEqual(backup.total_funds, 3_967_894)
            self.assertEqual(
                (result.backup_path / "PARMDAT.SAV").read_bytes(),
                (slot / "PARMDAT.SAV").read_bytes(),
            )
            self.assertIn("資金：9999999", result.save.detail)
            self.assertEqual((slot / "SYSDATA.SAV").stat().st_size, SYSDATA_SIZE)

    def test_load_and_update_pilot_pp_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            original = (slot / "PARMDAT.SAV").read_bytes()
            pilots = load_pilots(slot)
            self.assertEqual([(p.pilot_id, p.pp) for p in pilots], [(0x35, 8), (0x36, 251)])

            result = write_pilot_pp(slot, {0x35: MAX_PP, 0x36: 500})

            self.assertEqual([(p.pilot_id, p.pp) for p in result.pilots], [(0x35, 9_999), (0x36, 500)])
            backup_pilots = load_pilots(result.backup_path)
            self.assertEqual([(p.pilot_id, p.pp) for p in backup_pilots], [(0x35, 8), (0x36, 251)])
            updated = (slot / "PARMDAT.SAV").read_bytes()
            changed = [index for index, (old, new) in enumerate(zip(original, updated)) if old != new]
            expected = []
            for slot_index in (0, 1):
                offset = PILOT_RECORD_BASE + slot_index * PILOT_RECORD_STRIDE + PILOT_PP_IN_RECORD
                expected.extend((offset, offset + 1))
            self.assertEqual(changed, expected)

    def test_rejects_out_of_range_pp(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            with self.assertRaisesRegex(SaveFormatError, "0 through 9,999"):
                write_pilot_pp(slot, {0x35: MAX_PP + 1})

    def test_load_and_update_pilot_kills_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            original = (slot / "PARMDAT.SAV").read_bytes()
            before = load_pilots(slot)

            result = write_pilot_kills(slot, {0x35: MAX_KILLS, 0x36: 500})

            self.assertEqual(
                [(pilot.pilot_id, pilot.kills, pilot.pp) for pilot in result.pilots],
                [(0x35, 999, 8), (0x36, 500, 251)],
            )
            self.assertEqual(
                [(pilot.pilot_id, pilot.kills, pilot.pp) for pilot in load_pilots(result.backup_path)],
                [(pilot.pilot_id, pilot.kills, pilot.pp) for pilot in before],
            )
            updated = (slot / "PARMDAT.SAV").read_bytes()
            changed = [index for index, (old, new) in enumerate(zip(original, updated)) if old != new]
            expected = []
            for slot_index in (0, 1):
                offset = PILOT_RECORD_BASE + slot_index * PILOT_RECORD_STRIDE + PILOT_KILLS_IN_RECORD
                expected.extend((offset, offset + 1))
            self.assertEqual(changed, expected)

    def test_loads_and_updates_pilot_after_old_record_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            path = slot / "PARMDAT.SAV"
            payload = bytearray(path.read_bytes())
            slot_index = 255
            record = PILOT_RECORD_BASE + slot_index * PILOT_RECORD_STRIDE
            struct.pack_into(">H", payload, record + PILOT_ID_IN_RECORD, 0x71)
            struct.pack_into(">H", payload, record + PILOT_KILLS_IN_RECORD, 61)
            struct.pack_into(">H", payload, record + PILOT_EXPERIENCE_IN_RECORD, 30_688)
            struct.pack_into(">H", payload, record + PILOT_PP_IN_RECORD, 412)
            path.write_bytes(payload)
            original = bytes(payload)

            calvina = next(pilot for pilot in load_pilots(slot) if pilot.pilot_id == 0x71)
            self.assertEqual(calvina.slot_index, slot_index)
            self.assertEqual((calvina.kills, calvina.experience, calvina.pp), (61, 30_688, 412))

            result = write_pilot_kills(slot, {0x71: MAX_KILLS})
            updated_calvina = next(
                pilot for pilot in result.pilots if pilot.pilot_id == 0x71
            )
            self.assertEqual(updated_calvina.kills, MAX_KILLS)
            updated = path.read_bytes()
            changed = [index for index, pair in enumerate(zip(original, updated)) if pair[0] != pair[1]]
            kills_offset = record + PILOT_KILLS_IN_RECORD
            self.assertEqual(changed, [kills_offset, kills_offset + 1])
            self.assertEqual(
                PILOT_RECORD_BASE + PILOT_RECORD_COUNT * PILOT_RECORD_STRIDE,
                WEAPON_MASK_OFFSET - 0x10,
            )

    def test_rejects_out_of_range_kills(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            with self.assertRaisesRegex(SaveFormatError, "0 through 999"):
                write_pilot_kills(slot, {0x35: MAX_KILLS + 1})

    def test_parts_update_preserves_equipped_counts_and_unlocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            original = (slot / "SYSDATA.SAV").read_bytes()
            parts = {part.part_id: part for part in load_parts(slot)}
            self.assertEqual((parts[1].available, parts[1].equipped, parts[1].total_owned), (0, 3, 3))
            self.assertTrue(parts[2].locked)
            self.assertEqual((parts[3].available, parts[3].equipped, parts[3].total_owned), (2, 2, 4))

            result = write_parts(slot, {1: MAX_PARTS, 2: MAX_PARTS})

            after = {part.part_id: part for part in result.parts}
            self.assertEqual((after[1].available, after[1].equipped, after[1].total_owned), (96, 3, 99))
            self.assertEqual((after[2].available, after[2].equipped, after[2].total_owned), (99, 0, 99))
            backup = {part.part_id: part for part in load_parts(result.backup_path)}
            self.assertEqual((backup[1].available, backup[1].total_owned), (0, 3))
            self.assertTrue(backup[2].locked)
            updated = (slot / "SYSDATA.SAV").read_bytes()
            changed = [index for index, (old, new) in enumerate(zip(original, updated)) if old != new]
            self.assertEqual(
                changed,
                [PART_AVAILABLE_OFFSET, PART_AVAILABLE_OFFSET + 1, PART_TOTAL_OFFSET, PART_TOTAL_OFFSET + 1],
            )

    def test_parts_total_cannot_drop_below_equipped_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            with self.assertRaisesRegex(SaveFormatError, "3 equipped"):
                write_parts(slot, {1: 2})

    def test_ability_update_preserves_equipped_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            original = (slot / "SYSDATA.SAV").read_bytes()
            abilities = {ability.ability_id: ability for ability in load_abilities(slot)}
            self.assertEqual(
                (abilities[1].available, abilities[1].equipped, abilities[1].total_owned),
                (0, 3, 3),
            )
            self.assertEqual(
                (abilities[2].available, abilities[2].equipped, abilities[2].total_owned),
                (1, 3, 4),
            )

            result = write_abilities(slot, {1: ABILITY_STOCK_TARGET, 2: 10})

            after = {ability.ability_id: ability for ability in result.abilities}
            self.assertEqual((after[1].available, after[1].equipped, after[1].total_owned), (96, 3, 99))
            self.assertEqual((after[2].available, after[2].equipped, after[2].total_owned), (7, 3, 10))
            backup = {ability.ability_id: ability for ability in load_abilities(result.backup_path)}
            self.assertEqual((backup[1].available, backup[1].total_owned), (0, 3))
            self.assertEqual((backup[2].available, backup[2].total_owned), (1, 4))
            updated = (slot / "SYSDATA.SAV").read_bytes()
            changed = [index for index, (old, new) in enumerate(zip(original, updated)) if old != new]
            self.assertEqual(
                changed,
                [
                    ABILITY_AVAILABLE_OFFSET + 1,
                    ABILITY_AVAILABLE_OFFSET + 3,
                    ABILITY_TOTAL_OFFSET + 1,
                    ABILITY_TOTAL_OFFSET + 3,
                ],
            )

    def test_ability_total_cannot_drop_below_equipped_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            with self.assertRaisesRegex(SaveFormatError, "3 equipped"):
                write_abilities(slot, {1: 2})

    def test_ability_accepts_post_game_total_above_99(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            sysdata_path = slot / "SYSDATA.SAV"
            sysdata = bytearray(sysdata_path.read_bytes())
            struct.pack_into(">H", sysdata, ABILITY_AVAILABLE_OFFSET + 2, 89)
            struct.pack_into(">H", sysdata, ABILITY_TOTAL_OFFSET + 2, 101)
            sysdata_path.write_bytes(sysdata)

            ranged = load_abilities(slot)[1]

            self.assertEqual((ranged.available, ranged.equipped, ranged.total_owned), (89, 12, 101))
            result = write_abilities(slot, {2: MAX_ABILITIES})
            ranged_after = result.abilities[1]
            self.assertEqual(
                (ranged_after.available, ranged_after.equipped, ranged_after.total_owned),
                (32755, 12, 32767),
            )

    def test_weapon_additions_preserve_existing_instances(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            original = (slot / "PARMDAT.SAV").read_bytes()
            pilots_before = load_pilots(slot)
            weapons = {weapon.weapon_id: weapon for weapon in load_weapons(slot)}
            self.assertEqual(
                (weapons[0x10].available, weapons[0x10].equipped, weapons[0x10].total_owned),
                (0, 1, 1),
            )
            self.assertEqual(weapons[0x10].copies[0].upgrade_level, 10)
            self.assertEqual(
                (weapons[0x14].available, weapons[0x14].equipped, weapons[0x14].total_owned),
                (1, 0, 1),
            )

            result = write_weapon_totals(
                slot, {0x10: WEAPON_TARGET_COPIES, 0x14: WEAPON_TARGET_COPIES}
            )

            after = {weapon.weapon_id: weapon for weapon in result.weapons}
            self.assertEqual((after[0x10].available, after[0x10].equipped, after[0x10].total_owned), (3, 1, 4))
            self.assertEqual((after[0x14].available, after[0x14].equipped, after[0x14].total_owned), (4, 0, 4))
            self.assertEqual(after[0x10].copies[0], weapons[0x10].copies[0])
            self.assertEqual(load_pilots(slot), pilots_before)
            self.assertEqual((result.backup_path / "PARMDAT.SAV").read_bytes(), original)

            updated = (slot / "PARMDAT.SAV").read_bytes()
            changed = [index for index, (old, new) in enumerate(zip(original, updated)) if old != new]
            added_record_ids = [
                WEAPON_SLOT_BASE + slot_index * WEAPON_SLOT_STRIDE
                for slot_index in range(3, 9)
            ]
            self.assertEqual(
                changed,
                [WEAPON_MASK_OFFSET + 2, WEAPON_MASK_OFFSET + 3, *added_record_ids],
            )

    def test_weapon_editor_rejects_removal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            with self.assertRaisesRegex(SaveFormatError, "add-only"):
                write_weapon_totals(slot, {0x10: 0})

    def test_weapon_table_accepts_slot_224_and_ignores_reserved_slot_255(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            parmdat_path = slot / "PARMDAT.SAV"
            parmdat = bytearray(parmdat_path.read_bytes())
            last_mask_word = WEAPON_MASK_OFFSET + (WEAPON_MASK_WORD_COUNT - 1) * 4
            struct.pack_into(">I", parmdat, last_mask_word, 0x80000001)
            record = WEAPON_SLOT_BASE + 224 * WEAPON_SLOT_STRIDE
            parmdat[record : record + WEAPON_SLOT_STRIDE] = bytes((2, 0, 0))
            parmdat_path.write_bytes(parmdat)

            weapons = {weapon.weapon_id: weapon for weapon in load_weapons(slot)}
            self.assertEqual(WEAPON_SLOT_COUNT, 255)
            self.assertEqual(weapons[2].copies[0].slot_index, 224)
            self.assertEqual(
                struct.unpack_from(">I", parmdat_path.read_bytes(), last_mask_word)[0],
                0x80000001,
            )

            with self.assertRaisesRegex(SaveFormatError, "reserved replacement-weapon mask slot 255"):
                write_weapon_totals(slot, {2: 2})

    def test_rejects_total_lower_than_current_funds(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            slot = _make_slot(Path(temp))
            sysdata_path = slot / "SYSDATA.SAV"
            sysdata = bytearray(sysdata_path.read_bytes())
            struct.pack_into(">I", sysdata, TOTAL_FUNDS_OFFSET, 1)
            sysdata_path.write_bytes(sysdata)
            with self.assertRaisesRegex(SaveFormatError, "lower than current"):
                load_save(slot)

    def test_rejects_system_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            slot = _make_slot(root)
            renamed = root / "BLJS10335_OMI-SYS"
            slot.rename(renamed)
            with self.assertRaisesRegex(SaveFormatError, "scenario saves"):
                load_save(renamed)


if __name__ == "__main__":
    unittest.main()

# Moon Dwellers save layout investigation

Updated: 2026-09-21. Target: BLJS10335 RPCS3 scenario saves. All offsets below are file offsets and all multibyte save values are big-endian.

| File / field | Offset / layout |
| --- | --- |
| SYSDATA.SAV size | 26,164 (0x6634) bytes |
| Current funds | u32 at 0x280 |
| Total earned funds | u32 at 0x284 |
| Completed games | signed nonnegative i32 at 0x2AC; editor input 0–99 |
| Counter bank / clear-data flag | u32 at 0x258 / 0x2A8; read-only, bank must be 0 |
| Part ID 1 available / total | u8 at 0x529 / 0x64D; 43 known IDs; 0xFF means locked |
| Ability ID 1 available / total | u16 at 0x56A / 0x68E; 21 known IDs; 0xFFFF means locked |
| PARMDAT.SAV size | 137,624 (0x21998) bytes |
| Pilot table | 0x1BC44 + slot * 0x48, 256 records; ends at 0x20444 |
| Pilot ID / kills / EXP / PP | record + 0x0C / 0x12 / 0x14 / 0x16, u16 |
| Pilot skills | record + 0x35 through +0x40: six pairs of u8 skill ID, u8 learned levels |
| Weapon occupancy | Eight u32 words at 0x20454; low-bit-first within each word |
| Weapon copies | 255 three-byte records at 0x20475; ID, status, zero padding |
| Weapon status | High nibble = upgrade level; 0x08 equipped; 0x04 new |

The previous 2nd OG save offsets are incompatible. Moon Dwellers moved the tables and enlarged pilot records. Its ability counters are signed 16-bit with a -1 sentinel, rather than the previous editor's single-byte counters. ID 0 is the dummy slot: ability ID 1 begins at 0x56A, not 0x56C.

The pristine local ELF used for offline inspection is `work/poc/text_layout_20260905/EBOOT.elf`, SHA-256 `75ff8885b5c1b7336cb420fd4afd487d8f08aee58779d85f31bb50c46b8489d0`. `qa/sysdata_disassembly.txt` records 0x183000–0x194000 from this ELF.

Relevant executable evidence:

- 0x39A5AC returns SYSDATA serialized size 0x6634.
- 0x184960–0x184A0C implements current/earned funds at runtime structure +0xA38/+0xA3C. Positive awards update both; expenditure can update current alone. The fields are treated as signed 32-bit.
- Serialization at 0x1898C8 / 0x189904 copies these funds fields. Three real slots show current/total pairs 3,896/133,896 and 7,936/262,936, preserving spent values 130,000 and 255,000.
- 0x184FC8 and 0x184FF4 read part counts from runtime +0xCE0+ID and +0xE04+ID. 0x192430 caps stock at 99. Runtime serializer copies the 64-entry part region before the ability region.
- 0x185020 reads ability total at runtime +0xE44+2*ID. 0x185054 increments available at +0xD20+2*ID and caps it at 0x7FFF; 0x1850CC handles the locked sentinel. 0x18A2B0–0x18A398 serializes 64 two-byte entries starting at runtime +0xD20.
- Pilot tables have plausible named IDs, PP, kills and EXP across all three slots, with 14, 14 and 29 recruited pilots. All remaining records are scanned. The table boundary meets the weapon section with a 16-byte intervening structure.
- Weapon masks and all occupied records agree in each slot (14, 14 and 31 copies). The standalone catalog comes from the current English release's native FIXH tables; group-zero WeaponData entries map the 53 supported weapon IDs (ID 0x26 is absent).

The current English save DETAIL text is just route information and has no funds label. Funds editing preserves that SFO byte for byte. If a supported save has a recognized Japanese/English funds label, the editor validates and synchronizes it instead.

The bundled name catalog uses the v12 English Logic archive with current `script_editor/edits/project.json` short-name overrides applied. The edits hash is recorded in `names.json`; this reconciles recent corrections absent from that release archive.

`qa/real_save_verification.json` records all inspected original file hashes and each disposable edit result. Copy roundtrips establish parser/write consistency and preservation, but do not substitute for loading an edited slot in-game. Physical PS3 signing and PS4 save layouts are outside this implementation.

## Version 1.1: skills and completed games

Target-specific executable evidence is also retained in `qa/skills_progress_disassembly.txt`:

- Pilot serialization at 0x1DA560–0x1DA610 interleaves runtime skill IDs +0x2A..+0x2F and learned levels +0x30..+0x35 into the six on-disk pairs. Deserialization at 0x1DA034 reverses that mapping. The runtime pilot stride is 0x4C; the serialized record stride remains 0x48. Do not copy runtime offsets directly into a save.
- Native defaults at 0x1A8900 call 0x14BB84 for each slot. That getter reads PilotData +0x96 + slot*10; the next nine bytes are unlock levels (0x14BAAC). Runtime key 0x157 computes natural levels and key 0x159 reads learned levels. 0x1ECFDC–0x1ED03C adds them for SP Up. Pilot level is EXP//500+1, capped at 99 (0x1DD1A8, 0x19CA10).
- Natural progression is tied to the original slot; substituted skills have no natural levels. The standalone `skills.json` records these six native profiles per pilot plus SkillData names/level flags. Allowed trained levels reserve room for the entire natural growth curve. Leveled skill ranges are bounded by the highest populated native PP-cost entry or observed native growth level, rather than guessed byte limits. Catalog placeholders 0/1 are empty/reserved; only named IDs 2–44 may be added. Battle-specific bonuses are not represented in the editor's natural-level label.
- Completed-game getter 0x184ACC reads runtime +0xA64 + 4*counter-bank. The MD reset at 0x192D58 forces bank zero. The getter feeds 0x399A70, then 0x3A5158 stores it in save-description +0x40. The SFO formatter at 0x3A1038 computes min(count+1,99), subtracts the clear-data flag, and formats ProgStr ID 0x203 (Game Mode / Laps).
- Serialization at 0x189B5C places runtime +0xA64 at file 0x2AC. In that serializer's region, destination r3 is file+0x3D, so r3+0x26F = 0x2AC. The same mapping puts known funds +0xA38 at file 0x280. +0xA10 is file 0x258 and +0xA60 is file 0x2A8. These neighboring fields and other completion counters stay untouched.
- Runtime +0xA98 / file 0x2E0 is **not** the completed-game counter: stage progression resets it. It is excluded from this editor feature.

`qa/skills_progress_verification.json` records two independent writes per copied slot, with exact changed offsets, matching backups and original hashes. New synthetic tests cover the final pilot record (index 255), invalid/duplicate skills, growth limits, unknown counter banks, unchanged neighboring fields, metadata synchronization, stale snapshots and rollback. In-game normal-Load validation is pending.

## Version 1.2: mech skills

`qa/mech_skills_disassembly.txt` retains the target executable evidence:

- Unit version is the big-endian float 3.0 at PARMDAT file +8. Eight occupancy words start at +0x0C, low bit first. There are 256 serialized unit records at +0x2C, stride 0x1BC. Unit ID is record +0. The native serializer 0x1DB3A0 translates runtime stride 0x1E4 into this packed layout. Do not use runtime offsets in save files.
- Native runtime unit +0x25..0x27 become saved record +0x23..0x25: three one-byte equipped AbilityElement IDs, zero means Empty. Getter key 0x6A (0x1EE3E4) reads these slots. Unit creation at 0x1CDA80..0x1CDAFC accounts for the same three bytes against SYSDATA Ability inventory; pilot equipment uses runtime +0x36..0x38 and the existing editor's pilot-relative saved +0x41..0x43.
- Setter key 0x6A (0x1F38E8) propagates equipment changes recursively through runtime +0/+4/+8 links when flag 0x08 is set. These are saved at record +0x12/+0x16/+0x1A, each a u16 flag followed by a signed i16 unit-record index (-1 means absent). The editor computes the connected group, requires equal equipment across linked forms, writes every member, and charges inventory once. Groups plus pilot equipment exactly match total-minus-available inventory for every Ability type across the six distinct real saves.
- Runtime unit +0x54 is saved at record +0x4F as a u32. Built-in enable flags are bits 7..11 (mask 0xF80). Getter key 0x7E at 0x1E8950 and setter at 0x1F3788 test/set/clear these five bits without changing the other flags. The native setter does not propagate these flags to linked forms; neither does the editor.
- Built-in ability getter key 0x7A at 0x1EF260 reads five IDs from UnitData +0x46..0x4A using getter 0x1475FC and checks the enable mask. IDs are fixed game data, not replaceable save slots. This release offers enable/disable only; empty-slot flags remain unchanged. It does not inject HP Regen, barriers or other skills into a mech that lacks them, nor edit game archives.
- `mechs.json` includes the native UnitData and AbilityData labels, five built-in IDs per unit, source hashes and current mech-name corrections. `build_mech_catalog.py` reproduces it from the workspace's extracted native tables. Built-in labels assume those unit definitions; a custom gameplay mod may assign different IDs.
- The unit table ends at 0x1BC2C. The actual packed pilot records start at 0x1BC50 after a 0x24-byte pilot header; the earlier pilot editor deliberately indexes from 0x1BC44 with its ID offset +0x0C, which addresses the same bytes. That existing indexing is retained for compatibility.

Mech equipment writes change PARMDAT's selected group slots and SYSDATA's available counters only. Total ownership, pilot equipment, unit occupancy, IDs, links, weapons and upgrades stay unchanged. Full equipment counts are verified before and after preparation; insufficient stock, conflicting linked edits, unknown IDs/versions and inconsistent links/counters are rejected before backup. Built-in edits change only selected enable bits. The existing snapshot/lock/backup/atomic-write guards apply to both files, with restoration attempted for every affected file on ordinary failure.

`qa/mech_skills_verification.json` records combined equipment/enable writes on nine copied save folders, exact changed offsets, original hashes and byte-identical restoration. Tests also cover record 255, repeated Abilities, transfers with no spare stock, empty built-in slots, cross-file readback failure, stale snapshots, GUI staging and inventory refresh. These checks do not establish in-game persistence or visual behavior; a normal in-game Load test is still pending.

## Version 1.4: pilot Will and Seishin boundary

- The packed pilot record's saved/base Will byte is `record + 0x2F`. Across the inspected real saves, unmodified values cluster at 100, 105 and 110. The editor reads/writes only that byte for Will and validates the exact readback after an atomic write.
- The six Seishin/Spirit Command IDs are **not** serialized as per-pilot command IDs in the packed scenario record. They come from the game's pilot parameter data. The public PS3 EBOOT override points at `0x00659084`, `0x006591B0`, `0x00659224`, `0x006592A0`, `0x0065931C`, and `0x00659398` replace Spirit slots 1–5/Twin globally while enabled. The editor's Seishin tab is therefore a patch generator, not a save writer.
- Public helpers used by the generator are `0x001EB9B4` and `0x001F26A0` for zero SP cost and `0x001E397C` for ignoring Spirit unlock level. These EBOOT modifications are intentionally kept separate from save mutation.


## Version 1.5: pilot status

The actual packed pilot begins at `0x1BC50`; the existing parser's legacy start is `0x1BC44`, twelve bytes earlier. Records have stride `0x48`. The section version at `0x1BC2C` must be big-endian float 2.0. Native runtime offsets and packed offsets agree for the fields below; this is independently checked by executing serializer `0x1DA2C4..0x1DA500` and deserializer `0x1D9D8C..0x1D9FCC` with distinct source bytes.

| Field | Runtime / packed offset | Legacy editor relative offset |
| --- | --- | --- |
| EXP | u16 +0x08 | +0x14 |
| Melee training | u16 +0x0C | +0x18 |
| Ranged training | u16 +0x0E | +0x1A |
| Skill training | u16 +0x10 | +0x1C |
| Evade training | u16 +0x12 | +0x1E |
| Defense training | u16 +0x14 | +0x20 |
| Hit training | u16 +0x16 | +0x22 |
| Air/Land/Water/Space training | four u8 +0x18..+0x1B | +0x24..+0x27 |

Combat getter keys 0x119..0x11E add native growth and training, plus contextual bonuses, then cap at 400. The raw training setters also cap at 400. The status form displays personal totals (natural growth + training), excluding contextual bonuses. It allows new training 0..400 and retains unchanged pre-existing raw values. Editing an unchanged displayed capped total does not truncate its original training.

The growth routine at `0x1DC508` selects base values from PilotData +0x15..+0x1A, curve IDs +0x11B..+0x120 and signed corrections +0x122..+0x127. The native growth table starts at `0xDC244C`, with 3 curves of 99 bytes per stat (297 bytes per group, group 0 is SP). Result: base + trunc(curve[level-1] * (curve[98]+correction) / curve[98]). The verifier executes the arithmetic instruction sequence at `0x1DC598..0x1DC608` and compares every supported pilot/stat/level. PilotData/ELF SHA-256 are bundled with the catalog.

EXP setter `0x1F73B8` clamps the stored u16 to 0..65535 (`0x1F7464..0x1F748C`). Level getter caps EXP at 49000 before EXP//500+1. Changing EXP does not modify the learned-skill records or natural-growth flags; the game derives natural levels again when loading.

Terrain getters at `0x1F1D70`, `0x1F2338`, `0x1F2140` and `0x1F1F58` add the respective saved training byte to PilotData +0x2B..+0x2E, cap at 5, and then apply contextual effects. Ratings are 0 none, 1 D, 2 C, 3 B, 4 A, 5 S. The UI writes the difference between the selected rating and native default. It permits lowering trained ratings back to the native default, and does not change UnitData or mech terrain.

`qa/status_native_verification.json` records instruction/copy checks and 129492 arithmetic comparisons. `qa/status_real_saves.json` records original hashes, selective byte changes, verified backups and exact reversal on temporary copies. Tests cover mixed PP/kills/Will/status writes, rollback, stale snapshots, bad input, unsupported versions, capped values, level synchronization, filtering and refreshed skill-level previews. Runtime/in-game validation remains pending.

## Version 1.6: native weapon definitions

Entry `/Dat/FixedData/WeaponData.dat` in Logic contains 856 physical records, each 84 bytes. Record zero is the dummy and is excluded; the remaining 855 definitions include 53 equippable types and built-in weapon variants. The two-byte big-endian unit ID and byte slot at record +0/+2 identify the native weapon lookup (`0x13A390`, indexed by unit << 16 plus slot). These are game-wide definitions, separate from replacement-weapon save records or current remaining ammunition.

| Field | Record byte offset | Native load instruction |
| --- | --- | --- |
| Base attack | +0x0C, big-endian u16 | 0x13B20C: lhz r3, 0x0C(r3) |
| Minimum range | +0x0E, u8 | 0x13B068: lbz r3, 0x0E(r3) |
| Maximum range | +0x0F, u8 | 0x13B044: lbz r3, 0x0F(r3) |
| Maximum ammo | +0x14, u8 | 0x13B020: lbz r3, 0x14(r3) |
| EN cost | +0x15, u8 | 0x13AFFC: lbz r3, 0x15(r3) |

Native unsigned loads are asserted against pristine ELF SHA-256 `75ff8885b5c1b7336cb420fd4afd487d8f08aee58779d85f31bb50c46b8489d0`. Base-power calculation calls the table reader at 0x201E38 / 0x2022D0, adds upgrade and bonus values and stores the result as a 32-bit value. This is offline field evidence, not an in-game boundary-value test. Some combination attack definitions have zero stored base power and use additional native calculations.

The supported structure fingerprint masks only these six editable bytes and the two translated name-pointer bytes at +4/+5. Unit, slot, attributes, terrain, MAP shapes, flags, prerequisites, hit/critical adjustments, animation references, table mapping and every other record byte remain strict. The writer checks byte differences against selected records only. The original catalog supports restoring these fields without restoring Japanese text or changing other game data.

The archive transaction is adapted from the Pilot Editor's verified SDAT/PSARC workflow. It verifies all SDAT blocks, every decoded archive entry, output size and timestamp, a full backup, atomic replacement and post-write readback. Exact backup restore requires a matching target and latest archive snapshot. See `qa/weapon_archives.json`, `qa/weapon_ui.json` and `qa/tests_1_6.txt` for offline results. `in_game_test` remains false.

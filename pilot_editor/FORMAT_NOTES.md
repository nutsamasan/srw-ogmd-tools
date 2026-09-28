# Pilot field evidence

Target: PS3 BLJS10335. Inspected read-only from the pristine native ELF at `work/poc/text_layout_20260905/EBOOT.elf`, SHA-256 `75ff8885b5c1b7336cb420fd4afd487d8f08aee58779d85f31bb50c46b8489d0`.

## Spirit Command definitions

`PilotData.dat` uses 336-byte FIXH records and a sparse logical-to-physical index. Five normal slots plus one Twin slot start at record `0x72`, stride 6. The fields are command ID (`+0`, unsigned byte), reserved (`+1`, preserved), SP cost (`+2`, big-endian u16), unlock level (`+4`, signed byte), and an additional condition byte (`+5`, preserved for existing populated slots).

The native getters are `0x14C094` (ID), `0x14BFCC` (cost), `0x14BF04` (level) and `0x14BE3C` (additional byte); their scaled indexes compute `slot * 6`. The sixth slot begins at `0x90`; the following skill table starts at `0x96`. No seventh command is added. Empty slots use ID 0 and `FFFF/FF/FF`; newly populated slots use additional byte 0. Three stock populated slots use additional byte -1, which this editor preserves. Exact defaults retain all native values, including unusual stock configurations.

Command names and descriptions come from the local official-English `SpiritData` conversion, excluding dummy IDs 0/1 from named command choices. Current reconciled pilot names come from `save_editor/names.json`.

## Will behavior

Native getter `0x14A564` reads the unsigned byte at PilotData `+0x13`. Its runtime wrapper `0x1E3F60` is getter key `0x104`; current Will key `0x110` maps to wrapper `0x1EE07C`. The dispatch table maps both, and the known skill keys `0x157/0x159`, consistently.

The battle path at `0x3F05C0` queries key `0x104`; `0x3F08F0..0x3F0944` uses that value to index six-word response profiles at `0xDC3EF0 + 0x5C4 + type*24`. Stock PilotData uses types 0–11. The UI names profiles by verified donor-pilot membership. Changing the pilot's profile uses the existing gain/loss logic; the global response table and executable are untouched.

Version 1.1 labels the six signed response words, in native order: **hit, miss, evade, take damage, own defeat bonus, allied unit lost**. The hit path loads `+0x5C4` at `0x3EBF6C` and checks skill 28 (Will+ Hit). The other attack branch loads `+0x5C8` at `0x3EB9A8`. The defender paths load `+0x5CC` at `0x3EBB68` with skill 27 (Will+ Evade), and `+0x5D0` at `0x3EBDD8` with skill 29 (Will+ Damage). These named skill IDs are cross-checked against the local English SkillData conversion.

The fifth word is an **extra** defeat bonus, not a complete battle delta. The defeat path starts from the defeated-unit count (`r19` -> `r31` at `0x3F0618`), then adds the fifth word at `0x3F0910`; the Twin partner path includes a subtraction at `0x3F094C`. Skill 30 (Will+ Destroy) and other bonuses are added separately. For a normal single defeat, a raw +3 thus contributes +4 including the ordinary +1; hit gains are a separate calculation. The guide displays the raw bonus and explains this distinction instead of mislabeling raw +3 as the entire defeat gain.

The sixth word is used in `0x3DFAE4..0x3E0038`: this enumerates other deployed units, checks the same side with getter `0x195`, and adds the signed response to each pilot through `0x6CEB5C`. At `0x3DFD54` it adds `0x10` to the profile address and loads `+0x5C8` at `0x3DFD78` (total sixth-word offset `0x14`). Its caller `0x631250` is in the unit-removal path, immediately following `0x71765C`. Thus this column concerns an allied unit being lost, rather than an ally defeating an enemy. Disassembly excerpts and instruction/value checks are saved by `qa/verify_behavior.py`.

These event labels and values describe the native base response components. Twin/support/MAP behavior, barriers, skills, Ace bonuses, scripts, and caps can affect the final delta. No fresh in-game outcome is claimed.

## Current saved Will

The actual packed pilot section starts at `PARMDAT.SAV 0x1BC50`, with 256 records of 0x48 bytes. The pilot header at `0x1BC2C` is float **2.0**, independent of the earlier unit section's 3.0. The existing save parser indexes from `0x1BC44` with an additional 0x0C to reach each real record; that indexing is retained.

Runtime getter `0x1EE0F0` reads pilot structure byte `+0x24`. Setter `0x1F51C0` / `0x1F52AC` writes it, with minimum 50 and a cap derived from 150 plus bonuses. This is separate from the six pilot-skill IDs at runtime `+0x2A..+0x2F`.

Serializer `0x1DA2C4` copies runtime `+0x24` to packed record `+0x23`, via instructions `0x1DA4F4..0x1DA4FC`. Deserializer `0x1D9D8C` reverses that mapping at `0x1D9FC4..0x1D9FC8`. `qa/verify_native.py` executes the unrolled byte-copy paths with distinct source bytes and the actual 2.0 version comparisons, proving both directions. Thus the legacy editor-relative offset is **0x2F**, and the absolute offset is `0x1BC44 + slot*0x48 + 0x2F`.

The latest inspected normal slot is scenario 22, `BLJS10335_OMI-SCN_EXAMPLE`: 65 pilots, saved Will 100–120. All ten inspected real slots use pilot version 2.0. These observations establish data consistency, not an in-game Load outcome.

## Write boundaries

Archive edits permit only selected physical pilot records' `+0x13`, and each command slot's `+0/+2/+3/+4/+5`. Text, sort order, reserved bytes, skills, stats, and other records remain intact. Supported fingerprints normalize only these gameplay fields and proven translated text/sort pointers. Every untouched archive entry is verified during exact-size rebuilding; SDAT block verification, timestamps, snapshot checks, backup and rollback are reused from the existing patcher.

Save writes allow only selected current-Will bytes. The full save slot is fingerprinted and backed up; only PARMDAT is atomically replaced, reread and parsed. Failure triggers restoration. Backup Will restoration also writes only those bytes; it requires matching slot identity and pilot roster. These offline checks do not establish in-game persistence, which remains pending.

"""Package the confirmed caption hook without the temporary diagnostic recorder."""
import json
import struct
import zlib
from build_battle_caption_path_fix import ROOT,ASSEMBLY,HOOK,FULL_CAP,COMPACT_CAP
from native_eboot import extract_elf,sha
from build_ogmd_native_eboot import program_headers,file_offset,branch
from build_battle_text_fit import ppu_hash
from core import atomic_json
from keystone import Ks,KS_ARCH_PPC,KS_MODE_PPC64,KS_MODE_BIG_ENDIAN

BASE=ROOT/'work/poc/battle_fit_cache_20260918'
TESTED=ROOT/'work/poc/battle_caption_path_fix_20260920_v2'
OUT=ROOT/'work/poc/battle_caption_release_20260920'


def build():
    evidence=json.loads((ROOT/'reports/battle_caption_path_fix_20260920.json').read_text(encoding='utf8'))
    assert evidence['in_game_visual_test'] and evidence['visual_overflow_resolved']
    raw=(BASE/'EBOOT.BIN').read_bytes()
    assert sha(raw)=='5732c4c733fe90e989a9efdfbfe91a931794b9f5e66975a6e38485d4b5bc90dc'
    elf=extract_elf(raw)
    source_meta=json.loads((BASE/'native_eboot/assets.json').read_text(encoding='utf8'))
    h,ss=program_headers(elf);cursor=ss[0][2]+ss[0][5]
    target=ss[0][3]+cursor-ss[0][2]
    code=bytes(Ks(KS_ARCH_PPC,KS_MODE_PPC64|KS_MODE_BIG_ENDIAN).asm(ASSEMBLY,target)[0])
    payload=code+branch(target+len(code),HOOK+4)
    tested=(TESTED/'EBOOT.elf').read_bytes()
    checked=json.loads((TESTED/'build.json').read_text(encoding='utf8'))
    original_hook=checked['caption_fit_hook']
    assert original_hook['assembly']==ASSEMBLY
    assert tested[file_offset(tested,original_hook['payload_address']):file_offset(tested,original_hook['payload_address'])+len(code)]==code
    assert cursor+len(payload)<ss[1][2] and not any(elf[cursor:cursor+len(payload)])
    off=file_offset(elf,HOOK);assert elf[off:off+4].hex()=='3ac00000'
    result=bytearray(elf);result[off:off+4]=branch(HOOK,target);result[cursor:cursor+len(payload)]=payload
    end=(cursor+len(payload)+15)&~15
    struct.pack_into('>QQ',result,h[5]+32,end-ss[0][2],end-ss[0][2])
    section_at=h[6]+(h[12]-1)*h[11]
    section=struct.unpack_from('>IIQQQQIIQQ',elf,section_at)
    assert section[1:3]==(1,6)
    struct.pack_into('>Q',result,section_at+32,end-section[4])
    changes=[(off,4),(cursor,len(payload)),(h[5]+32,16),(section_at+32,8)]
    mask=bytearray(len(elf))
    for at,size in changes:mask[at:at+size]=b'\1'*size
    assert len(result)==len(elf) and all(a==b or mask[i] for i,(a,b) in enumerate(zip(elf,result)))
    # The three renderer entries are pristine, and no diagnostic BSS was added.
    for addr,word in ((0x247574,'7d800026'),(0xb7a198,'f821fbf1'),(0xb7c980,'f821fc01')):
        assert result[file_offset(result,addr):file_offset(result,addr)+4].hex()==word
    assert program_headers(result)[1][1]==ss[1]
    boot=raw[:source_meta['elf_offset']]+result;packed=zlib.compress(boot,9)
    meta={**source_meta,'elf_sha256':sha(result),'ppu':ppu_hash(result),'sha256':sha(boot),
          'compressed_sha256':sha(packed),'battle_fit_visual_tested':True,
          'plain_battle_caption_fitting':True,'battle_caption_limits':{'full':FULL_CAP,'compact':COMPACT_CAP},
          'diagnostic_recorder':False,'confirmed_battle_hook_identical':True,
          'battle_visual_test_eboot_sha256':checked['asset']['sha256'],
          'battle_visual_test_scope':'User-confirmed reported Azuki line; full/compact modes and three rows checked offline.',
          'previous_elf_sha256':'83ca939897144b713cdd195a6f0b5431cd30d2709e52e0cd8f27c4f31931408e',
          'replaces_elf_sha256':'e2c5611ca50eae01ea9e337ff0deb66f4de2d2742af71a6d329200849bf78994'}
    assets=OUT/'native_eboot';assets.mkdir(parents=True,exist_ok=True)
    for path,data in ((OUT/'EBOOT.elf',result),(OUT/'EBOOT.BIN',boot),(assets/'EBOOT.BIN.zlib',packed)):
        if path.exists():assert path.read_bytes()==data,f'Refusing to replace different {path}'
        else:path.write_bytes(data)
    atomic_json(assets/'assets.json',meta)
    atomic_json(OUT/'build.json',dict(status='built; final release verification pending',asset=meta,
        caption_fit_hook=dict(address=HOOK,payload_address=target,size=len(payload),assembly=ASSEMBLY),
        diagnostic_recorder_removed=True,tested_caption_payload_identical=True,
        existing_font_and_cache_hooks_unchanged=True,allowed_changes=[list(v) for v in changes]))
    print(json.dumps(meta,indent=2))


if __name__=='__main__':build()

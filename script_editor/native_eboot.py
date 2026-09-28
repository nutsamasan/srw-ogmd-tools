"""Verified embedded font code for RPCS3, with no runtime font YAML required."""
from pathlib import Path
import hashlib
import json
import struct
import zlib

STOCK_SHA256='38ac2f2cac4d2ce76423bb800ea46c7d8c80bad874298dfd11954936685add09'
TESTED_SHA256='e85aa2ca8e85263632a1d33ee35c80b621220bebc0a84146d8b9e3e12acf561b'
ELF_SHA256='83ca939897144b713cdd195a6f0b5431cd30d2709e52e0cd8f27c4f31931408e'
PPU='PPU-9ef8bd430c548c07aee1cc943f379bdee8e24b47'
LEGACY_ELF_SHA256=ELF_SHA256
LEGACY_PPU=PPU
PREVIOUS_BATTLE_ELF_SHA256='e2c5611ca50eae01ea9e337ff0deb66f4de2d2742af71a6d329200849bf78994'
ELF_SHA256='b013eeda2ed9cba2a85cc88c9ffe55fa89cfdab48548bebe7d4fd52a13f5a319'
PPU='PPU-9b78c49aa1bceaef78955512ec0ba63568365934'
BATTLE_CAPTION_LIMITS={'full':768,'compact':720}
KNOWN_ELFS={
    LEGACY_ELF_SHA256:LEGACY_PPU,
    PREVIOUS_BATTLE_ELF_SHA256:'PPU-28e2ebad987c46244dae8598755e29f06b58a232',
    '8550a9849ba09bafc880c8ef4bf8cc1e492f80da74ce950eb04906f58a71b6f1':'PPU-5effab33c3d4be07cfb1b9f8eba2d1f570811071',
    'bbfe215fcc54b7a76017d47e4a0881922595d2b4d2e895468264a68f1618b3a0':'PPU-dc4455702ec56cf1046a3cfee4033dc662c68581',
    '33e4921cd0dbbd17561b41efe6c71c8401eb03df41d2cb034e946709816a09be':'PPU-e4fb2176bc44ea94a0db21c0784a5ec9e47a8e1b',
    ELF_SHA256:PPU,
}
LEGACY_COMPACT_SHA256='c485b6f7479aecf74f83b5aa41fdd834bac6ba95020f5aa24de1db9059837abb'
CURRENT_COMPACT_SHA256='342dbd4e87376cbb87da3feccdf6f30e1cd73ff91ddb19c62d1146d6be1c2b8a'
UPGRADED_TEST_SHA256='4d547c2ddfecca09e2854881e438836c645c236a2b497c4c09e75f9d10683dab'
KNOWN_BOOTS={TESTED_SHA256,LEGACY_COMPACT_SHA256,CURRENT_COMPACT_SHA256,UPGRADED_TEST_SHA256,
    'af51c360ea1da41e22c2ec61bc38f6d4376691503b923c103bff3fd5357ab662',
    'ceada99a192cf4a7e75a9534b3ccc114b9c4b77cda747530dff6229cb6757079',
    '5732c4c733fe90e989a9efdfbfe91a931794b9f5e66975a6e38485d4b5bc90dc',
    '9d2d334ba7b1878337cb872a7a1b012b411acac629eef96a4f067da5b5bce307',
    '5ea79e05ea21b95cf125f8eafb0ade7c5727cf52fc896a7745ff27f9e92c32d7',
}
MODE='embedded-eboot'


def sha(data):return hashlib.sha256(data).hexdigest()


def extract_elf(raw):
    if len(raw)<32 or raw[:4]!=b'SCE\0' or raw[8:10]!=b'\x80\0':
        raise ValueError('Expected a verified RPCS3 debug SELF.')
    offset=struct.unpack_from('>Q',raw,16)[0]
    if not 32<=offset<len(raw) or raw[offset:offset+4]!=b'\x7fELF':
        raise ValueError('Invalid embedded EBOOT header.')
    return raw[offset:]


def load_asset(assets):
    assets=Path(assets)
    info=json.loads((assets/'assets.json').read_text(encoding='utf8'))
    if info.get('version')!=1 or info.get('source_sha256')!=STOCK_SHA256 or info.get('elf_sha256') not in KNOWN_ELFS or info.get('ppu')!=KNOWN_ELFS[info['elf_sha256']]:
        raise ValueError('Unrecognized embedded EBOOT asset.')
    compressed=(assets/'EBOOT.BIN.zlib').read_bytes()
    if sha(compressed)!=info['compressed_sha256']:raise ValueError('Embedded EBOOT payload checksum failed.')
    raw=zlib.decompress(compressed)
    if len(raw)!=info['size'] or sha(raw)!=info['sha256'] or sha(raw) not in KNOWN_BOOTS or sha(extract_elf(raw))!=info['elf_sha256']:
        raise ValueError('Embedded EBOOT does not contain the tested font code.')
    return info,raw


def prepare(original,assets,output,mtime_ns):
    info,raw=load_asset(assets);before=sha(original)
    if before in KNOWN_BOOTS:
        old_elf=extract_elf(original)
        if sha(old_elf) not in KNOWN_ELFS:raise ValueError('Existing embedded EBOOT differs from the verified code.')
        # Preserve the source wrapper, including the older 4 KiB test wrapper.
        raw=original[:-len(old_elf)]+extract_elf(raw)
    elif before!=STOCK_SHA256:
        raise ValueError('Unsupported EBOOT revision. Use BLJS10335 01.00 or the verified embedded-font build.')
    if len(raw)!=len(original):raise ValueError('Embedded EBOOT must fit the original file size.')
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('xb') as stream:stream.write(raw)
    return dict(file='native/EBOOT.BIN',before=before,after=sha(raw),size=len(raw),mtime_ns=mtime_ns,
                elf_sha256=info['elf_sha256'],ppu=info['ppu'],mode=MODE,rpcs3_only=True)


def validate_prepared(folder,record):
    if record.get('file')!='native/EBOOT.BIN' or record.get('mode')!=MODE or record.get('elf_sha256') not in KNOWN_ELFS or record.get('ppu')!=KNOWN_ELFS[record['elf_sha256']]:
        raise ValueError('Invalid prepared embedded EBOOT record.')
    path=Path(folder)/record['file'];raw=path.read_bytes()
    if sha(raw)!=record['after'] or len(raw)!=record['size'] or sha(extract_elf(raw))!=record['elf_sha256']:
        raise ValueError('Prepared embedded EBOOT changed.')
    return path

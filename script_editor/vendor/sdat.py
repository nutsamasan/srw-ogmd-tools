#!/usr/bin/env python3
"""
SDAT decryptor / encryptor for PS3 .psarc.sdat files.

Ported from the verified algorithm in make_npdata (Hykem) and cross-checked
against RPCS3's rpcs3/Crypto/unedat.cpp (authoritative for this game).

Only handles the SDAT case actually used by Dai-2-Ji Super Robot Taisen OG:
  flags = 0x0100003C  ->  SDAT | enc-key(0x08) | 0x10 | 0x20, no compression.
The crypto path is implemented generally enough for the common SDAT variants,
but compression (EDAT_COMPRESSED_FLAG) is intentionally NOT supported because
these files don't use it (we assert that).
"""
import struct, sys, os
from Crypto.Cipher import AES

# --- constants from make_npdata.h ---
SDAT_KEY  = bytes([0x0D,0x65,0x5E,0xF8,0xE6,0x74,0xA9,0x8A,0xB8,0x50,0x5C,0xFA,0x7D,0x01,0x29,0x33])
EDAT_KEY_0= bytes([0xBE,0x95,0x9C,0xA8,0x30,0x8D,0xEF,0xA2,0xE5,0xE1,0x80,0xC6,0x37,0x12,0xA9,0xAE])
EDAT_KEY_1= bytes([0x4C,0xA9,0xC1,0x4B,0x01,0xC9,0x53,0x09,0x96,0x9B,0xEC,0x68,0xAA,0x0B,0xC0,0x81])
EDAT_IV   = bytes(16)

SDAT_FLAG              = 0x01000000
EDAT_COMPRESSED_FLAG   = 0x00000001
EDAT_FLAG_0x02         = 0x00000002
EDAT_ENCRYPTED_KEY_FLAG= 0x00000008
EDAT_FLAG_0x10         = 0x00000010
EDAT_FLAG_0x20         = 0x00000020
EDAT_DEBUG_DATA_FLAG   = 0x80000000

def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))

def _aes_ecb_enc(key, data):
    return AES.new(key, AES.MODE_ECB).encrypt(data)

def _aes_cbc_dec(key, iv, data):
    return AES.new(key, AES.MODE_CBC, iv).decrypt(data)

def _aes_cbc_enc(key, iv, data):
    return AES.new(key, AES.MODE_CBC, iv).encrypt(data)

class NPD:
    __slots__ = ("magic","version","license","type","content_id","digest","title_hash","dev_hash","unk1","unk2")
    @classmethod
    def parse(cls, h):
        n = cls()
        n.magic = h[0:4]
        n.version, n.license, n.type = struct.unpack(">iii", h[4:16])
        n.content_id = h[16:16+0x30]
        n.digest     = h[0x40:0x50]
        n.title_hash = h[0x50:0x60]
        n.dev_hash   = h[0x60:0x70]
        n.unk1, n.unk2 = struct.unpack(">QQ", h[0x70:0x80])
        return n

class EDAT:
    __slots__ = ("flags","block_size","file_size")
    @classmethod
    def parse(cls, h):
        e = cls()
        e.flags, e.block_size = struct.unpack(">ii", h[0:8])
        e.file_size = struct.unpack(">Q", h[8:16])[0]
        e.flags &= 0xFFFFFFFF
        return e

def _block_key(block, npd):
    src = bytes(16) if npd.version <= 1 else npd.dev_hash
    return src[:0xC] + struct.pack(">I", block)

def decrypt(in_path, out_path, verbose=True):
    with open(in_path, "rb") as f:
        npd = NPD.parse(f.read(0x80))
        edat = EDAT.parse(f.read(0x10))

        if npd.magic != b"NPD\x00":
            raise ValueError("Not an NPD/SDAT file (bad magic)")
        if not (edat.flags & SDAT_FLAG):
            raise ValueError("EDAT (not SDAT) — needs a RAP/klic, not supported here")
        if edat.flags & EDAT_COMPRESSED_FLAG:
            raise ValueError("Compressed SDAT not supported (this game doesn't use it)")

        crypt_key = _xor(npd.dev_hash, SDAT_KEY)
        bs = edat.block_size
        total = (edat.file_size + bs - 1) // bs
        msize = 0x20 if (edat.flags & (EDAT_COMPRESSED_FLAG | EDAT_FLAG_0x20)) else 0x10
        use_key1 = (npd.version == 4)
        edat_key = EDAT_KEY_1 if use_key1 else EDAT_KEY_0
        iv = bytes(16) if npd.version <= 1 else npd.digest

        if verbose:
            print(f"  flags=0x{edat.flags:08X} block_size=0x{bs:X} blocks={total} size={edat.file_size}")

        with open(out_path, "wb") as out:
            for i in range(total):
                if edat.flags & EDAT_FLAG_0x20:
                    msec = 0x100 + i * (msize + bs)
                    data_off = msec + 0x20
                else:
                    data_off = 0x100 + i * bs + total * msize
                length = bs
                if i == total - 1 and edat.file_size % bs:
                    length = edat.file_size % bs
                pad_length = length
                rd_len = (pad_length + 0xF) & ~0xF

                f.seek(data_off)
                enc = f.read(rd_len)

                key_result = _aes_ecb_enc(crypt_key, _block_key(i, npd))
                # crypto_mode = AES-CBC (0x02), encrypted-key (0x10000000) since flag 0x08 set
                if edat.flags & EDAT_ENCRYPTED_KEY_FLAG:
                    key_final = _aes_cbc_dec(edat_key, EDAT_IV, key_result)
                else:
                    key_final = key_result
                dec = _aes_cbc_dec(key_final, iv, enc)
                out.write(dec[:pad_length])

                if verbose and (i % 2000 == 0 or i == total - 1):
                    print(f"    block {i+1}/{total}", end="\r")
    if verbose:
        print(f"\n  -> wrote {out_path} ({os.path.getsize(out_path)} bytes)")

import hmac, hashlib, os
def _hmac_sha1(key, data):
    return hmac.new(key, data, hashlib.sha1).digest()

def encrypt(in_path, out_path, template_sdat, verbose=True):
    """Re-encrypt a plain .psarc into SDAT, reusing the NPD/EDAT header from
    template_sdat (same dev_hash/digest => same self-derived key). Only the
    EDAT file_size is patched. Mirrors make_npdata for flags 0x0100003C."""
    with open(template_sdat, "rb") as stream:
        header = bytearray(stream.read(0x100))
    with open(in_path, "rb") as stream:
        data = stream.read()
    npd = NPD.parse(header[:0x80])
    edat = EDAT.parse(header[0x80:0x90])
    if not (edat.flags & SDAT_FLAG):
        raise ValueError("template is not SDAT")
    if not (edat.flags & EDAT_FLAG_0x20) or (edat.flags & EDAT_COMPRESSED_FLAG):
        raise ValueError("only the 0x20 non-compressed SDAT layout is implemented")

    new_size = len(data)
    struct.pack_into(">Q", header, 0x88, new_size)   # patch EDAT file_size
    crypt_key = _xor(npd.dev_hash, SDAT_KEY)
    bs = edat.block_size
    total = (new_size + bs - 1) // bs
    edat_key = EDAT_KEY_1 if npd.version == 4 else EDAT_KEY_0
    iv = bytes(16) if npd.version <= 1 else npd.digest

    with open(out_path, "wb") as out:
        out.write(header)
        for i in range(total):
            chunk = data[i*bs:(i+1)*bs]
            pad_length = len(chunk)
            length = (pad_length + 0xF) & ~0xF
            dec = chunk + b"\x00" * (length - pad_length)

            key_result = _aes_ecb_enc(crypt_key, _block_key(i, npd))
            block_hash = _aes_ecb_enc(crypt_key, key_result)              # FLAG_0x10
            key_final  = _aes_cbc_dec(edat_key, EDAT_IV, key_result)      # enc-key
            enc = _aes_cbc_enc(key_final, iv, dec)

            hmac_key = _aes_cbc_dec(edat_key, EDAT_IV, block_hash) + b"\x00"*4  # 0x14
            H = _hmac_sha1(hmac_key, enc)            # full 0x14 SHA1-HMAC
            # Metadata scheme (matches retail): the reconstructed 0x14 hash must
            # equal the full HMAC. recon[0:0x10]=hr1^hr2, recon[0x10:0x14]=hr2[0:4].
            # So hr2[0:4] MUST be H[0x10:0x14]; remaining 12 bytes are free.
            hr2 = H[0x10:0x14] + os.urandom(12)
            hr1 = _xor(H[0:0x10], hr2)

            msec = 0x100 + i * (0x20 + bs)
            out.seek(msec);        out.write(hr1 + hr2)
            out.seek(msec + 0x20); out.write(enc)
            if verbose and (i % 2000 == 0 or i == total-1):
                print(f"    enc block {i+1}/{total}", end="\r")
        out.seek(0, 2)
        out.write(bytes([0x53,0x44,0x41,0x54,0x41,0x20,0x34,0x2E,0x30,0x2E,0x30,0x2E,0x57,0,0,0]))  # SDATA 4.0.0.W
    if verbose:
        print(f"\n  -> wrote {out_path} ({os.path.getsize(out_path)} bytes)")

def verify(sdat_path, expect_plain=None, verbose=True):
    """Decrypt + check every block's HMAC exactly like RPCS3 (first 0x10 bytes).
    Returns True only if all blocks pass. If expect_plain given, also checks the
    decrypted bytes match that file."""
    with open(sdat_path, "rb") as f:
        npd = NPD.parse(f.read(0x80)); edat = EDAT.parse(f.read(0x10))
        crypt_key = _xor(npd.dev_hash, SDAT_KEY)
        bs = edat.block_size; total = (edat.file_size + bs - 1)//bs
        edat_key = EDAT_KEY_1 if npd.version == 4 else EDAT_KEY_0
        iv = bytes(16) if npd.version <= 1 else npd.digest
        out = bytearray(); bad = 0
        for i in range(total):
            msec = 0x100 + i*(0x20+bs)
            f.seek(msec); meta = f.read(0x20)
            # reconstruct the full 0x14 hash exactly as the game does
            recon = bytes(meta[j] ^ meta[j+0x10] for j in range(0x10)) + meta[0x10:0x14]
            length = bs
            if i == total-1 and edat.file_size % bs: length = edat.file_size % bs
            rd = (length + 0xF) & ~0xF
            f.seek(msec+0x20); enc = f.read(rd)
            key_result = _aes_ecb_enc(crypt_key, _block_key(i, npd))
            block_hash = _aes_ecb_enc(crypt_key, key_result)
            hmac_key = _aes_cbc_dec(edat_key, EDAT_IV, block_hash) + b"\x00"*4
            if _hmac_sha1(hmac_key, enc)[:0x14] != recon: bad += 1
            key_final = _aes_cbc_dec(edat_key, EDAT_IV, key_result)
            out += _aes_cbc_dec(key_final, iv, enc)[:length]
    ok = (bad == 0)
    if verbose: print(f"  hash check: {total-bad}/{total} blocks OK" + ("" if ok else f"  ({bad} BAD)"))
    if expect_plain is not None:
        with open(expect_plain,"rb") as stream:
            same = bytes(out) == stream.read()
        if verbose: print(f"  plaintext matches {os.path.basename(expect_plain)}: {same}")
        ok = ok and same
    return ok

if __name__ == "__main__":
    a = sys.argv
    if len(a) >= 4 and a[1] == "enc":
        encrypt(a[2], a[3], a[4])           # enc <in.psarc> <out.sdat> <template.sdat>
    elif len(a) >= 3 and a[1] == "verify":
        verify(a[2], a[3] if len(a) > 3 else None)
    elif len(a) == 3:
        decrypt(a[1], a[2])
    else:
        print("usage:\n  sdat.py <in.sdat> <out.psarc>\n  sdat.py enc <in.psarc> <out.sdat> <template.sdat>\n  sdat.py verify <file.sdat> [expected.psarc]")

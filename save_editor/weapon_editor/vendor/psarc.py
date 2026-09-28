#!/usr/bin/env python3
"""
PSARC (PlayStation Archive) reader/extractor.

Format (big-endian):
  0x00 magic "PSAR"
  0x04 version (u16 major, u16 minor)
  0x08 compression "zlib"/"lzma"
  0x0C toc_length (u32)   total size of header+TOC+blocktable = offset of first data
  0x10 toc_entry_size(u32) usually 30
  0x14 num_files (u32)    includes entry 0 = manifest
  0x18 block_size (u32)
  0x1C archive_flags (u32)
TOC entry (30 bytes):
  16  md5 of lowercase path
  4   block-list index (u32) into block-size table
  5   uncompressed size (40-bit)
  5   data offset (40-bit)
Block-size table: N entries, width = 2/3/4 bytes depending on block_size.
Entry 0 is the manifest: newline-separated paths for entries 1..n-1.
"""
import struct, sys, os, zlib

def _u40(b):
    return int.from_bytes(b, "big")

class Entry:
    __slots__ = ("name","md5","block_index","size","offset","_blocks")

def _bt_width(block_size):
    if block_size <= 0x100: return 1
    if block_size <= 0x10000: return 2
    if block_size <= 0x1000000: return 3
    return 4

class Psarc:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            hdr = f.read(32)
            if hdr[:4] != b"PSAR":
                raise ValueError("not a PSARC")
            self.ver_major, self.ver_minor = struct.unpack(">HH", hdr[4:8])
            self.compression = hdr[8:12]
            (self.toc_length, self.toc_entry_size, self.num_files,
             self.block_size, self.archive_flags) = struct.unpack(">IIIII", hdr[12:32])

            toc_raw = f.read(self.num_files * self.toc_entry_size)
            self.entries = []
            for i in range(self.num_files):
                o = i * self.toc_entry_size
                e = Entry()
                e.md5 = toc_raw[o:o+16]
                e.block_index = struct.unpack(">I", toc_raw[o+16:o+20])[0]
                e.size   = _u40(toc_raw[o+20:o+25])
                e.offset = _u40(toc_raw[o+25:o+30])
                e.name = None
                self.entries.append(e)

            bt_start = 32 + self.num_files * self.toc_entry_size
            bt_bytes = self.toc_length - bt_start
            self.bt_width = _bt_width(self.block_size)
            n_blocks = bt_bytes // self.bt_width
            bt_raw = f.read(bt_bytes)
            self.block_table = []
            for i in range(n_blocks):
                o = i * self.bt_width
                self.block_table.append(int.from_bytes(bt_raw[o:o+self.bt_width], "big"))

        # decode manifest (entry 0) to get names
        manifest = self._read_file(self.entries[0]).decode("utf-8", "replace")
        names = [ln for ln in manifest.split("\n") if ln != ""]
        for idx, e in enumerate(self.entries[1:], start=1):
            e.name = names[idx-1].strip() if idx-1 < len(names) else f"__unnamed_{idx}"
        self.entries[0].name = "__manifest__"

    def _read_file(self, e):
        out = bytearray()
        with open(self.path, "rb") as f:
            f.seek(e.offset)
            bi = e.block_index
            remaining = e.size
            while remaining > 0:
                clen = self.block_table[bi]; bi += 1
                if clen == 0:
                    # full uncompressed block
                    chunk = f.read(self.block_size)
                    if not chunk:
                        raise ValueError('Truncated PSARC data block')
                    out += chunk
                    remaining -= len(chunk)
                else:
                    raw = f.read(clen)
                    if len(raw) != clen:
                        raise ValueError('Truncated PSARC compressed block')
                    if raw[:1] == b"\x78":
                        try:
                            # decompressobj stops at stream end, ignoring trailing
                            # padding bytes (how the game's zlib behaves too)
                            chunk = zlib.decompressobj().decompress(raw)
                        except zlib.error:
                            chunk = raw
                    else:
                        chunk = raw
                    if not chunk:
                        raise ValueError('Empty PSARC data block')
                    out += chunk
                    remaining -= len(chunk)
        return bytes(out[:e.size])

    def list(self):
        for e in self.entries[1:]:
            print(f"{e.size:>12}  {e.name}")

    def extract_all(self, dest):
        os.makedirs(dest, exist_ok=True)
        for e in self.entries[1:]:
            name = e.name.lstrip("/")
            outp = os.path.join(dest, name)
            os.makedirs(os.path.dirname(outp), exist_ok=True)
            with open(outp, "wb") as fp:
                fp.write(self._read_file(e))
        # also write manifest for reference
        with open(os.path.join(dest, "__manifest__.txt"), "wb") as fp:
            fp.write(self._read_file(self.entries[0]))

    def _index_blocks(self):
        """For each entry, capture its on-disk compressed blocks as raw bytes
        (so unmodified files can be copied through byte-for-byte)."""
        with open(self.path, "rb") as f:
            for e in self.entries:
                f.seek(e.offset)
                bi = e.block_index
                remaining = e.size
                blocks = []  # list of (clen, raw_bytes)
                while remaining > 0:
                    clen = self.block_table[bi]; bi += 1
                    nbytes = self.block_size if clen == 0 else clen
                    raw = f.read(nbytes)
                    # how many uncompressed bytes this block yields:
                    if clen == 0:
                        produced = min(self.block_size, remaining)
                    else:
                        produced = len(zlib.decompress(raw)) if raw[:1]==b"\x78" else len(raw)
                    blocks.append((clen, raw))
                    remaining -= produced
                e._blocks = blocks

    def _compress_file(self, data):
        """Split into block_size chunks and compress -> list of (clen, bytes)."""
        bs = self.block_size
        maxc = (1 << (8*self.bt_width)) - 1
        blocks = []
        for o in range(0, max(len(data),1), bs):
            chunk = data[o:o+bs]
            if not chunk and o == 0:
                blocks.append((0, b"")); break
            comp = zlib.compress(chunk, 9)
            if len(comp) < len(chunk) and len(comp) <= maxc:
                blocks.append((len(comp), comp))
            elif len(chunk) == bs:
                blocks.append((0, chunk))            # full incompressible block
            else:
                # partial block: store compressed (fits since < block_size)
                blocks.append((len(comp) if len(comp)<=maxc else len(chunk),
                               comp if len(comp)<=maxc else chunk))
        return blocks

    def pack(self, dest_path, overrides=None, pad_after=None):
        """Rebuild the archive. overrides: {entry_name: new_bytes}. Names match
        entry.name (with leading '/'). Unlisted files are copied verbatim.
        Preserves the original's deduplication: entries that shared a data offset
        share it again (so structure/size match the original).
        pad_after=(entry_name, nbytes): append nbytes of NUL padding to that
        entry's LAST block (clen grows by nbytes); the trailing bytes sit after
        the valid zlib stream and are ignored on decompress. Used to hit an
        exact total .psarc size for the game's size-integrity check."""
        overrides = overrides or {}
        if not hasattr(self.entries[0], "_blocks"):
            self._index_blocks()
        n = len(self.entries)
        sizes = [0]*n
        # Decide each entry's blocks; dedup non-overridden entries by original offset.
        # emitted: list of (block_index, data_offset, blocks) actually written.
        emit_blocks = []          # ordered unique block-segments to write
        ent_blockidx = [0]*n      # per entry: index into the block table
        ent_offset   = [0]*n      # per entry: data offset
        off_to_emit  = {}         # original offset -> (block_index, data_offset)
        # First compute block table size to know data start.
        # Build emission plan (block_index assigned after we know counts):
        plan = []                 # per entry: ('ref', key)
        unique_segs = []          # (key, blks)
        seg_index_of = {}         # key -> position in unique_segs
        for i, e in enumerate(self.entries):
            ov = overrides.get(e.name)
            if ov is not None:
                blks = self._compress_file(ov); sizes[i] = len(ov)
                key = ("new", i)          # always unique
            else:
                blks = e._blocks; sizes[i] = e.size
                key = ("off", e.offset)   # dedup identical originals by offset
            if key not in seg_index_of:
                seg_index_of[key] = len(unique_segs)
                unique_segs.append((key, blks))
            plan.append(("ref", key))
        # apply exact-size padding to one entry's last block
        if pad_after:
            pad_name, pad_n = pad_after
            if pad_n < 0:
                raise ValueError(f"pad_after nbytes negative ({pad_n}); content too big, reduce it")
            if pad_n > 0:
                ei = next(i for i, e in enumerate(self.entries) if e.name == pad_name)
                key = plan[ei][1]
                si = seg_index_of[key]
                k, blks = unique_segs[si]
                blks = list(blks)
                clen, raw = blks[-1]
                if clen == 0:  # uncompressed full block — make it explicit so we can pad
                    clen = len(raw)
                blks[-1] = (clen + pad_n, raw + b"\x00" * pad_n)
                unique_segs[si] = (k, blks)
        total_table = sum(len(b) for _, b in unique_segs)
        toc_len = 32 + n*self.toc_entry_size + total_table*self.bt_width
        # assign block_index + data_offset to each unique seg
        seg_bidx = []; seg_off = []
        bidx = 0; doff = toc_len
        for key, blks in unique_segs:
            seg_bidx.append(bidx); seg_off.append(doff)
            bidx += len(blks)
            for clen, raw in blks: doff += len(raw)
        # per-entry resolve
        for i, (kind, key) in enumerate(plan):
            si = seg_index_of[key]
            ent_blockidx[i] = seg_bidx[si]
            ent_offset[i]   = seg_off[si]
        with open(dest_path, "wb") as out:
            out.write(b"PSAR")
            out.write(struct.pack(">HH", self.ver_major, self.ver_minor))
            out.write(self.compression)
            out.write(struct.pack(">IIIII", toc_len, self.toc_entry_size, n,
                                  self.block_size, self.archive_flags))
            for i, e in enumerate(self.entries):
                out.write(e.md5)
                out.write(struct.pack(">I", ent_blockidx[i]))
                out.write(sizes[i].to_bytes(5, "big"))
                out.write(ent_offset[i].to_bytes(5, "big"))
            for key, blks in unique_segs:
                for clen, raw in blks:
                    out.write(clen.to_bytes(self.bt_width, "big"))
            for key, blks in unique_segs:
                for clen, raw in blks:
                    out.write(raw)
        return dest_path

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: psarc.py <list|extract> <archive.psarc> [destdir]")
        sys.exit(1)
    cmd, arc = sys.argv[1], sys.argv[2]
    p = Psarc(arc)
    print(f"PSARC v{p.ver_major}.{p.ver_minor} comp={p.compression} files={p.num_files-1} "
          f"block_size=0x{p.block_size:X} bt_width={p.bt_width} blocks={len(p.block_table)}")
    if cmd == "list":
        p.list()
    elif cmd == "extract":
        dest = sys.argv[3] if len(sys.argv) > 3 else "extracted"
        p.extract_all(dest)
        print(f"extracted to {dest}")

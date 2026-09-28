"""Port complete English icon fonts while preserving the accepted main font."""
from pathlib import Path
import json
import struct
import numpy as np
from PIL import Image
from port_localized_textures import texture_pixels,sha,OUT,ROOT


def build():
    native_dir=OUT/'native_ui/Common/Dat/Font'
    english_dir=ROOT/'work/extracted/ps4_lang/Dat/Font/@En'
    template=(native_dir/'exFont01.bin').read_bytes()
    tbase=struct.unpack_from('>I',template,20)[0]
    gtf_template=template[tbase:tbase+128]
    assert gtf_template[24:28]==b'\xa5\x01\x02\0'
    reports=[]
    # 02-04 are pixel-identical to native. 05 contains portraits, not labels,
    # and uses a different PS4 atlas layout. Retain all four native files.
    for i in range(1,2):
        name=f'exFont{i:02d}'
        native=(native_dir/(name+'.bin')).read_bytes()
        metadata=(english_dir/(name+'.bin')).read_bytes()
        assert metadata[:4]==b'FTTF' and int.from_bytes(metadata[4:8],'big')==len(metadata)
        assert metadata[20:24]==bytes.fromhex('deadbeef') and len(metadata)%128==0
        # Every present character page points inside the complete font metadata.
        pages=struct.unpack_from('>256I',metadata,0x54)
        assert all(p==0 or 0x454<=p<=len(metadata)-1024 for p in pages)
        donor=(english_dir/'phyre'/(name+'00.dds.GNM.phyre')).read_bytes()
        pixels,info=texture_pixels(donor)
        h,w=pixels.shape[:2]
        # RSX linear A8R8G8B8 stores ARGB bytes, unlike a DDS's BGRA bytes.
        payload=pixels[:,:,[3,2,1,0]].tobytes()
        header=bytearray(gtf_template)
        struct.pack_into('>I',header,4,len(payload))
        struct.pack_into('>I',header,20,len(payload))
        struct.pack_into('>HH',header,32,w,h)
        struct.pack_into('>I',header,40,w*4)
        prefix=bytearray(metadata)
        struct.pack_into('>I',prefix,20,len(prefix))
        struct.pack_into('>I',prefix,4,len(prefix)+128+len(payload))
        result=bytes(prefix)+bytes(header)+payload
        assert len(result)==int.from_bytes(result[4:8],'big')
        assert result[24:len(prefix)]==metadata[24:]
        assert result[8:20]==native[8:20]
        assert np.array_equal(np.frombuffer(payload,np.uint8).reshape(h,w,4)[:,:,[3,2,1,0]],pixels)
        target=OUT/'ui/Common/Dat/Font'/(name+'.bin');target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(result)
        preview=OUT/'font_previews'/(name+'.png');preview.parent.mkdir(exist_ok=True)
        Image.fromarray(pixels[:,:,[2,1,0,3]]).save(preview)
        reports.append(dict(file=name+'.bin',source_sha256=sha(native),english_metadata_sha256=sha(metadata),
                            donor_texture_sha256=sha(donor),output_sha256=sha(result),source_size=len(native),
                            output_size=len(result),source_texture=info,width=w,height=h,
                            all_english_glyph_metadata_preserved=True,main_dialogue_font_untouched=True))
    for i in range(2,6):
        candidate=OUT/f'ui/Common/Dat/Font/exFont{i:02d}.bin'
        if candidate.exists():
            candidate.replace(OUT/f'font_previews/candidate_exFont{i:02d}.bin')
    (OUT/'extended_font_report.json').write_text(json.dumps(reports,indent=2),encoding='utf8')
    print(json.dumps(dict(fonts=len(reports),main_font_untouched=True,texture_bytes=sum(r['width']*r['height']*4 for r in reports))))


if __name__=='__main__':build()

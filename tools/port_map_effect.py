"""Port the English map status atlas, retaining native BC3 DDS mip storage."""
import struct,json,io
import numpy as np
from PIL import Image
from port_localized_textures import ROOT,OUT,MORTON,dds_bc_header,sha

def flip_bc3(blocks,height):
    result=blocks[::-1].copy()
    rows=min(4,height)
    alpha=np.zeros(result.shape[:2],np.uint64)
    for i in range(6):alpha|=result[:,:,2+i].astype(np.uint64)<<(8*i)
    new=alpha.copy()
    for row in range(rows):
        mask=np.uint64(0xfff)<<(12*row)
        new=(new&~mask)|(((alpha>>(12*(rows-1-row)))&np.uint64(0xfff))<<(12*row))
    for i in range(6):result[:,:,2+i]=((new>>(8*i))&255).astype(np.uint8)
    result[:,:,12:12+rows]=result[:,:,12:12+rows][:,:,::-1]
    return result

def build():
    native=(OUT/'native_ui/General3d/Dat/Particle/MapFontEffect/@Ja/edp4990_ja.edp').read_bytes()
    english=(ROOT/'work/extracted/ps4_lang/Dat/Particle/MapFontEffect/@En/edp4990_en.edp.ps4').read_bytes()
    assert native[:0x210]==english[:0x210]
    assert struct.unpack_from('>4I',native,0)==(0x50444540,0x100,62,1)
    nt,ns=struct.unpack_from('>II',native,0x210);et,es=struct.unpack_from('>II',english,0x210)
    assert nt+ns==len(native) and et+es==len(english) and (nt,et)==(0x11080,0x11070)
    dds=native[nt:];phyre=english[et:]
    assert dds[:4]==b'DDS ' and dds[84:88]==b'DXT5' and phyre[:4]==b'RYHP'
    h,w=struct.unpack_from('<II',dds,12);mips=struct.unpack_from('<I',dds,28)[0]
    assert (w,h,mips)==(1024,2048,12)
    assert struct.unpack_from('<II',phyre,0x4c)==(1,2801664)
    assert struct.unpack_from('<II',phyre,3552)==(w,h)
    words=struct.unpack_from('<8I',phyre,3568)
    assert words[2]&0x3fff==w-1 and ((words[2]>>14)&0x3fff)==h-1
    assert ((words[3]>>20)&31)==13 and ((words[4]>>13)&0x3fff)==w-1
    assert struct.unpack_from('<I',phyre,3600)[0]==mips
    raw=phyre[-2801664:];position=0;payload=bytearray();levels=[]
    for level in range(mips):
        mw,mh=max(1,w>>level),max(1,h>>level)
        bw,bh=((mw+31)//32)*8,((mh+31)//32)*8
        size=bw*bh*16;source=raw[position:position+size];position+=size
        tiles=np.frombuffer(source,np.uint8).reshape(bh//8,bw//8,64,16)
        linear=tiles[:,:,MORTON,:].reshape(bh//8,bw//8,8,8,16).transpose(0,2,1,3,4).reshape(bh,bw,16)
        inverse=linear.reshape(bh//8,8,bw//8,8,16).transpose(0,2,1,3,4).reshape(bh//8,bw//8,64,16)[:,:,np.argsort(MORTON),:]
        assert inverse.tobytes()==source
        blocks=linear[:(mh+3)//4,:(mw+3)//4]
        flipped=flip_bc3(blocks,mh)
        assert np.array_equal(flip_bc3(flipped,mh),blocks)
        a=np.asarray(Image.open(io.BytesIO(dds_bc_header(mw,mh,'DXT5',blocks.nbytes)+blocks.tobytes())).convert('RGBA'))
        b=np.asarray(Image.open(io.BytesIO(dds_bc_header(mw,mh,'DXT5',flipped.nbytes)+flipped.tobytes())).convert('RGBA'))
        assert np.array_equal(a[::-1],b),(level,'DDS pixel mismatch')
        if level==0:
            preview=OUT/'image_previews/map_status_english.png';preview.parent.mkdir(exist_ok=True);Image.fromarray(b).save(preview)
        payload.extend(flipped.tobytes());levels.append(dict(level=level,width=mw,height=mh,source_size=size,native_size=flipped.nbytes,retile_and_decoded_pixels_verified=True))
    assert position==len(raw) and len(payload)==len(dds)-128
    # Particle records have a 20-byte header and 384-byte keyframes. English
    # changes only glyph scale/position and four normalized atlas UV floats.
    changed=[]
    for k in range(62):
        offset=struct.unpack_from('>I',native,32+k*4)[0];size=struct.unpack_from('>I',native,280+k*4)[0]
        assert size in (788,1172)
        for j in range(0,size,4):
            if native[offset+j:offset+j+4]==english[offset+j:offset+j+4]:continue
            assert j>=20 and (j-20)%384 in (272,276,360,364,368,372),(k,j)
            value=struct.unpack_from('>f',english,offset+j)[0]
            assert np.isfinite(value)
            if (j-20)%384>=360:assert 0<=value<=1
            changed.append(offset+j)
    result=bytearray(native)
    for p in changed:result[p:p+4]=english[p:p+4]
    result[nt+128:]=payload
    assert len(result)==len(native) and result[:0x218]==native[:0x218]
    assert result[nt:nt+128]==native[nt:nt+128]
    target=OUT/'ui/General3d/Dat/Particle/MapFontEffect/@Ja/edp4990_ja.edp';target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(result)
    report=dict(source_sha256=sha(native),english_sha256=sha(english),output_sha256=sha(result),size=len(result),particle_records=62,changed_float_fields=len(changed),mips=levels,native_dds_header_and_container_offsets_preserved=True)
    (OUT/'map_effect_report.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report))

if __name__=='__main__':build()

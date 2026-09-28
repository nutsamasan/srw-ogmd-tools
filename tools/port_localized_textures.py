"""Losslessly detile official PS4 ARGB8 UI images into native PS3 DDS files.

Run with the bundled Python (NumPy/Pillow). Thin1DThin uses 8x8 Morton
microtiles. Platform orientation is verified byte-for-byte on shared assets.
Reference: shadPS4 src/video_core/amdgpu/tiling.h, TileMode::Thin1DThin=13.
"""
from pathlib import Path
import io
import json
import struct
import hashlib
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'work/poc/full_english_20260906'
MORTON=np.array([sum(((x>>i)&1)<<(2*i)|((y>>i)&1)<<(2*i+1) for i in range(3)) for y in range(8) for x in range(8)])

def sha(data):return hashlib.sha256(data).hexdigest().upper()


def texture_info(data):
    assert data[:4]==b'RYHP' and data[12:16]==b'\x02MNG'
    count,size=struct.unpack_from('<II',data,0x4c)
    assert count==1
    start=len(data)-size
    marker=data.rfind(b'PTexture2D\0',0,start)
    assert marker>0
    fmt=data[marker+11:data.index(0,marker+11)].decode()
    width,height,mips=struct.unpack_from('<III',data,marker-126)
    words=struct.unpack_from('<8I',data,marker-110)
    assert width==1+(words[2]&0x3fff) and height==1+((words[2]>>14)&0x3fff)
    tile=(words[3]>>20)&31
    pitch=1+((words[4]>>13)&0x3fff)
    assert 0<width<=pitch<=16384 and mips==1 and tile==13
    return dict(width=width,height=height,pitch=pitch,format=fmt,tile=tile,payload=start,size=size)


def detile_argb(data):
    info=texture_info(data)
    assert info['format']=='ARGB8'
    w,h,p=info['width'],info['height'],info['pitch']
    ph=(h+7)//8*8
    assert p%8==0 and info['size']==p*ph*4
    tiles=np.frombuffer(data[info['payload']:],dtype=np.uint8).reshape(ph//8,p//8,64,4)
    linear=tiles[:,:,MORTON,:].reshape(ph//8,p//8,8,8,4).transpose(0,2,1,3,4).reshape(ph,p,4)
    # Retile all pixels, including unused padding, to prove exact conversion.
    inverse=linear.reshape(ph//8,8,p//8,8,4).transpose(0,2,1,3,4).reshape(ph//8,p//8,64,4)[:,:,np.argsort(MORTON),:]
    assert inverse.tobytes()==data[info['payload']:]
    return np.ascontiguousarray(linear[:h,:w][::-1]),info


def dds_bc_header(width,height,fmt,size):
    header=bytearray(128);header[:4]=b'DDS '
    struct.pack_into('<7I',header,4,124,0x81007,height,width,size,0,0)
    struct.pack_into('<II4s',header,76,32,4,fmt.encode())
    struct.pack_into('<I',header,108,0x1000)
    return bytes(header)


def texture_pixels(data):
    """Return native-orientation BGRA pixels; retain every source pixel."""
    info=texture_info(data)
    if info['format']=='ARGB8':return detile_argb(data)
    assert info['format'] in ('DXT3','DXT5')
    w,h,p=info['width'],info['height'],info['pitch']
    bw,bh=(p+3)//4,((h+31)//32)*8
    assert bw%8==0 and info['size']==bw*bh*16
    tiles=np.frombuffer(data[info['payload']:],dtype=np.uint8).reshape(bh//8,bw//8,64,16)
    linear=tiles[:,:,MORTON,:].reshape(bh//8,bw//8,8,8,16).transpose(0,2,1,3,4).reshape(bh,bw,16)
    inverse=linear.reshape(bh//8,8,bw//8,8,16).transpose(0,2,1,3,4).reshape(bh//8,bw//8,64,16)[:,:,np.argsort(MORTON),:]
    assert inverse.tobytes()==data[info['payload']:]
    payload=linear.tobytes()
    dds=dds_bc_header(bw*4,bh*4,info['format'],len(payload))+payload
    rgba=np.asarray(Image.open(io.BytesIO(dds)).convert('RGBA'))[:h,:w]
    return np.ascontiguousarray(rgba[::-1,:,[2,1,0,3]]),info


def build():
    # Independent identical-art check proves PS4 vertical orientation and
    # native DDS byte order, beyond the mathematical detile roundtrip.
    shared=OUT/'native_ui/PS4/Dat/SceneTitle/Dds/st_common_00.dds.GNM.phyre'
    stock=OUT/'native_ui/Common/Dat/SceneTitle/Dds/st_common_00.dds'
    pixels,_=detile_argb(shared.read_bytes())
    assert pixels.tobytes()==stock.read_bytes()[128:]
    rows=json.loads((OUT/'localized_texture_map.json').read_text())
    reports=[]
    for row in rows:
        if not row['candidates']:continue
        name,(archive,_)=row['candidates'][0]
        source=(ROOT/row['source']).read_bytes()
        native=(OUT/'native_ui'/archive/name.lstrip('/')).read_bytes()
        pixels,info=detile_argb(source)
        assert native[:4]==b'DDS ' and len(native)>=128
        assert struct.unpack_from('<7I',native,76)==(32,65,0,32,0xff0000,0xff00,0xff)
        assert struct.unpack_from('<I',native,104)[0]==0xff000000
        nh,nw=struct.unpack_from('<II',native,12)
        resized=(nw,nh)!=(info['width'],info['height'])
        if resized:
            assert (info['width'],info['height'],nw,nh)==(1920,1080,1280,720)
            im=Image.fromarray(pixels)
            pixels=np.asarray(im.resize((nw,nh),Image.Resampling.LANCZOS))
        result=native[:128]+pixels.tobytes()
        assert len(result)==len(native)
        # The DDS decoder must show exactly our output pixels, including alpha.
        im=Image.open(io.BytesIO(result)).convert('RGBA')
        assert np.array_equal(np.asarray(im),pixels[:,:,[2,1,0,3]])
        target=OUT/'ui'/archive/name.lstrip('/');target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(result)
        reports.append(dict(source=row['source'],archive=archive,entry=name,source_sha256=sha(source),
                            original_native_sha256=sha(native),output_sha256=sha(result),size=len(result),
                            info=info,resized_to_native_resolution=resized,lossless_pixels=not resized,
                            native_dds_header_preserved=True,detile_roundtrip_verified=True))
    assert len(reports)==144
    (OUT/'localized_texture_report.json').write_text(json.dumps(reports,indent=2),encoding='utf8')
    print(json.dumps(dict(converted=len(reports),resized=sum(r['resized_to_native_resolution'] for r in reports),
                         native_headers_preserved=True,all_dds_images_verified=True)))


if __name__=='__main__':build()

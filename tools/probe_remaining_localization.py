from pathlib import Path
import sys,json,struct,io,re
sys.path.insert(0,str(Path(str(Path(__file__).resolve().parents[1] / 'script_editor/vendor'))))
from psarc import Psarc
from port_mltd_roll import parse_csb
from port_localized_textures import OUT,ROOT,texture_pixels,dds_bc_header
from PIL import Image
import numpy as np

def main():
    archives={a:Psarc(ROOT/f'work/ps3_disc/PS3_GAME/USRDIR/PSARC/{a}.psarc') for a in ['Common','General2d','General3d']}
    entries={e.name:(a,e) for a,p in archives.items() for e in p.entries}
    for path in sorted((ROOT/'work/extracted/ps4_patch0101/Dat/Archive/Csb').glob('*.csb')):
        name='/Dat/Archive/Csb/'+path.name
        a,e=entries[name]; native=archives[a]._read_file(e)
        out=OUT/'native_ui'/a/name.lstrip('/');out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(native)
        rows=[]
        for label,data in [('native',native),('english',path.read_bytes())]:
            if len(data)==24:
                rows.append(dict(label=label,size=24,empty=True));continue
            sp,ss,sc=struct.unpack_from('>III',data,0x18) # tag represented as int
            size,count=ss,sc
            body=data[0x24:0x18+size]
            texts=[t.decode('utf8',errors='replace') for t in body.split(b'\0') if t]
            try:
                c,s,r=parse_csb(data);info=dict(records=len(r),record_sample=[x['arguments'] for x in r[3:5]])
            except Exception as ex:info=dict(error=str(ex))
            rows.append(dict(label=label,size=len(data),strp_size=size,count=count,actual_nonempty=len(texts),sample=texts[:12],japanese=sum(bool(re.search('[ぁ-んァ-ヶ一-鿿]',t)) for t in texts),**info))
        print(json.dumps(dict(archive=path.name,rows=rows),ensure_ascii=True))
    for path in sorted((ROOT/'work/extracted/ps4_lang/Dat/LessonTitle/@En').rglob('*')):
        if path.suffix not in ('.bn2','.ami'):continue
        name='/'+path.relative_to(ROOT/'work/extracted/ps4_lang').as_posix().replace('/@En/','/@Ja/')
        a,e=entries[name];data=archives[a]._read_file(e);en=path.read_bytes()
        p=OUT/'native_ui'/a/name.lstrip('/');p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        print(json.dumps(dict(asset=name,source_size=len(data),english_size=len(en),diffs=sum(x!=y for x,y in zip(data,en)),native_head=data[:64].hex(),english_head=en[:64].hex())))
    for i in range(2,6):
        name=f'exFont{i:02d}';data=(OUT/f'native_ui/Common/Dat/Font/{name}.bin').read_bytes();base=int.from_bytes(data[20:24],'big');header=data[base:base+128];w,h=struct.unpack_from('>HH',header,32);raw=data[base+128:]
        im=Image.open(io.BytesIO(dds_bc_header(w,h,'DXT3',len(raw))+raw)).convert('RGBA')
        im.save(OUT/f'font_previews/{name}_native.png')
        en,info=texture_pixels((ROOT/f'work/extracted/ps4_lang/Dat/Font/@En/phyre/{name}00.dds.GNM.phyre').read_bytes())
        pixels=np.asarray(im); same=pixels.shape==en.shape and np.array_equal(pixels,en[:,:,[2,1,0,3]])
        print(json.dumps(dict(font=name,same_pixels=same,native_shape=list(pixels.shape),english_shape=list(en.shape))))

if __name__=='__main__':main()

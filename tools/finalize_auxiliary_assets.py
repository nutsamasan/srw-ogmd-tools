from pathlib import Path
import sys,json,struct,io
sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'script_editor/vendor'))
from psarc import Psarc
from port_localized_textures import ROOT,OUT,texture_pixels,sha
from PIL import Image
import numpy as np

def build():
    archives={a:Psarc(ROOT/f'work/ps3_disc/PS3_GAME/USRDIR/PSARC/{a}.psarc') for a in ['Common','General3d','Logic']}
    index={e.name:(a,e) for a,arc in archives.items() for e in arc.entries}
    reports=[]
    for path in (ROOT/'work/extracted/ps4_lang/Dat/SaveData/@En').glob('*.png'):
        name='/Dat/SaveData/'+path.name;a,e=index[name]
        native=archives[a]._read_file(e);english=path.read_bytes()
        ni,ei=Image.open(io.BytesIO(native)),Image.open(io.BytesIO(english))
        assert ni.format==ei.format=='PNG'
        ei.load()
        donor_size=ei.size
        if ni.size!=ei.size:
            ei=ei.convert('RGBA').resize(ni.size,Image.Resampling.LANCZOS)
            buf=io.BytesIO();ei.save(buf,format='PNG');english=buf.getvalue()
        dest=OUT/'ui'/a/name.lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(english)
        reports.append(dict(entry=name,archive=a,source_sha256=sha(native),output_sha256=sha(english),size=len(english),dimensions=ei.size,donor_dimensions=donor_size))
    for path in (ROOT/'work/extracted/ps4_patch0101/Dat/Archive/Picture/Dds').glob('*.phyre'):
        name='/Dat/Archive/Picture/Dds/'+path.name.replace('.GNM.phyre','');a,e=index[name]
        native=archives[a]._read_file(e);pixels,info=texture_pixels(path.read_bytes());h,w=struct.unpack_from('<II',native,12)
        ni=np.asarray(Image.open(io.BytesIO(native)).convert('RGBA'))
        assert (w,h)==(info['width'],info['height'])
        rgba=pixels[:,:,[2,1,0,3]]
        preview=OUT/'image_previews'/path.name.replace('.dds.GNM.phyre','.png');preview.parent.mkdir(exist_ok=True)
        Image.fromarray(rgba).save(preview)
        same=np.array_equal(ni,rgba)
        reports.append(dict(entry=name,source_sha256=sha(native),same_pixels=same,english_info=info,preview=str(preview)))
        if not same:
            assert native[:4]==b'DDS ' and struct.unpack_from('<II',native,80)==(65,0)
            result=native[:128]+pixels.tobytes();assert len(result)==len(native)
            dest=OUT/'ui'/a/name.lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(result)
            reports[-1].update(output_sha256=sha(result),archive=a)
    for name,(a,e) in index.items():
        if name.endswith('.wtd') or 'MapFontEffect' in name:
            data=archives[a]._read_file(e);dest=OUT/'native_ui'/a/name.lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
            reports.append(dict(entry=name,archive=a,size=len(data),head=data[:64].hex()))
    (OUT/'auxiliary_asset_report.json').write_text(json.dumps(reports,indent=2),encoding='utf8')
    print(json.dumps(reports))

if __name__=='__main__':build()

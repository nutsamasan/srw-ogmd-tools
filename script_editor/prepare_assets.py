"""Read original archives and prepare the editor's local visual resources."""
import hashlib, io, json, struct, sys
from pathlib import Path
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(__file__).resolve().parent / 'assets'
sys.path.insert(0,str(ROOT / 'script_editor/vendor'))
from psarc import Psarc


def dds_bc(width,height,payload):
    h=bytearray(128);h[:4]=b'DDS '
    struct.pack_into('<7I',h,4,124,0x81007,height,width,len(payload),0,0)
    struct.pack_into('<II4s',h,76,32,4,b'DXT5')
    struct.pack_into('<I',h,108,0x1000)
    return Image.open(io.BytesIO(h+payload)).convert('RGBA')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    font=(ROOT/'work/poc/text_layout_20260905/ps3_font_original.bin').read_bytes()
    (OUT/'font.bin').write_bytes(font)
    p=struct.unpack_from('>I',font,20)[0]
    w,h=struct.unpack_from('>HH',font,p+32)
    assert font[p+24]==0x88
    texture=dds_bc(w,h,font[p+128:])
    texture.save(OUT/'font_atlas.png')
    sample=Image.new('RGB',(1024,512),(24,28,36))
    for i,ch in enumerate(['RGBA','R','G','B']):
        crop=texture.crop((0,0,1024,128))
        if ch=='RGBA':sample.paste(crop,(0,i*128),crop)
        else:
            mask=crop.getchannel(ch);color=Image.new('RGB',crop.size,'white');sample.paste(color,(0,i*128),mask)
    sample.save(OUT/'font_inspection.png')
    a=Psarc(ROOT/'work/ps3_disc/PS3_GAME/USRDIR/PSARC/General2d.psarc')
    tiles=[]
    for e in a.entries:
        if '/Window/WindowToolData/Texture/' in e.name:
            image=Image.open(io.BytesIO(a._read_file(e))).convert('RGBA')
            image.save(OUT/(Path(e.name).stem+'.png'))
            view=Image.new('RGB',image.size,(36,38,50));view.paste(image,mask=image.getchannel('A'));view.thumbnail((480,320))
            tiles.append((e.name,view,image.size))
    contact=Image.new('RGB',(1440,360*((len(tiles)+2)//3)),(23,25,32));draw=ImageDraw.Draw(contact)
    for i,(name,im,size) in enumerate(tiles):
        x=(i%3)*480;y=(i//3)*360;contact.paste(im,(x,y+28));draw.text((x+6,y+8),f'{Path(name).name} {size}',fill='white')
    contact.save(OUT/'ui_inspection.png')
    (OUT/'provenance.json').write_text(json.dumps(dict(font_source='work/poc/text_layout_20260905/ps3_font_original.bin',
        font_sha256=hashlib.sha256(font).hexdigest(),atlas_size=[w,h],
        texture_source='General2d.psarc / Dat/Window/WindowToolData/Texture',
        preview_note='Native glyphs and proportional-width metrics; offline composition, not an emulator framebuffer.'),indent=2),encoding='utf8')
    print('Prepared native font atlas and window textures',w,h)

if __name__=='__main__':main()

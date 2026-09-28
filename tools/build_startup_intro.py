"""Encode official English frames into original PS3 movie packet allocations."""
from pathlib import Path
from fractions import Fraction
import json,re,sys,hashlib,subprocess

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/poc/startup_assets_20260915'
sys.path.insert(0,str(ROOT/'work/startup_pydeps'))
import av


def pictures(data):
    return [m.start() for m in re.finditer(rb'\x00\x00\x01\x00',data)]


def encode(q):
    types=json.loads((WORK/'original_frame_order.json').read_text(encoding='utf8'))['frames']
    codec=av.CodecContext.create('mpeg2video','w')
    codec.width=1280;codec.height=720;codec.pix_fmt='yuv420p'
    codec.time_base=Fraction(1001,30000);codec.framerate=Fraction(30000,1001)
    codec.gop_size=600;codec.max_b_frames=2;codec.bit_rate=30000000
    codec.sample_aspect_ratio=Fraction(1,1)
    codec.options={'qmin':str(q),'qmax':str(q),'sc_threshold':'1000000000','b_strategy':'0'}
    codec.open();packets=[]
    with av.open(str(ROOT/'work/investigation_startup_graphics_20260915/m_op_02_en.usm')) as source:
        count=0
        for i,frame in enumerate(source.decode(video=0)):
            frame=frame.reformat(width=1280,height=720,format='yuv420p')
            frame.pts=i;frame.time_base=codec.time_base
            frame.pict_type=getattr(av.video.frame.PictureType,types[i]['pict_type'])
            packets.extend(codec.encode(frame));count+=1
        packets.extend(codec.encode(None))
    assert count==len(types)==len(packets)==421
    (WORK/f'encoded_q{q}.m2v').write_bytes(b''.join(bytes(p) for p in packets))
    return packets


def user_data(size):
    if size<4:raise ValueError('Insufficient room for MPEG-2 user-data padding.')
    return b'\x00\x00\x01\xb2'+b'\xff'*(size-4)


def compose(packets):
    native=(WORK/'original.m2v').read_bytes();info=json.loads((WORK/'native_video_structure.json').read_text(encoding='utf8'))
    old_pics=pictures(native)
    # A native unit includes any sequence/GOP headers immediately before its picture.
    starts=[]
    for i,pic in enumerate(old_pics):
        previous=old_pics[i-1]+4 if i else 0
        seq=native.rfind(b'\x00\x00\x01\xb3',previous,pic)
        starts.append(seq if seq>=0 else pic)
    assert starts[0]==0
    # Reconstruct absolute display indices from the original GOP temporal references.
    gops=[m.start() for m in re.finditer(rb'\x00\x00\x01\xb8',native)]
    expected=[];base=0
    for start,end in zip(gops,gops[1:]+[len(native)]):
        group=[p for p in old_pics if start<=p<end]
        expected.extend(base+(int.from_bytes(native[p+4:p+6],'big')>>6) for p in group)
        base+=len(group)
    assert sorted(expected)==list(range(421))
    actual=[p.pts for p in packets]
    if actual!=expected:raise ValueError('Encoder changed picture decode order: '+str([(i,a,b) for i,(a,b) in enumerate(zip(actual,expected)) if a!=b][:12]))
    units=[];oversize=[]
    for i,(packet,start,end,pic) in enumerate(zip(packets,starts,starts[1:]+[len(native)],old_pics)):
        encoded=bytes(packet);new_pic=pictures(encoded)
        assert len(new_pic)==1
        at=new_pic[0];picture=bytearray(encoded[at:])
        assert ((picture[5]>>3)&7)==((native[pic+5]>>3)&7)
        # Retain native temporal_reference values and original GOP timecodes.
        word=int.from_bytes(picture[4:6],'big');word=(word&63)|(int.from_bytes(native[pic+4:pic+6],'big')&0xffc0)
        picture[4:6]=word.to_bytes(2,'big')
        prefix=b''
        if pic>start:
            # The first encoder packet contains the decoder configuration used by every picture.
            first=bytes(packets[0]);gop=first.index(b'\x00\x00\x01\xb8')
            config=bytearray(first[:gop])
            # Retain the native aspect/frame-rate declaration and decoder
            # bitrate/buffer allocation while using the encoder's matrices.
            config[4:8]=native[start+4:start+8]
            mask=(0x3ffff<<14)|(0x3ff<<3)
            word=int.from_bytes(config[8:12],'big');old=int.from_bytes(native[start+8:start+12],'big')
            config[8:12]=((word&~mask)|(old&mask)).to_bytes(4,'big')
            old_gop=native.rfind(b'\x00\x00\x01\xb8',start,pic)
            assert old_gop>=start
            prefix=bytes(config)+native[old_gop:old_gop+8]
            prefix+=user_data(pic-start-len(prefix))
        assert len(prefix)==pic-start
        units.append(prefix+picture)
    # Keep sequence starts, I-picture entry points, and timestamped picture
    # boundaries fixed. Intermediate pictures may share the available bytes.
    anchors={0,len(units)}
    for i,(start,pic) in enumerate(zip(starts,old_pics)):
        if start!=pic or ((native[pic+5]>>3)&7)==1:anchors.add(i)
    timestamped=[]
    for pes in info['pes']:
        head=bytes.fromhex(pes['header'])
        if head[7]&0x80:
            next_picture=next(i for i,pic in enumerate(old_pics) if pic>=pes['payload'])
            anchors.add(next_picture);timestamped.append((pes['payload'],next_picture))
    boundaries=sorted(anchors);starts_end=starts+[len(native)]
    for first,last in zip(boundaries,boundaries[1:]):
        budget=starts_end[last]-starts_end[first];needed=budget-sum(map(len,units[first:last]))
        if needed<4:oversize.append((first,last,4-needed));continue
        # Put legal user data between the last picture's extensions and slices.
        unit=units[last-1];first_slice=re.search(rb'\x00\x00\x01[\x01-\xaf]',unit).start()
        units[last-1]=unit[:first_slice]+user_data(needed)+unit[first_slice:]
    if oversize:return None,oversize
    result=b''.join(units);assert len(result)==len(native)
    new_pics=pictures(result)
    assert len(new_pics)==len(old_pics)
    for i in anchors-{len(units)}:assert new_pics[i]==old_pics[i]
    for payload,index in timestamped:
        assert next(i for i,pic in enumerate(new_pics) if pic>=payload)==index
    original=(ROOT/'work/investigation_startup_graphics_20260915/m_op_02.pam').read_bytes()
    output=bytearray(original);pos=0
    for a,b in info['spans']:
        output[a:b]=result[pos:pos+b-a];pos+=b-a
    assert pos==len(result)
    # Everything outside video PES payloads, including all private audio packets,
    # the PAMF header, sector headers, timestamps and entry points, is unchanged.
    cursor=0
    for a,b in info['spans']:
        assert output[cursor:a]==original[cursor:a];cursor=b
    assert output[cursor:]==original[cursor:]
    return bytes(output),[]


def main():
    for q in [2,3,4,5,6,8,10,12]:
        packets=encode(q);result,oversize=compose(packets)
        print(json.dumps(dict(q=q,oversized_frames=len(oversize),worst=max(oversize,key=lambda x:x[2]) if oversize else None)),flush=True)
        if result:
            output=WORK/'m_op_02.english.pam';output.write_bytes(result)
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','mpeg','-i',str(output),'-map','0:v:0','-f','null','-'],check=True)
            report=dict(status='encoded',quantizer=q,frames=421,width=1280,height=720,fps='30000/1001',
                        original_audio_packets_preserved=True,all_nonvideo_bytes_preserved=True,
                        timed_picture_and_entry_offsets_preserved=True,picture_decode_order_preserved=True,
                        pamf_header_and_timestamps_preserved=True,full_video_decode_passed=True,
                        sha256=hashlib.sha256(result).hexdigest(),size=len(result),in_game_test=False)
            (WORK/'intro_verification.json').write_text(json.dumps(report,indent=2),encoding='utf8')
            print(json.dumps(report),flush=True);return
    raise ValueError('English frames did not fit original movie allocation.')


if __name__=='__main__':main()

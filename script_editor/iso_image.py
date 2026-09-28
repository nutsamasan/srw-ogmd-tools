"""Read-only ISO9660/Joliet/UDF extent validation for PS3 disc images.

Only existing, recorded file extents are used; no filesystem is rebuilt.
UDF field layouts: ECMA-167 part 4, UDF 2.50 metadata partition maps.
"""
from __future__ import annotations
import binascii
import hashlib
import struct
from dataclasses import dataclass
from datetime import datetime,timezone,timedelta
from pathlib import Path

BLOCK=2048
CHUNK=8*1024*1024

def u16(data,offset):return struct.unpack_from('<H',data,offset)[0]
def u32(data,offset):return struct.unpack_from('<I',data,offset)[0]
def u64(data,offset):return struct.unpack_from('<Q',data,offset)[0]

def compact(extents):
    result=[]
    for offset,size in extents:
        if not size:continue
        if result and result[-1][0]+result[-1][1]==offset:
            result[-1]=(result[-1][0],result[-1][1]+size)
        else:result.append((offset,size))
    return result

def canonical(path):
    return path.upper().removesuffix(';1').replace('_PSARC.SDAT','.PSARC.SDAT')

@dataclass
class DiscFile:
    path:str
    extents:list
    inline:bool=False
    mtime_ns:int|None=None
    @property
    def size(self):return sum(n for _,n in self.extents)

class DiscImage:
    def __init__(self,path):
        self.path=Path(path).resolve();self.size=self.path.stat().st_size
        self.fp=self.path.open('rb');self.views={};self.files={};self.metadata=[]
        try:
            if self.size%BLOCK:raise ValueError('ISO length is not a multiple of 2048 bytes.')
            for sector in range(16,64):
                block=self.read(sector*BLOCK,BLOCK)
                if block[1:6]!=b'CD001':break
                if block[0] in (1,2):
                    joliet=block[0]==2
                    if joliet and block[88:91] not in (b'%/@',b'%/C',b'%/E'):continue
                    if u16(block,128)!=BLOCK:raise ValueError('Unsupported ISO sector size.')
                    if u32(block,80)*BLOCK>self.size:raise ValueError('Truncated ISO image.')
                    view={};self._iso_dir(block[156:190],'',view,joliet,set())
                    self.views['Joliet' if joliet else 'ISO9660']=view
                if block[0]==255:break
            if 'ISO9660' not in self.views:raise ValueError('An ISO9660 PS3 disc image is required.')
            # NSR identifies a UDF bridge; never silently ignore a broken UDF view.
            if any(self.read(s*BLOCK+1,5) in (b'NSR02',b'NSR03') for s in range(16,32)):
                self._udf()
            self.files=self.views.get('UDF',self.views.get('Joliet',self.views['ISO9660']))
            for name,view in self.views.items():
                if set(view)!=set(self.files):raise ValueError('The '+name+' file index disagrees with the other disc indexes.')
                for key,item in view.items():
                    if compact(item.extents)!=compact(self.files[key].extents):
                        raise ValueError('Disc indexes point to different bytes: '+item.path)
            sfo=self.file('/PS3_GAME/PARAM.SFO')
            if sfo.size>1024*1024 or b'BLJS10335' not in self.content(sfo):raise ValueError('Select an OGMD PS3 ISO (BLJS10335).')
            logic=self.file('/PS3_GAME/USRDIR/PSARC/Logic.psarc.sdat')
            if self.read(logic.extents[0][0],4)!=b'NPD\0':
                raise ValueError('The ISO game data is encrypted or unsupported. Use a decrypted OGMD PS3 ISO.')
        except Exception:
            self.close();raise

    def close(self):self.fp.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def read(self,offset,size):
        if offset<0 or size<0 or offset+size>self.size:raise ValueError('Disc extent is outside the ISO.')
        self.fp.seek(offset);data=self.fp.read(size)
        if len(data)!=size:raise ValueError('Unexpected end of ISO.')
        return data
    def file(self,path):
        try:return self.files[canonical(path)]
        except KeyError:raise ValueError('ISO file is missing: '+path) from None
    def content(self,item):
        if item.size>16*1024*1024:raise ValueError('Oversized disc metadata.')
        return b''.join(self.read(p,n) for p,n in item.extents)
    def chunks(self,item):
        for offset,size in item.extents:
            while size:
                n=min(size,CHUNK);yield self.read(offset,n);offset+=n;size-=n
    def extract(self,item,path):
        checksum=hashlib.sha256()
        with Path(path).open('xb') as out:
            for data in self.chunks(item):out.write(data);checksum.update(data)
        return checksum.hexdigest()
    def checksum(self,item):
        checksum=hashlib.sha256()
        for data in self.chunks(item):checksum.update(data)
        return checksum.hexdigest()
    def check_patch_files(self,items):
        keys={canonical(x.path) for x in items};ranges=[]
        for item in items:
            if item.inline:raise ValueError('Inline UDF files cannot be patched.')
            ranges.extend((p,p+n,item.path) for p,n in item.extents)
        ordered=sorted(ranges)
        if any(a[1]>b[0] for a,b in zip(ordered,ordered[1:])):raise ValueError('Patch extents overlap.')
        for key,item in self.files.items():
            if key in keys:continue
            if any(max(p,a)<min(p+n,b) for p,n in item.extents for a,b,_ in ranges):
                raise ValueError('Patch file overlaps another disc file: '+item.path)
        if any(max(p,a)<min(p+n,b) for p,n in self.metadata for a,b,_ in ranges):
            raise ValueError('Patch file overlaps disc metadata.')

    def _iso_dir(self,record,path,view,joliet,seen):
        offset=u32(record,2)*BLOCK;size=u32(record,10)
        if record[1] or record[26] or record[27]:raise ValueError('Interleaved/extended ISO records are unsupported.')
        if (offset,size) in seen or len(seen)>10000:raise ValueError('Invalid ISO directory tree.')
        seen.add((offset,size));self.metadata.append((offset,size))
        if size>16*1024*1024:raise ValueError('Oversized ISO directory.')
        data=self.read(offset,size);pos=0;pending=None
        while pos<size:
            n=data[pos]
            if not n:pos=(pos//BLOCK+1)*BLOCK;continue
            rec=data[pos:pos+n];pos+=n
            if n<34 or len(rec)!=n or 33+rec[32]>n:raise ValueError('Invalid ISO directory record.')
            raw=rec[33:33+rec[32]]
            if raw in (b'\0',b'\1'):continue
            label=raw.decode('utf-16-be' if joliet else 'ascii').removesuffix(';1')
            if '/' in label or '\\' in label or label in ('.','..'):raise ValueError('Invalid disc filename.')
            full=path+'/'+label;key=canonical(full)
            if rec[25]&2:
                if pending:raise ValueError('Incomplete ISO multi-extent file.')
                self._iso_dir(rec,full,view,joliet,seen);continue
            if rec[1] or rec[26] or rec[27]:raise ValueError('Interleaved ISO files are unsupported.')
            extent=(u32(rec,2)*BLOCK,u32(rec,10));self.read(extent[0],min(extent[1],1))
            if extent[0]+extent[1]>self.size:raise ValueError('Truncated ISO file.')
            if pending and pending!=key:raise ValueError('Broken ISO multi-extent sequence.')
            if key in view and not pending:raise ValueError('Duplicate ISO file.')
            try:
                zone=struct.unpack('b',rec[24:25])[0]
                stamp=int(datetime(1900+rec[18],*rec[19:24],tzinfo=timezone(timedelta(minutes=zone*15))).timestamp())*1_000_000_000
            except (ValueError,OverflowError):stamp=None
            item=view.setdefault(key,DiscFile(full,[],mtime_ns=stamp))
            if item.mtime_ns!=stamp:raise ValueError('ISO multi-extent timestamps disagree.')
            item.extents.append(extent)
            pending=key if rec[25]&128 else None
        if pending:raise ValueError('Incomplete ISO multi-extent file.')

    @staticmethod
    def _tag(data,expected=None):
        if len(data)<16 or (sum(data[:16])-data[4])&255!=data[4]:raise ValueError('UDF tag checksum failed.')
        n=u16(data,10)
        if n+16>len(data) or binascii.crc_hqx(data[16:16+n],0)!=u16(data,8):raise ValueError('UDF descriptor CRC failed.')
        tag=u16(data,0)
        if expected is not None and tag!=expected:raise ValueError('Unexpected UDF descriptor type.')
        return tag

    def _udf(self):
        anchor=self.read(256*BLOCK,BLOCK);self._tag(anchor,2)
        size,sector=u32(anchor,16),u32(anchor,20)
        if size>1024*1024:raise ValueError('Oversized UDF descriptor sequence.')
        self.metadata.extend([(0,352*BLOCK),(sector*BLOCK,size)])
        parts={};logical=None
        for p in range(sector*BLOCK,sector*BLOCK+size,BLOCK):
            b=self.read(p,BLOCK);tag=self._tag(b)
            if tag==5:parts[u16(b,22)]=(u32(b,188)*BLOCK,u32(b,192)*BLOCK)
            if tag==6:
                if logical is not None:raise ValueError('Multiple UDF logical volumes are unsupported.')
                logical=b
            if tag==8:break
        if logical is None or u32(logical,212)!=BLOCK:raise ValueError('Unsupported UDF volume.')
        maps=[];pos=440;end=pos+u32(logical,264)
        for _ in range(u32(logical,268)):
            if pos+2>end or end>BLOCK:raise ValueError('Invalid UDF partition maps.')
            kind,length=logical[pos:pos+2];m=logical[pos:pos+length]
            if kind==1 and length==6:maps.append(('physical',u16(m,4),None,None))
            elif kind==2 and length==64 and m[5:28]==b'*UDF Metadata Partition':
                maps.append(('metadata',u16(m,38),u32(m,40),u32(m,44)))
            else:raise ValueError('This UDF partition layout is unsupported.')
            pos+=length
        if pos!=end:raise ValueError('Invalid UDF partition map lengths.')
        physical={i:[parts[m[1]]] for i,m in enumerate(maps) if m[0]=='physical'}
        mapping=dict(physical);mirrors={}
        for i,(kind,part,location,mirror) in enumerate(maps):
            if kind!='metadata':continue
            ref=next((j for j,m in enumerate(maps) if m[:2]==('physical',part)),None)
            if ref is None:raise ValueError('Missing UDF physical partition.')
            item,ftype=self._udf_entry(ref,location,mapping)
            if ftype!=250:raise ValueError('Invalid UDF metadata file.')
            mapping[i]=item.extents;self.metadata.extend(item.extents)
            if mirror!=0xffffffff:
                mirror_item,ftype=self._udf_entry(ref,mirror,mapping)
                if ftype!=251:raise ValueError('Invalid UDF metadata mirror.')
                mirrors[i]=mirror_item.extents;self.metadata.extend(mirror_item.extents)
        for name,table in [('UDF',mapping)]+([('UDF mirror',{**mapping,**mirrors})] if mirrors else []):
            fsd=self._mapped_read(table,u16(logical,256),u32(logical,252)*BLOCK,BLOCK)
            self._tag(fsd,256);view={}
            self._udf_walk(u16(fsd,408),u32(fsd,404),'',table,view,set())
            self.views[name]=view

    def _mapped_extents(self,mapping,ref,offset,size):
        if ref not in mapping:raise ValueError('Unknown UDF partition.')
        result=[]
        for start,n in mapping[ref]:
            if offset>=n:offset-=n;continue
            take=min(n-offset,size);result.append((start+offset,take));size-=take;offset=0
            if not size:break
        if size:raise ValueError('UDF extent exceeds its partition.')
        return result
    def _mapped_read(self,mapping,ref,offset,size):
        return b''.join(self.read(p,n) for p,n in self._mapped_extents(mapping,ref,offset,size))
    def _udf_entry(self,ref,location,mapping):
        descriptor=self._mapped_extents(mapping,ref,location*BLOCK,BLOCK);self.metadata.extend(descriptor)
        data=self._mapped_read(mapping,ref,location*BLOCK,BLOCK);tag=self._tag(data)
        if tag not in (261,266):raise ValueError('Unsupported UDF file entry.')
        size=u64(data,56);kind=u16(data,34)&7;start=176 if tag==261 else 216
        ea,ad=u32(data,start-8),u32(data,start-4);at=start+ea;end=at+ad
        if end>BLOCK:raise ValueError('Oversized UDF allocation descriptors.')
        extents=[]
        if kind==3:
            if size>ad:raise ValueError('Truncated inline UDF file.')
            extents=self._mapped_extents(mapping,ref,location*BLOCK+at,size)
        elif kind in (0,1):
            stride=8 if kind==0 else 16
            if ad%stride:raise ValueError('Invalid UDF allocation descriptor size.')
            remaining=size
            for p in range(at,end,stride):
                length=u32(data,p)
                if length>>30:raise ValueError('Sparse or indirect UDF extents are unsupported.')
                if not remaining:continue
                take=min(length,remaining);part=ref if kind==0 else u16(data,p+8)
                extents+=self._mapped_extents(mapping,part,u32(data,p+4)*BLOCK,take);remaining-=take
            if remaining:raise ValueError('Truncated UDF file allocations.')
        else:raise ValueError('Unsupported UDF allocation type.')
        return DiscFile('',extents,kind==3),data[27]
    def _udf_walk(self,ref,location,path,mapping,view,seen):
        if len(seen)>10000 or (ref,location) in seen:raise ValueError('Invalid UDF directory tree.')
        seen.add((ref,location));item,kind=self._udf_entry(ref,location,mapping)
        if kind!=4:raise ValueError('Expected a UDF directory.')
        self.metadata.extend(item.extents);data=self.content(item);pos=0
        while pos<len(data):
            if not any(data[pos:]):break
            if pos+38>len(data):raise ValueError('Truncated UDF directory entry.')
            n=data[pos+19];impl=u16(data,pos+36);length=(38+impl+n+3)&~3
            rec=data[pos:pos+length];self._tag(rec,257);pos+=length
            if rec[18]&12:continue  # deleted / parent entry
            raw=rec[38+impl:38+impl+n]
            if not raw or raw[0] not in (8,16):raise ValueError('Invalid UDF filename encoding.')
            label=raw[1:].decode('latin1' if raw[0]==8 else 'utf-16-be')
            if '/' in label or '\\' in label or label in ('.','..'):raise ValueError('Invalid UDF filename.')
            full=path+'/'+label;part,block=u16(rec,28),u32(rec,24)
            if rec[18]&2:self._udf_walk(part,block,full,mapping,view,seen)
            else:
                child,kind=self._udf_entry(part,block,mapping)
                if kind!=5:raise ValueError('Unsupported UDF file type.')
                key=canonical(full)
                if key in view:raise ValueError('Duplicate UDF file.')
                child.path=full;view[key]=child

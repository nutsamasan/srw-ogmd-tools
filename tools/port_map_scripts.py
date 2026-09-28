"""Translate native LOGO string tables without changing any event commands."""
import json,struct,collections,re
from probe_map_scripts import ROOT,OUT,parse_logo
from port_mltd_stage import mltd_lookup,localization_hash,sha256,ps3_dialogue_text

def build():
    lookup=collections.defaultdict(list);allkeys=set()
    for f in (ROOT/'work/extracted/ps4_lang/Dat/MultiLanguage/@En/MapLogic').glob('*.mltd'):
        for key,entry in mltd_lookup(f.read_bytes()).items():
            lookup[key].append((f.stem,entry));allkeys.add((f.stem,key))
    used=set();reports=[];custom={'１．　ヒリュウ改、またはハガネの撃墜。':'１.Either Hiryu Kai or Hagwane defeated.'}
    for f in sorted((ROOT/'work/extracted/ps3_logic/Dat/logic').glob('scr*.bin')):
        source=f.read_bytes();base,tables=parse_logo(source);table=tables[1];count=table['count'];tp=table['table']
        assert struct.unpack_from('>I',source,0x58)[0]==count
        start=struct.unpack_from('>I',source,0x5c)[0]
        assert start==base+table['offsets'][0]
        oldend=base+struct.unpack_from('>I',source,tp+count*4)[0]
        assert start<=oldend<=len(source)
        values=[];rows=[]
        for index,text in enumerate(table['strings']):
            candidates=lookup.get(localization_hash(text),[])
            english=text
            if candidates:
                assert len({e.text for _,e in candidates})==1,(f.name,index)
                english=ps3_dialogue_text(candidates[0][1].text)
                used.update((name,localization_hash(text)) for name,e in candidates)
            elif text in custom:english=custom[text]
            if english!=text:
                # Dynamic numeric substitutions must survive localization.
                assert sorted(re.findall(r'#[0-9]+',english))==sorted(re.findall(r'#[0-9]+',text)),(f.name,index,text,english)
                rows.append(dict(index=index,japanese=text,english=english,source=[name for name,_ in candidates] or ['Reviewed native variant']))
            values.append(english)
        if not rows:continue
        payload=bytearray();offsets=[]
        for text in values:
            offsets.append(start-base+len(payload));payload.extend(text.encode('utf8')+b'\0')
        offsets.append(start-base+len(payload))
        end=start+len(payload)
        # Keep the native file size, all section addresses and event records.
        assert end<=len(source),(f.name,'String pool overflow',end-len(source))
        out=bytearray(source);out[start:max(oldend,end)]=bytes(max(oldend,end)-start)
        out[start:end]=payload;struct.pack_into('>'+str(count+1)+'I',out,tp,*offsets)
        assert len(out)==len(source)
        _,actual=parse_logo(out)
        assert actual[0]==tables[0] and actual[1]['strings']==values
        assert all(a==b or start<=i<max(oldend,end) or tp<=i<tp+4*(count+1) for i,(a,b) in enumerate(zip(source,out)))
        target=OUT/'ui/Logic/Dat/logic'/f.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(out)
        reports.append(dict(file=f.name,source_sha256=sha256(source),output_sha256=sha256(out),size=len(out),changed=len(rows),free_pool_bytes=len(out)-end,all_event_command_bytes_preserved=True,rows=rows))
    unused=[]
    for table,key in sorted(allkeys-used):
        entry=next(e for name,e in lookup[key] if name==table)
        unused.append(dict(table=table,key=key,english=entry.text))
    report=dict(files=reports,total_changed=sum(r['changed'] for r in reports),unused_official_entries=unused)
    (OUT/'map_script_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(files=len(reports),translated=report['total_changed'],unused_official_entries=len(unused))))

if __name__=='__main__':build()

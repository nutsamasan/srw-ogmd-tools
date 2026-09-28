"""Import official PS4 recap text into native PS3 command fields only."""
import json,re,difflib
from port_mltd_roll import parse_csb
from ogmd_text_formats import rebuild_csb
from port_localized_textures import ROOT,OUT,sha

def build():
    reports=[]
    for name in ['Archive_OG1','Archive_OG2','Archive_OGg','Archive_2OG','Archive_OGDP']:
        native=(OUT/f'native_ui/Common/Dat/Archive/Csb/{name}.csb').read_bytes()
        donor=(ROOT/f'work/extracted/ps4_patch0101/Dat/Archive/Csb/{name}.csb').read_bytes()
        _,_,nr=parse_csb(native);_,_,er=parse_csb(donor)
        edits={};rows=[];control_differences=[]
        alignment=difflib.SequenceMatcher(a=[r['arguments'][0] for r in nr],b=[r['arguments'][0] for r in er],autojunk=False).get_opcodes()
        pairs=[]
        for tag,i,j,k,l in alignment:
            if tag=='equal':pairs.extend(zip(range(i,j),range(k,l)))
            else:
                assert name=='Archive_OG1' and tag=='delete'
                assert [r['arguments'] for r in nr[i:j]] in ([['2','100','100']],[['30','60','43'],['10','60']])
                control_differences.append(dict(native_commands_preserved=list(range(i,j)),reason='PS4 omits these native transition commands'))
        for k,ek in pairs:
            n,e=nr[k],er[ek]
            na,ea=n['arguments'],e['arguments']
            assert na[0]==ea[0] and len(ea)>=len(na),(name,k,na,ea)
            for j,(a,b) in enumerate(zip(na,ea)):
                if na[0]=='42' and j==3:
                    assert na[:3]+na[4:]==ea[:3]+ea[4:len(na)],(name,k,'Text timing mismatch')
                    assert not re.search('[ぁ-んァ-ヶ一-鿿]',b),(name,k,b)
                    edits[k,j]=b
                    rows.append(dict(command=k,donor_command=ek,japanese=a,english=b))
                elif a!=b:control_differences.append(dict(command=k,argument=j,native=a,ps4=b))
        # Known PS4 update differences are logged; native commands remain.
        assert rows
        result=rebuild_csb(native,edits)
        _,_,actual=parse_csb(result)
        assert not any(re.search('[ぁ-んァ-ヶ一-鿿]',a) for r in actual for a in r['arguments'])
        target=OUT/f'ui/Common/Dat/Archive/Csb/{name}.csb';target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(result)
        reports.append(dict(file=name,source_sha256=sha(native),donor_sha256=sha(donor),output_sha256=sha(result),source_size=len(native),output_size=len(result),commands=len(nr),translated=len(rows),control_differences_preserved=control_differences,rows=rows))
    (OUT/'archive_recap_report.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(recaps=len(reports),text_pages=sum(r['translated'] for r in reports),preserved_control_differences=sum(len(r['control_differences_preserved']) for r in reports))))

if __name__=='__main__':build()

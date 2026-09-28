"""Apply reviewed English line breaks and translate twelve developer prompts."""
import json,re
from collections import defaultdict
from port_story_corpus import OUT
from ogmd_text_formats import dialogue_grid,rebuild_ldbi_pool
from port_mltd_stage import sha256

BREAKS={
 ('ls009.bin',86400):(' to Antarctica','@　to Antarctica'),
 ('ls009.bin',86988):(' you to Antarctica',' you@　to Antarctica'),
 ('ls016.bin',111772):('were at the scene','@　were at the scene'),
 ('ls016.bin',112948):(' in her comrades','@　in her comrades'),
 ('ls019.bin',116852):(" how it's going", "@　how it's going"),
 ('ls082.bin',87024):(' which side Al-Van','@　which side Al-Van'),
 ('ls082.bin',94864):(" don't attack", "@　don't attack"),
 ('ls082.bin',107408):(" to draw Fury's attention", "@　to draw Fury's attention"),
 ('ls082.bin',162288):(' “Volda\'s Gate".', '@　“Volda\'s Gate".'),
}
DEBUG={
 '「パイロットのレベルは？」':'「What level should the pilots be?」',
 '「なにもしない」;@「４５にする」;@「９９にする」':'「Leave unchanged」;@「Set to 45」;@「Set to 99」',
 '「全機体を改造しますか？」':'「Upgrade all mechs?」',
 '「なにもしない」;@「フル改造一歩手前にする」;@「フル改造する」':'「Leave unchanged」;@「One step below full upgrade」;@「Fully upgrade」',
 '「強制出撃させますか？」':'「Force deployment?」',
 '「させない」;@「させる」':'「No」;@「Yes」',
 '「出撃画面のタイプは？」':'「Which deployment screen type?」',
 '「２次ＯＧ」;@「ＯＧＤＰ」;@「ＯＧＤＰと２次ＯＧの両方」':'「2nd OG」;@「OGDP」;@「Both OGDP and 2nd OG」',
 '「以上でよろしいですか？@　それとも最初からやりなおしますか？」':'「Are these settings correct?@　Or would you like to start over?」',
 '「この設定で問題ない」;@「最初からやりなおす」':'「Use these settings」;@「Start over」',
 '「クストウェル・ブラキウムを追加しますか？」':'「Add Coustwell Brachium?」',
 '「追加しない」;@「追加する」':'「Do not add」;@「Add」',
}

def build():
    grouped=defaultdict(dict)
    for (file,p),edit in BREAKS.items():grouped[file][p]=edit
    grouped['ls990.bin']={}
    reports=[]
    for file,edits in grouped.items():
        path=OUT/'story'/file;source=path.read_bytes();variants=[];rows=[];replacements={}
        for p,index,_,text in dialogue_grid(source):
            new=text
            if p in edits:
                a,b=edits[p]
                # Idempotence permits an audit rerun without changing words.
                if b in text:pass
                else:
                    assert a in text
                    new=text.replace(a,b,1)
                norm=lambda t:re.sub(r'\s+','',t.replace('@',''))
                assert norm(text)==norm(new)
            elif file=='ls990.bin':new=DEBUG.get(text,text)
            if new!=text:
                assert text.count(';')==new.count(';') and new.count('@')<=2
                if file=='ls990.bin':
                    assert replacements.setdefault(index,new)==new
                else:variants.append((p,index,new))
                rows.append(dict(record=p,before=text,after=new))
        result,validation=rebuild_ldbi_pool(source,replacements,variants)
        path.write_bytes(result)
        reports.append(dict(file=file,source_sha256=sha256(source),output_sha256=sha256(result),changes=rows,validation=validation))
    (OUT/'story_layout_refinements.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(files=len(reports),changed_dialogues=sum(len(r['changes']) for r in reports))))

if __name__=='__main__':build()

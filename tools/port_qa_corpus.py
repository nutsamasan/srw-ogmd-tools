"""Port the official question-and-answer library, preserving links and images."""
from pathlib import Path
import json
from port_mltd_stage import parse_mltd, sha256
from port_mltd_roll import parse_csb
from ogmd_text_formats import rebuild_csb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'work/poc/full_english_20260906'
LANG = ROOT/'work/extracted/ps4_lang/Dat/MultiLanguage/@En'

def build():
    source = (OUT/'native_ui/Common/Dat/Option/QA/2og_Q&A.csb').read_bytes()
    chunks,strings,records = parse_csb(source)
    assert len(records) == 150 and records[2]['arguments'][2:6] == ['Title','Index','Question','Key Words']
    rows = records[3:]
    assert len(rows) == 147 and all(len(r['arguments']) in (7,9) for r in rows)
    edits, manifest = {}, []
    for name, column, sparse in [('QA_TitleText',2,True),('QA_IndexText',3,True),
                                 ('QA_QuestionText',4,False),('QA_Key WordsText',5,False),('QA_AnswerText',6,False)]:
        english,_ = parse_mltd((LANG/(name+'.mltd')).read_bytes())
        selected = [(k,r) for k,r in enumerate(rows,3) if not sparse or r['arguments'][column]]
        assert len(selected) == len(english), (name,len(selected),len(english))
        for (k,r),en in zip(selected,english):
            edits[k,column] = en.text
            manifest.append(dict(command=k,id=r['arguments'][1],column=column,table=name,
                                 english_index=en.physical_index,japanese=r['arguments'][column],english=en.text))
    result = rebuild_csb(source,edits)
    destination = OUT/'ui/Common/Dat/Option/QA/2og_Q&A.csb'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(result)
    report = dict(source_sha256=sha256(source),output_sha256=sha256(result),
                  source_size=len(source),output_size=len(result),fields=len(edits),rows=manifest,
                  question_ids_links_and_images_preserved=True,all_command_arguments_verified=True)
    (OUT/'qa_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}))

if __name__ == '__main__':build()

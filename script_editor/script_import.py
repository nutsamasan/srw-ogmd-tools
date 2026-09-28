"""Validate stable-ID JSON/text imports and produce an atomic, undoable edit plan."""
import json
import re
from pathlib import Path
from core import EditProject

HEADER=re.compile(r'^\[([^\]\n]+:\d+)\](?: ([^\n]*))?\n?',re.M)
BLOCK_HEADER=re.compile(r'^={72}\nBLOCK: [^\n]*\n={72}\n',re.M)
ANNOTATION='[The official English table contains Japanese here; preserved as shipped.]'

def normalized(value):return value.replace('\r\n','\n').replace('\r','\n') if isinstance(value,str) else value

def read_json(path):
    def pairs(values):
        result={}
        for k,v in values:
            if k in result:raise ValueError('Duplicate JSON property: '+k)
            result[k]=v
        return result
    return json.loads(path.read_text(encoding='utf-8-sig'),object_pairs_hook=pairs)

class ScriptImporter:
    def __init__(self,project):
        self.project=project;self.corpus=project.corpus;self.rows={};self.by_id={}
        for c in self.corpus.collections:
            key=c['key'];doc,_=self.corpus.load(key);self.rows[key]={r['id']:r for r in doc['rows']}
            for rid in self.rows[key]:self.by_id.setdefault(rid,set()).add(key)

    def resolve(self,path,ids,meta=None,key=None):
        candidates=set(self.rows)
        if key is not None:
            if key not in candidates:raise ValueError('Unknown collection: '+key)
            candidates={key}
        else:
            suffix=path.parent.as_posix().casefold()
            paths={k for k in candidates if suffix.endswith('/'+k.casefold())}
            if paths:candidates &= paths
        if meta:
            for field in ('native_entry','script_id'):
                if meta.get(field):candidates={k for k in candidates if self.corpus.load(k)[0]['metadata'].get(field)==meta[field]}
        for rid in ids:
            if rid not in self.by_id:raise ValueError('Unknown row ID: '+rid)
            candidates &= self.by_id[rid]
        if len(candidates)!=1:raise ValueError('Cannot identify one script collection for '+str(path)+'. Keep its original collection folder and row IDs.')
        return next(iter(candidates))

    def json_fields(self,path):
        doc=read_json(path);result=[]
        if not isinstance(doc,dict):raise ValueError('Expected a script.json or editor edits JSON object.')
        if 'collections' in doc:
            if doc.get('version')!=1 or doc.get('corpus_identity')!=self.corpus.identity:raise ValueError('This edits file belongs to a different source corpus.')
            for key,collection in doc['collections'].items():
                self.resolve(path,list(collection['rows']),key=key)
                if collection.get('source_sha256')!=self.corpus.load(key)[1]:raise ValueError('Source checksum differs: '+key)
                for rid,values in collection['rows'].items():
                    if any(f not in EditProject.FIELDS for f in values):raise ValueError('Unknown edit field: '+rid)
                    result.extend((key,rid,f,v) for f,v in values.items())
        elif 'rows' in doc and 'metadata' in doc:
            ids=[r['id'] for r in doc['rows']]
            if len(ids)!=len(set(ids)):raise ValueError('Duplicate row ID in '+str(path))
            if not ids:return []
            key=self.resolve(path,ids,doc['metadata'])
            exported=doc.get('editor_export',{})
            if exported.get('source_sha256',self.corpus.load(key)[1])!=self.corpus.load(key)[1]:raise ValueError('Imported script source checksum differs.')
            for incoming in doc['rows']:
                original=self.rows[key][incoming['id']]
                for field,value in incoming.items():
                    if field in EditProject.FIELDS:
                        if value is None and original.get(field) is None:continue
                        result.append((key,incoming['id'],field,value))
                    elif field in original and field not in ('en_raw','jp_raw') and value!=original[field]:
                        raise ValueError('Native metadata was changed in '+incoming['id']+': '+field)
        else:raise ValueError('Select script.json, edits.json, or an editor project JSON file.')
        return result

    def text_fields(self,path,language=None):
        # The original Windows exporter expanded one already-CRLF source line to CRCRLF.
        raw=path.read_bytes().decode('utf-8-sig').replace('\r\r\n','\r\n').replace('\r\n','\n').replace('\r','\n')
        matches=list(HEADER.finditer(raw))
        if not matches:
            key=self.resolve(path,[])
            if not self.rows[key]:return []
            raise ValueError('No stable row headers found in '+str(path))
        key=self.resolve(path,[m[1] for m in matches]);result=[];seen=set()
        if path.stem.upper() in ('EN','JP'):language=path.stem.lower()
        editor_export='Edited script export\n' in raw[:matches[0].start()]
        blocks=list(BLOCK_HEADER.finditer(raw))
        for i,match in enumerate(matches):
            rid=match[1];tail=match[2] or '';lang=language
            explicit=re.match(r'^(EN|JP)(?: (.*))?$',tail)
            if explicit:lang=explicit[1].lower();speaker=explicit[2] or ''
            else:speaker=tail
            if lang not in ('en','jp'):raise ValueError('Untagged text needs an EN.txt or JP.txt filename, or a language selection.')
            identity=(rid,lang)
            if identity in seen:raise ValueError('Duplicate text row/language: '+rid+' '+lang)
            seen.add(identity)
            end=matches[i+1].start() if i+1<len(matches) else len(raw)
            end=min([end]+[b.start() for b in blocks if match.end()<=b.start()<end])
            body=raw[match.end():end]
            annotation=body.find('\n'+ANNOTATION)
            if annotation>=0:body=body[:annotation+1]
            separators=1 if editor_export and end==len(raw) else 2
            for _ in range(separators):
                if body.endswith('\n'):body=body[:-1]
            original=self.rows[key][rid]
            if original.get(lang) is None and body in ('','[No official counterpart located]'):continue
            result.append((key,rid,lang,body))
            if 'speaker_'+lang in original:result.append((key,rid,'speaker_'+lang,speaker))
        return result

    def preview(self,source,folder_format='script.json',language=None,include_source=False,progress=lambda text:None):
        if not str(source).strip():raise ValueError('Choose a script file or folder.')
        source=Path(source).resolve()
        if source.is_dir():
            if folder_format not in ('script.json','EN.txt','JP.txt','Bilingual.txt'):raise ValueError('Choose a supported folder format.')
            paths=sorted(source.rglob(folder_format))
            if not paths and folder_format=='script.json':paths=[p for p in (source/'edits.json',source/'project.json') if p.is_file()]
        elif source.is_file():paths=[source]
        else:raise ValueError('Choose an existing script file or folder.')
        if not paths:raise ValueError('No '+folder_format+' files were found.')
        plan=[];seen={};unchanged=0
        for index,path in enumerate(paths):
            progress(f'Reading {index+1}/{len(paths)}: {path.name}')
            if path.stat().st_size>100*1024*1024:raise ValueError('Script import file exceeds 100 MB: '+str(path))
            try:
                fields=self.json_fields(path) if path.suffix.lower()=='.json' else self.text_fields(path,language) if path.suffix.lower()=='.txt' else None
                if fields is None:raise ValueError('Only JSON and TXT scripts are supported.')
                for key,rid,field,value in fields:
                    row=self.rows[key][rid];original=row.get(field)
                    if field not in row or not isinstance(value,str) or '\0' in value:raise ValueError('Invalid text field: '+rid+' '+field)
                    value=value.replace('\r\n','\n').replace('\r','\n')
                    identity=(key,rid,field)
                    if identity in seen:
                        if seen[identity]!=value:raise ValueError('Conflicting duplicate import field: '+rid+' '+field)
                        continue
                    seen[identity]=value
                    if row.get('null_text'):
                        if value!=(original or ''):raise ValueError('A subtitle cannot be added to a null battle record: '+rid)
                        continue
                    before=self.project.values(key,row).get(field)
                    if value==normalized(before) or (value==normalized(original) and not include_source):unchanged+=1;continue
                    conflict=normalized(before)!=normalized(original)
                    plan.append(dict(key=key,id=rid,field=field,before=before,after=value,original=original,
                        title=self.corpus.by_key[key]['title'],conflict=conflict,status='Conflict' if conflict else 'Import',file=str(path)))
            except Exception as exc:raise ValueError(str(path)+'\n'+str(exc)) from exc
        return dict(plan=plan,files=len(paths),unchanged=unchanged,conflicts=sum(x['conflict'] for x in plan))

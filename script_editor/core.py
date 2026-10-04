"""Corpus access, guarded edit storage, and native font measurements."""
from __future__ import annotations
import copy
import hashlib
import json
import os
import re
import struct
import tempfile
from datetime import datetime
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    payload=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf8')
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(payload);f.flush();os.fsync(f.fileno())
        assert json.loads(Path(tmp).read_text(encoding='utf8'))==value
        os.replace(tmp,path)
    finally:
        if Path(tmp).exists():Path(tmp).unlink()


class Corpus:
    def __init__(self,root):
        self.root=Path(root).resolve()
        if not (self.root/'data/stage_index.json').is_file():
            raise ValueError('Choose the OGMD_EN_JP export folder containing START_HERE.md and data.')
        self.identity=sha((self.root/'SOURCE_MANIFEST.json').read_bytes())
        self.collections=[];seen=set()
        def add(folder,title,group,meta=None):
            if folder in seen:return
            path=(self.root/folder/'script.json').resolve()
            if not path.is_relative_to(self.root) or not path.is_file():raise ValueError('Invalid collection path: '+folder)
            seen.add(folder);self.collections.append(dict(key=folder,title=title,group=group,meta=meta or {}))
        stages=json.loads((self.root/'data/stage_index.json').read_text(encoding='utf8'))
        for s in sorted(stages,key=lambda s:(s.get('stage_data_chapter',1000),s['scenario_id'])):
            if s['scenario_id']==40 and s['title_en']=="HAGWANE'S CRISIS":
                s={**s,'title_en':"HAGANE'S CRISIS"}
            sid=s['scenario_id'];ch=s.get('stage_data_chapter','–');route=s.get('classification_route','')
            group=('Stages' if sid<96 else 'Alternate versions' if sid<100 else 'Interludes' if sid<200 else 'Extras' if sid in (200,800,999) else 'Developer scripts')
            title=f"{ch:02d}" if isinstance(ch,int) else str(ch)
            title+=f" · {route} · {s['title_en'].strip()} · {s['script_id']}"
            add(s['folder'],title,group,s)
        for c in json.loads((self.root/'data/collection_index.json').read_text(encoding='utf8')):
            add(c['folder'],c.get('title_en',c['folder']),'Shared & narration',c)
        for m in json.loads((self.root/'data/map_inventory.json').read_text(encoding='utf8')):
            stage=next((s for s in stages if s['scenario_id']==m['scenario_id']),{})
            if stage.get('scenario_id')==40 and stage.get('title_en')=="HAGWANE'S CRISIS":
                stage={**stage,'title_en':"HAGANE'S CRISIS"}
            add(m['folder'],f"S{m['scenario_id']:03d} · {stage.get('title_en','Map events').strip()}",'Map event text',stage)
        for b in json.loads((self.root/'data/battle_inventory.json').read_text(encoding='utf8')):
            add(b['folder'],f"Bank {Path(b['folder']).name} · {b['records']} records",'Battle messages')
        self.fixed_hashes={};self.extension_hashes={}
        for extension in (self.root/'data/fixed_index.json',self.root/'data/expanded_index.json'):
            if not extension.exists():continue
            fixed=json.loads(extension.read_text(encoding='utf8'))
            if fixed.get('version')!=1:raise ValueError('Unsupported game-data library version.')
            for c in fixed['collections']:
                add(c['folder'],c['title_en'],c['group'],c)
                self.extension_hashes[c['folder']]=c['sha256']
                if c['group']!='Location banners':self.fixed_hashes[c['folder']]=c['sha256']
        from gilliam_title_correction import correct_title_label
        for collection in self.collections:
            collection['title'] = correct_title_label(collection['title'])
            if 'title_en' in collection['meta']:
                collection['meta']['title_en'] = correct_title_label(collection['meta']['title_en'])
        self.cache={};self.by_key={c['key']:c for c in self.collections}

    def load(self,key):
        if key not in self.by_key:raise KeyError('Unknown script')
        if key not in self.cache:
            raw=(self.root/key/'script.json').read_bytes();doc=json.loads(raw)
            if key in self.extension_hashes and sha(raw)!=self.extension_hashes[key]:raise ValueError('Game-data source changed: '+key)
            ids=[r['id'] for r in doc['rows']]
            if len(ids)!=len(set(ids)):raise ValueError('Duplicate row IDs in '+key)
            from gilliam_title_correction import correct_title_label
            for row in doc['rows']:
                for field in ('label_en', 'label_jp'):
                    if field in row: row[field] = correct_title_label(row[field])
            for metadata in ('meta', 'metadata'):
                if 'title_en' in doc.get(metadata, {}):
                    doc[metadata]['title_en'] = correct_title_label(doc[metadata]['title_en'])
            self.cache[key]=(doc,sha(raw))
        return self.cache[key]


class EditProject:
    FIELDS=('en','jp','speaker_en','speaker_jp')
    def __init__(self,corpus,path):
        self.corpus=corpus;self.path=Path(path);self.dirty=False
        self.file_hash=sha(self.path.read_bytes()) if self.path.exists() else None
        self.data=json.loads(self.path.read_text(encoding='utf8')) if self.path.exists() else dict(version=1,corpus_identity=corpus.identity,collections={})
        if self.data.get('version')!=1 or self.data.get('corpus_identity')!=corpus.identity:
            raise ValueError('This edits file belongs to a different source corpus. It was not loaded.')
        for key,item in self.data['collections'].items():
            doc,digest=corpus.load(key)
            if item['source_sha256']!=digest:raise ValueError('Source script changed since editing: '+key)
            original={r['id']:r for r in doc['rows']}
            for rid,values in item['rows'].items():
                if rid not in original or any(k not in self.FIELDS or not isinstance(v,str) for k,v in values.items()):
                    raise ValueError('Invalid edit record: '+rid)

    def values(self,key,row):
        item=self.data['collections'].get(key,{})
        return {**row,**item.get('rows',{}).get(row['id'],{})}

    def changed(self,key,row):
        return bool(self.data['collections'].get(key,{}).get('rows',{}).get(row['id']))

    def set(self,key,row,field,text):
        if field not in self.FIELDS:raise ValueError('Unsupported edit field')
        if field not in row or row.get('null_text',False):raise ValueError('This record has no editable field: '+field)
        if '\0' in text:raise ValueError('NUL characters cannot be stored in game text.')
        text=text.replace('\r\n','\n').replace('\r','\n')
        old=self.values(key,row).get(field)
        if text==old:return
        entry=self.data['collections'].setdefault(key,dict(source_sha256=self.corpus.load(key)[1],rows={}))
        edits=entry['rows'].setdefault(row['id'],{})
        if text==(row.get(field) or '').replace('\r\n','\n').replace('\r','\n'):edits.pop(field,None)
        else:edits[field]=text
        if not edits:entry['rows'].pop(row['id'],None)
        if not entry['rows']:self.data['collections'].pop(key,None)
        self.dirty=True

    def count(self):
        return sum(len(x['rows']) for x in self.data['collections'].values())

    def save(self):
        if not self.dirty:return
        current=sha(self.path.read_bytes()) if self.path.exists() else None
        if current!=self.file_hash:raise RuntimeError('The edits file changed in another process. Close the other editor and reopen to avoid overwriting its changes.')
        if self.path.exists():
            backup=self.path.parent/'backups'/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
            backup.parent.mkdir(exist_ok=True);backup.write_bytes(self.path.read_bytes())
        atomic_json(self.path,self.data)
        self.file_hash=sha(self.path.read_bytes());self.dirty=False

    def export(self,destination):
        destination=Path(destination).resolve()
        if destination==self.corpus.root or destination.is_relative_to(self.corpus.root):
            raise ValueError('Export outside the original script corpus.')
        if destination.exists():raise ValueError('The export directory already exists; choose a new one.')
        destination.mkdir(parents=True)
        written=[]
        for key,edits in self.data['collections'].items():
            source,digest=self.corpus.load(key)
            if sha((self.corpus.root/key/'script.json').read_bytes())!=digest:raise ValueError('Source changed: '+key)
            doc=copy.deepcopy(source)
            for row in doc['rows']:
                patch=edits['rows'].get(row['id'],{})
                for field,text in patch.items():
                    row[field+'_original']=row.get(field)
                    row[field]=text
                    if field in ('en','jp'):
                        row[field+'_raw_original']=row.get(field+'_raw')
                        # jp_raw convention is native @ for LDBI and map strings;
                        # CSB narration retains LF. Native provenance remains explicit.
                        native_markers=bool(row.get('command_offset') is not None or row.get('native_string_index') is not None)
                        row[field+'_raw']=text.replace('\n','@') if field=='jp' and native_markers else text
                        if 'record_metadata_hex' in row:
                            from text_layout import battle_storage
                            row[field+'_raw']=battle_storage(text)
                    row['editor_modified']=True
            doc['editor_export']=dict(source_sha256=digest,changed_rows=len(edits['rows']),game_archives_modified=False)
            folder=destination/key;atomic_json(folder/'script.json',doc)
            for label,languages in [('EN',['en']),('JP',['jp']),('Bilingual',['en','jp'])]:
                lines=[doc['metadata'].get('title_en',key),'Edited script export','']
                for row in doc['rows']:
                    for lang in languages:
                        lines += [f"[{row['id']}] {lang.upper()} {row.get('speaker_'+lang,'')}",row.get(lang) or '', '']
                (folder/(label+'.txt')).write_text('\n'.join(lines),encoding='utf-8-sig')
            written.append(dict(collection=key,source_sha256=digest,changed_rows=len(edits['rows'])))
        atomic_json(destination/'edits.json',self.data)
        from edit_bundle import export_bundle
        export_bundle(self,destination/'patch_edits.json')
        from title_cards import project_cards
        cards=project_cards(self)
        if cards.count():
            atomic_json(destination/'title_cards.json',cards.data)
            folder=destination/'Title_cards';folder.mkdir()
            for identity in cards.data['images']:
                language,key=identity.split(':',1)
                (folder/(key+'_'+language+'.png')).write_bytes(cards.png(key,language))
        atomic_json(destination/'export_manifest.json',dict(collections=written,game_archives_modified=False))
        (destination/'README.txt').write_text('Edited script files and stable row IDs for review/reimport.\nOriginal source fields are retained with _original suffixes.\nTitle_cards contains edited PNG sheets, when present. Reimport those through Stage title cards, not Import scripts.\npatch_edits.json includes English text and artwork for the Full English patcher embedded in Script Editor 3.15 or newer.\nGame archives have not been rebuilt or installed.\n',encoding='utf8')
        return len(written)

    def find_all(self,query,replacement='',languages=('en',),speakers=True,match_case=False,whole_word=False):
        """Literal corpus-wide search of current values, including unsaved edits."""
        if not query:raise ValueError('Enter text to find.')
        if '\0' in query or '\0' in replacement:raise ValueError('NUL characters are not allowed.')
        if not languages or any(x not in ('en','jp') for x in languages):raise ValueError('Choose English or Japanese.')
        expression=re.escape(query)
        if whole_word:expression=r'(?<!\w)'+expression+r'(?!\w)'
        pattern=re.compile(expression,0 if match_case else re.IGNORECASE)
        fields=list(languages)+(['speaker_'+x for x in languages] if speakers else [])
        result=[]
        for collection in self.corpus.collections:
            key=collection['key'];doc,_=self.corpus.load(key)
            for row in doc['rows']:
                if row.get('null_text',False):continue
                values=self.values(key,row)
                for field in fields:
                    before=values.get(field)
                    if not isinstance(before,str):continue
                    after,count=pattern.subn(lambda match:replacement,before)
                    if count:result.append(dict(key=key,id=row['id'],field=field,before=before,after=after,count=count,title=collection['title']))
        return result

    def apply_replacements(self,plan,undo=False):
        """Validate the complete preview before changing any values; one save/backup."""
        rows={};seen=set()
        for item in plan:
            key=item['key'];rid=item['id'];field=item['field'];identity=(key,rid,field)
            if identity in seen:raise ValueError('Duplicate replacement field.')
            seen.add(identity)
            if key not in rows:rows[key]={r['id']:r for r in self.corpus.load(key)[0]['rows']}
            row=rows[key][rid]
            expected=item['after'] if undo else item['before']
            value=item['before'] if undo else item['after']
            if undo and value is None:value=''
            if self.values(key,row).get(field)!=expected:
                raise ValueError('Text changed after the preview. Search again, or undo later edits first: '+rid)
            if field not in self.FIELDS or field not in row or row.get('null_text',False) or '\0' in value:
                raise ValueError('Invalid replacement: '+rid)
        snapshot=copy.deepcopy(self.data);dirty=self.dirty
        try:
            for item in plan:
                self.set(item['key'],rows[item['key']][item['id']],item['field'],(item['before'] or '') if undo else item['after'])
            self.save()
        except Exception:
            self.data=snapshot;self.dirty=dirty;raise
        return sum(item['before']!=item['after'] for item in plan)


COLOR_TAG=re.compile(r'</?C(?:=[^>]*)?>',re.I)


class NativeMetrics:
    def __init__(self,path):
        self.data=Path(path).read_bytes()
        if self.data[:4]!=b'FTTF':raise ValueError('Missing native FTTF font')

    def descriptor(self,char):
        cp=ord(char)
        if cp>65535:return None
        page=struct.unpack_from('>I',self.data,0x54+(cp>>8)*4)[0]
        if not page:return None
        descriptor=self.data[page+(cp&255)*4:page+(cp&255)*4+4]
        if len(descriptor)!=4 or not any(descriptor):return None
        return descriptor

    @staticmethod
    def visible(text):
        return COLOR_TAG.sub('',text).replace('<','').replace('>','').replace('@','\n')

    def advance(self,char,cell=24):
        d=self.descriptor(char)
        if d is None:return cell
        if char=="'" and d[1]==22:return cell*13/32
        return cell*d[1]/32 if 32<=ord(char)<=126 and 0<d[1]<=32 else cell

    def raw_width(self,text,cell=24):
        total=0.
        for c in text:
            if c!='\n':total=struct.unpack('f',struct.pack('f',total+self.advance(c,cell)))[0]
        return total

    def width(self,text,cell=24):
        return self.raw_width(self.visible(text),cell)

    def assess(self,text,cell=24,limit=768,max_lines=3):
        visible=self.visible(text);lines=visible.split('\n')
        widths=[self.width(line,cell) for line in lines]
        missing=sorted({c for c in visible if c not in '\n\r\t' and self.descriptor(c) is None})
        return dict(lines=lines,widths=widths,missing=missing,line_count=len(lines),
                    overflow=any(w>limit for w in widths),too_many_lines=len(lines)>max_lines,
                    fits=all(w<=limit for w in widths) and len(lines)<=max_lines and not missing)

    def wrap(self,text,cell=24,limit=768):
        if re.search(r';\s*(?:@|\n)',text) or COLOR_TAG.search(text):
            raise ValueError('This row contains choice separators or color controls. Adjust its line breaks manually to preserve those controls.')
        # Explicit blank paragraphs remain; ordinary line breaks are reflowed.
        paragraphs=re.split(r'\n\s*\n',text.replace('@','\n'))
        output=[]
        for paragraph in paragraphs:
            tokens=re.findall(r'<[^>]*>|\S+|[ \t]+',paragraph.replace('\n',' '))
            line=''
            for token in tokens:
                if not token.strip():
                    if line and not line.endswith(' '):line+=' '
                    continue
                if line.strip() and self.width(line+token,cell)>limit:
                    output.append(line.rstrip());line=''
                if self.width(token,cell)<=limit:
                    line+=token;continue
                if '<' in token or '>' in token:raise ValueError('A marked keyword exceeds the width; edit it manually.')
                for char in token:
                    if line and self.width(line+char,cell)>limit:output.append(line.rstrip());line=''
                    line+=char
            output.append(line.rstrip())
            output.append('')
        return '\n'.join(output[:-1])

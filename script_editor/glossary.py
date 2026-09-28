"""Keyword markup, glossary lookup, and explicit rename previews."""
import re

TOKEN=re.compile(r'<([^<>]+)>')
CONTROL=re.compile(r'^/?[CIW](?:=.*)?$',re.I)

def key(text):return re.sub(r'\s+','',text.replace('@','')).casefold()

def keywords(text):return [m[1] for m in TOKEN.finditer(text) if not CONTROL.fullmatch(m[1])]

def rich_lines(text):
    lines=[[]];pos=0
    def add(value,term=None):
        for char in value.replace('@','\n'):
            if char=='\n':lines.append([])
            elif char not in '<>':lines[-1].append((char,term))
    for m in TOKEN.finditer(text):
        add(text[pos:m.start()])
        if not CONTROL.fullmatch(m[1]):add(m[1],m[1])
        elif not re.fullmatch(r'/?C(?:=.*)?',m[1],re.I):add(m[1])
        pos=m.end()
    add(text[pos:]);return lines

def glossary_rows(project):
    for c in project.corpus.collections:
        if c['group']=='Glossary':
            doc,_=project.corpus.load(c['key'])
            for r in doc['rows']:
                if r['fixed_field']=='term':yield c['key'],r

def resolve(project,term,lang):
    matches=[]
    for collection,row in glossary_rows(project):
        if key(project.values(collection,row)[lang])==key(term):matches.append((collection,row))
    return matches

def rename_plan(project,collection,row,lang,new):
    old=project.values(collection,row)[lang]
    if row.get('fixed_field')!='term' or not new.strip() or any(c in new for c in '\n\r@<>\0'):
        raise ValueError('Enter a single glossary term without control markers.')
    if key(old)!=key(new) and resolve(project,new,lang):raise ValueError('Another glossary entry already uses that term.')
    if old==new:return []
    plan=[]
    for c in project.corpus.collections:
        doc,_=project.corpus.load(c['key'])
        for r in doc['rows']:
            if r.get('null_text'):continue
            before=project.values(c['key'],r).get(lang)
            if not isinstance(before,str):continue
            if c['key']==collection and r['id']==row['id']:after=new;count=1
            else:
                count=0
                def sub(m):
                    nonlocal count
                    if not CONTROL.fullmatch(m[1]) and key(m[1])==key(old):count+=1;return '<'+new+'>'
                    return m[0]
                after=TOKEN.sub(sub,before)
            if count:plan.append(dict(key=c['key'],id=r['id'],field=lang,before=before,after=after,count=count,title=c['title']))
    return plan

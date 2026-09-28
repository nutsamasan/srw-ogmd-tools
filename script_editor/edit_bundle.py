"""Portable text corrections for a vanilla-to-English build."""
from pathlib import Path
import json,hashlib
from core import atomic_json
from patcher import collect_changes,archive_name

def checksum(doc):return hashlib.sha256(json.dumps(doc,ensure_ascii=False,sort_keys=True).encode('utf8')).hexdigest()

def export_bundle(project,path):
    groups=collect_changes(project,'en')
    doc=dict(version=1,kind='ogmd-english-edits',corpus_identity=project.corpus.identity,
             groups=[dict(archive=a,entry=e,items=items) for (a,e),items in sorted(groups.items())])
    doc['payload_sha256']=checksum(doc);atomic_json(path,doc);return Path(path)

def read_bundle(path,release):
    path=Path(path)
    if path.stat().st_size>100*1024*1024:raise ValueError('Editor corrections exceed 100 MB.')
    doc=json.loads(path.read_text(encoding='utf-8-sig'));expected=doc.pop('payload_sha256',None)
    if checksum(doc)!=expected:raise ValueError('Editor corrections changed. Export them again from the editor.')
    if doc.get('version')!=1 or doc.get('kind')!='ogmd-english-edits':raise ValueError('Choose patch_edits.json from Export edits.')
    if doc.get('corpus_identity')!=release.get('corpus_identity'):raise ValueError('Editor corrections and release use different source libraries.')
    groups={}
    for group in doc['groups']:
        a,e=group['archive'],group['entry']
        if not e.startswith('/') or archive_name(e[1:])!=a or (a,e) in groups:raise ValueError('Invalid correction archive mapping.')
        for item in group['items']:
            row=item['row']
            if not isinstance(row.get('id'),str):raise ValueError('Missing correction row ID.')
            if row.get('fixed_table') and e!='/Dat/FixedData/'+row['fixed_table']+'.dat':raise ValueError('Fixed table mapping differs.')
            if row.get('location_field') and e!='/'+row.get('native_entry',''):raise ValueError('Location script mapping differs.')
            if not item['edits'] or any(k not in ('en','speaker_en') or not isinstance(v,str) or '\0' in v for k,v in item['edits'].items()):
                raise ValueError('Invalid English correction field.')
        groups[(a,e)]=group['items']
    return groups,expected

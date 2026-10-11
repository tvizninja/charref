#!/usr/bin/env python3
import sqlite3,json,pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
con=sqlite3.connect(ROOT/'db'/'charref.sqlite'); con.row_factory=sqlite3.Row
meta=dict(con.execute('SELECT key,value FROM meta'))
out={'meta':meta,'characters':{},'positions':{},'sequences':{},'collections':[],'sources':[],'blocks':[]}
for s in con.execute('SELECT source_key,title,publisher,version,url,license,notes FROM source ORDER BY id'):
    out['sources'].append(dict(s))
for b in con.execute('SELECT block_key,name,first_cp,last_cp FROM unicode_block ORDER BY first_cp'):
    out['blocks'].append(dict(b))
for r in con.execute('''SELECT u.cp,u.name,u.age,u.general_category,u.canonical_combining_class,u.bidi_class,u.east_asian_width,u.decomposition,
                               b.name AS block_name,s.name AS script_name
                        FROM unicode_codepoint u
                        LEFT JOIN unicode_block b ON b.id=u.block_id
                        LEFT JOIN unicode_script s ON s.id=u.primary_script_id
                        ORDER BY u.cp'''):
    out['characters'][f"{r['cp']:X}"]={'cp':r['cp'],'name':r['name'],'age':r['age'],'category':r['general_category'],'eaw':r['east_asian_width'],
        'block':r['block_name'],'script':r['script_name'],'ccc':r['canonical_combining_class'],'bidi':r['bidi_class'],'decomposition':r['decomposition'],'properties':{},'issues':[],'relations':[],'encodings':{},'mapping_details':[],'jis_positions':[],'variations':[],'memberships':[]}
chars=out['characters']
for r in con.execute('SELECT cp,property,value FROM unicode_property ORDER BY cp,property,value'):
    d=chars.get(f"{r['cp']:X}")
    if d: d['properties'].setdefault(r['property'],[]).append(r['value'])
for r in con.execute('''SELECT ui.cp,i.issue_key,i.title,i.description FROM unicode_issue ui JOIN issue i ON i.id=ui.issue_id ORDER BY ui.cp'''):
    if f"{r['cp']:X}" in chars: chars[f"{r['cp']:X}"]['issues'].append({'key':r['issue_key'],'title':r['title'],'description':r['description']})
for r in con.execute('SELECT from_cp,to_cp,relation_type FROM relation ORDER BY from_cp'):
    if f"{r['from_cp']:X}" in chars: chars[f"{r['from_cp']:X}"]['relations'].append({'cp':r['to_cp'],'type':r['relation_type']})
# Export only semantic/custom memberships; block/script navigation is already explicit fields and would bloat the payload.
for r in con.execute("""SELECT cm.cp,c.collection_key,c.title,c.collection_type FROM collection_member_unicode cm JOIN collection c ON c.id=cm.collection_id WHERE c.collection_type NOT IN ('unicode-block','unicode-script','root','unicode-group') ORDER BY cm.cp,c.sort_order,c.title"""):
    d=chars.get(f"{r['cp']:X}")
    if d: d['memberships'].append({'key':r['collection_key'],'title':r['title'],'type':r['collection_type']})

# Export every code position and every mapping without collapsing direction/kind/sequence.
pos_rows=con.execute('''SELECT p.id,cs.system_key,cs.title,cs.system_type,p.position_key,p.plane,p.row_no,p.cell_no,p.byte_value,p.notes
                        FROM code_position p JOIN code_system cs ON cs.id=p.system_id ORDER BY p.id''').fetchall()
for r in pos_rows:
    b=r['byte_value']; out['positions'][str(r['id'])]={
        'id':r['id'],'system_key':r['system_key'],'title':r['title'],'system_type':r['system_type'],'position_key':r['position_key'],
        'plane':r['plane'],'row':r['row_no'],'cell':r['cell_no'],'bytes':' '.join(f'{n:02X}' for n in b) if b is not None else None,
        'notes':r['notes'],'mappings':[]}

map_rows=con.execute('''SELECT m.id,m.code_position_id,m.direction,m.mapping_kind,m.priority,m.notes,
                               cs.system_key,cs.title,cs.system_type,p.position_key,p.byte_value
                        FROM mapping m JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id
                        ORDER BY m.id''').fetchall()
for m in map_rows:
    cps=[x['cp'] for x in con.execute('SELECT cp FROM mapping_unicode WHERE mapping_id=? ORDER BY seq_index',(m['id'],))]
    item={'mapping_id':m['id'],'direction':m['direction'],'kind':m['mapping_kind'],'priority':m['priority'],'unicode':cps,'notes':m['notes']}
    out['positions'][str(m['code_position_id'])]['mappings'].append(item)
    hx=' '.join(f'{n:02X}' for n in m['byte_value']) if m['byte_value'] is not None else m['position_key']
    if len(cps)==1:
        d=chars.get(f'{cps[0]:X}')
        if d:
            md={'system_key':m['system_key'],'title':m['title'],'system_type':m['system_type'],'position_key':m['position_key'],
                'bytes':hx,'direction':m['direction'],'kind':m['mapping_kind'],'priority':m['priority'],'notes':m['notes']}
            d['mapping_details'].append(md)
            if m['system_type']=='encoding' and m['direction'] in ('encode','both'):
                a=d['encodings'].setdefault(m['system_key'],[])
                if hx not in a:a.append(hx)
            elif m['system_type']=='standard-position':
                p=out['positions'][str(m['code_position_id'])]
                d['jis_positions'].append({'position_id':m['code_position_id'],'system_key':m['system_key'],'title':m['title'],'position_key':m['position_key'],'plane':p['plane'],'row':p['row'],'cell':p['cell']})
    elif len(cps)>1:
        skey='-'.join(f'{cp:X}' for cp in cps)
        seq=out['sequences'].setdefault(skey,{'cps':cps,'mappings':[],'variations':[]})
        seq['mappings'].append({'system_key':m['system_key'],'title':m['title'],'system_type':m['system_type'],'position_key':m['position_key'],
                                'bytes':hx,'direction':m['direction'],'kind':m['mapping_kind'],'priority':m['priority'],'notes':m['notes']})

for r in con.execute('''SELECT vs.id,vs.base_cp,vs.variation_cp,vc.collection_key,vc.title,
                               GROUP_CONCAT(va.key || '=' || va.value, char(31)) AS annotations
                        FROM variation_sequence vs JOIN variation_collection vc ON vc.id=vs.collection_id
                        LEFT JOIN variation_annotation va ON va.variation_id=vs.id
                        GROUP BY vs.id ORDER BY vs.base_cp,vs.variation_cp'''):
    ann={}
    if r['annotations']:
        for pair in r['annotations'].split(chr(31)):
            k,v=pair.split('=',1); ann[k]=v
    d=chars.get(f"{r['base_cp']:X}")
    item={'variation_cp':r['variation_cp'],'collection_key':r['collection_key'],'collection_title':r['title'],'annotations':ann,'label':ann.get('glyph-standard')}
    if d:d['variations'].append(item)
    skey=f"{r['base_cp']:X}-{r['variation_cp']:X}"
    seq=out['sequences'].setdefault(skey,{'cps':[r['base_cp'],r['variation_cp']],'mappings':[],'variations':[]})
    seq['variations'].append(item)

# First-class Unicode sequences (Emoji ZWJ, RI flags, modifiers, keycaps, tags, named sequences...).
for r in con.execute('SELECT id,sequence_key,sequence_type,name,notes FROM unicode_sequence ORDER BY id'):
    cps=[x['cp'] for x in con.execute('SELECT cp FROM unicode_sequence_member WHERE sequence_id=? ORDER BY seq_index',(r['id'],))]
    skey='-'.join(f'{cp:X}' for cp in cps)
    seq=out['sequences'].setdefault(skey,{'cps':cps,'mappings':[],'variations':[]})
    anns={x['key']:x['value'] for x in con.execute('SELECT key,value FROM unicode_sequence_annotation WHERE sequence_id=?',(r['id'],))}
    seq.setdefault('entities',[]).append({'id':r['id'],'sequence_key':r['sequence_key'],'sequence_type':r['sequence_type'],'name':r['name'],'notes':r['notes'],'annotations':anns})

for r in con.execute('SELECT id,collection_key,parent_id,title,collection_type,description,sort_order FROM collection ORDER BY sort_order,title'):
    members=[x[0] for x in con.execute('SELECT cp FROM collection_member_unicode WHERE collection_id=? ORDER BY COALESCE(sort_order,cp),cp',(r['id'],))]
    positions=[x[0] for x in con.execute('SELECT code_position_id FROM collection_member_position WHERE collection_id=? ORDER BY COALESCE(sort_order,code_position_id),code_position_id',(r['id'],))]
    sequences=[]
    for x in con.execute('''SELECT us.id FROM collection_member_sequence cms JOIN unicode_sequence us ON us.id=cms.sequence_id WHERE cms.collection_id=? ORDER BY COALESCE(cms.sort_order,us.id),us.id''',(r['id'],)):
        cps=[m[0] for m in con.execute('SELECT cp FROM unicode_sequence_member WHERE sequence_id=? ORDER BY seq_index',(x[0],))]
        sequences.append('-'.join(f'{cp:X}' for cp in cps))
    out['collections'].append({**dict(r),'members':members,'positions':positions,'sequences':sequences})
path=ROOT/'dist'/'webdata.json'; path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps(out,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
print(path,'bytes',path.stat().st_size,'characters',len(chars),'positions',len(out['positions']),'sequences',len(out['sequences']))

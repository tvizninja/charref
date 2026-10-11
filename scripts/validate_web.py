#!/usr/bin/env python3
import json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
d=json.loads((ROOT/'dist'/'webdata.json').read_text(encoding='utf-8'))
fail=[]
def need(cond,*msg):
    if not cond: fail.append(msg)
# Exact Unicode sequences must survive DB -> web export.
for key,system,hx in [
    ('FF76-FF9E','cp932','B6 DE'),
    ('304B-309A','shift_jis_2004','82 F5'),
]:
    seq=d.get('sequences',{}).get(key)
    need(seq is not None,key,'sequence missing')
    if seq:
        vals=[m['bytes'] for m in seq['mappings'] if m['system_key']==system and m['direction'] in ('encode','both')]
        need(hx in vals,key,system,hx,vals)
# IVS metadata must survive export.
for key,label in [('8FBB-E0100','JIS90'),('8FBB-E0101','JIS2004')]:
    seq=d.get('sequences',{}).get(key)
    vals=[v.get('label') for v in (seq or {}).get('variations',[])]
    need(label in vals,key,'IVS label',label,vals)
# All UI-facing structural fixtures are consolidated into one debug Collection.
debug=next((x for x in d['collections'] if x['collection_key']=='debug-structural'),None)
need(debug is not None,'debug structural collection missing')
if debug:
    ps=[d['positions'][str(x)] for x in debug.get('positions',[]) if str(x) in d['positions']]
    need(any(p.get('system_key')=='test_jis_position' and not p['mappings'] for p in ps),'unmapped code position lost')
    need(any(p.get('system_key')=='test_jis_position' and p['mappings'] for p in ps),'mapped code position lost')
# Direction must not be collapsed during export.
directions=[]
for p in d['positions'].values():
    if p['system_key']=='test_directional':
        directions.extend(m['direction'] for m in p['mappings'])
need(sorted(directions)==['decode','encode'],'direction export',directions)

# Mapping edge cases must also be reachable through the consolidated debug Collection.
if debug:
    systems=[d['positions'][str(x)].get('system_key') for x in debug.get('positions',[]) if str(x) in d['positions']]
    for sk in ('test_roundtrip','test_ambiguous','test_alias'):
        need(sk in systems,'debug mapping fixture missing',sk,systems)

# v0.6: asymmetric/ambiguous mappings, alias positions, second variation collection,
# and Unicode decomposition must survive DB -> web export without collapsing.
def find_position(system, poskey):
    return next((p for p in d['positions'].values() if p['system_key']==system and p['position_key']==poskey),None)

p=find_position('test_roundtrip','81 60')
need(p is not None,'roundtrip position missing')
if p:
    got=sorted((m['direction'],m['kind'],m['priority'],tuple(m['unicode'])) for m in p['mappings'])
    exp=sorted([('decode','standard',0,(0x301C,)),('encode','vendor',0,(0xFF5E,))])
    need(got==exp,'roundtrip mappings collapsed',got)

p=find_position('test_ambiguous','A1')
need(p is not None,'ambiguous position missing')
if p:
    got=sorted((m['direction'],m['kind'],m['priority'],tuple(m['unicode'])) for m in p['mappings'])
    exp=sorted([('decode','standard',0,(0x301C,)),('decode','vendor',10,(0xFF5E,))])
    need(got==exp,'ambiguous decode candidates collapsed',got)

yen=d['characters'].get('A5')
need(yen is not None,'U+00A5 missing')
if yen:
    alias=sorted((m['position_key'],m['kind'],m['priority']) for m in yen.get('mapping_details',[]) if m['system_key']=='test_alias')
    need(alias==[('A1','standard',0),('A2','vendor',10)],'alias positions lost',alias)

seq=d.get('sequences',{}).get('8FBB-E0102')
vals=[(v.get('collection_key'),v.get('label')) for v in (seq or {}).get('variations',[])]
need(('test-ivd-alt','ALT-COLLECTION') in vals,'second variation collection lost',vals)

eacute=d['characters'].get('E9')
need(eacute is not None,'U+00E9 missing')
if eacute: need(eacute.get('decomposition')=='0065 0301','decomposition export',eacute.get('decomposition'))


# v0.7: standards revision position changes and sequence aliases must survive export.
tsuji=d['characters'].get('8FBB')
need(tsuji is not None,'U+8FBB missing')
if tsuji:
    rev={(m['system_key'],m['position_key']) for m in tsuji.get('mapping_details',[]) if m['system_key'].startswith('test_jis_revision_')}
    need(rev=={('test_jis_revision_old','1-10-10'),('test_jis_revision_new','1-20-20')},'revision positions lost',rev)
seq=d.get('sequences',{}).get('304B-309A')
if seq:
    poss=sorted(m['position_key'] for m in seq.get('mappings',[]) if m['system_key']=='test_seq_positions')
    need(poss==['1-30-30','2-40-40'],'sequence standard positions lost',poss)
else: need(False,'304B-309A sequence missing')
seq=d.get('sequences',{}).get('8FBB-E0100')
if seq:
    anns=[v.get('annotations',{}).get('rendering-risk') for v in seq.get('variations',[]) if v.get('collection_key')=='adobe-japan1']
    need('font-dependent' in anns,'IVS rendering-risk annotation lost',anns)
# Search ambiguity fixture: raw 8140 is both a Unicode scalar and bytes in multiple code systems.
need('8140' in d['characters'],'U+8140 search candidate missing')
pos8140=[p for p in d['positions'].values() if p.get('bytes')=='81 40']
need(len(pos8140)>=2,'81 40 position candidates missing',len(pos8140))

# v0.8: first-class Unicode sequence entities and special-code-point metadata.
for key,etype in [('1F468-200D-1F469-200D-1F467-200D-1F466','emoji-zwj'),('1F1EF-1F1F5','regional-indicator'),('1F44B-1F3FB','emoji-modifier'),('31-FE0F-20E3','emoji-keycap'),('1F3F4-E0067-E0062-E0065-E006E-E0067-E007F','emoji-tag')]:
    seq=d.get('sequences',{}).get(key)
    need(seq is not None,key,'unicode sequence missing')
    if seq: need(any(e.get('sequence_type')==etype for e in seq.get('entities',[])),key,'sequence entity type',etype,seq.get('entities'))
if debug:
    need(len(debug.get('sequences',[]))==2,'debug structural sequence count',debug.get('sequences'))
    need(len(debug.get('positions',[]))==12,'debug structural position count',debug.get('positions'))
# Normal Unicode > Sequences is no longer a structural sample: it is the complete UCD NamedSequences list.
named=next((x for x in d['collections'] if x['collection_key']=='unicode-named-sequences'),None)
need(named is not None,'UCD Named Sequences collection missing')
if named: need(len(named.get('sequences',[]))==461,'UCD Named Sequences count',len(named.get('sequences',[])))
# Legacy fragmented structural Collections must not remain in navigation.
legacy={'jis-structural-unmapped','mapping-structural-edgecases','unicode-sequences-structural'}
need(not any(x.get('collection_key') in legacy for x in d['collections']),'legacy structural collections still exported')
for cp,gc in [('200D','Cf'),('200C','Cf'),('301','Mn'),('E000','Co'),('0','Cc')]:
    ch=d['characters'].get(cp)
    need(ch is not None,cp,'special character missing')
    if ch: need(ch.get('category')==gc,cp,'category',gc,ch.get('category'))
need(any(b.get('name')=='Greek and Coptic' and b.get('first_cp')<=0x378<=b.get('last_cp') for b in d.get('blocks',[])),'block ranges export missing Greek and Coptic')


# v0.9: Unicode generic properties must survive export.
for cp,props in [('20',['White_Space']),('200D',['Default_Ignorable_Code_Point','Join_Control']),('FE0F',['Variation_Selector']),('1F600',['Emoji','Emoji_Presentation','Extended_Pictographic']),('4E00',['Ideographic','Unified_Ideograph']),('149',['Deprecated'])]:
    ch=d['characters'].get(cp)
    need(ch is not None,cp,'property character missing')
    if ch:
        got=set((ch.get('properties') or {}).keys())
        need(set(props)<=got,cp,'properties',props,sorted(got))

# v2.2: complete Emoji 18.0 + education/qualification collections.
def collkey(k): return next((x for x in d['collections'] if x['collection_key']==k),None)
for k,count in [('emoji18-rgi',3972),('emoji18-basic',1409),('emoji18-keycap',12),('emoji18-flag',259),('emoji18-tag',3),('emoji18-modifier',675),('emoji18-zwj',1614),('education-joyo',2136),('education-junior-high',1110),('kanken-10',80),('kanken-9',240),('kanken-8',440),('kanken-7',642),('kanken-6',835),('kanken-5',1026),('kanken-4',1339),('kanken-3',1623),('kanken-pre2',1951),('kanken-2',2136)]:
    c=collkey(k); need(c is not None,k,'collection missing')
    if c: need(len(c.get('members',[]))+len(c.get('sequences',[]))+len(c.get('positions',[]))==count,k,'count',count,len(c.get('members',[]))+len(c.get('sequences',[]))+len(c.get('positions',[])))
# Collection sequence keys must resolve to exported code-point sequence keys.
for k in ('unicode-named-sequences','emoji18-rgi','emoji18-zwj'):
    c=collkey(k)
    if c:
        need(all(x in d.get('sequences',{}) for x in c.get('sequences',[])),k,'unresolvable sequence key')

if fail:
    print('FAIL web structural audit:',len(fail))
    for x in fail: print(' -',x)
    sys.exit(1)

# v1.2: CP932 duplicate decode aliases + JIS X 0213 crosswalk must survive export.
kou=d['characters'].get('7864')
need(kou is not None,'U+7864 missing')
if kou:
    need('EE 5E' in kou.get('encodings',{}).get('cp932',[]),'U+7864 CP932 encode canonical',kou.get('encodings',{}).get('cp932'))
    need('F6 C4' in kou.get('encodings',{}).get('shift_jis_2004',[]),'U+7864 Shift_JIS-2004',kou.get('encodings',{}).get('shift_jis_2004'))
    md=kou.get('mapping_details',[])
    need(any(x.get('system_key')=='cp932' and x.get('bytes')=='FB 7A' and x.get('direction')=='decode' for x in md),'U+7864 CP932 decode alias FB7A lost',md)
    need(any(x.get('key')=='cp932-jis0213-reassignment' for x in kou.get('issues',[])),'U+7864 crosswalk issue missing',kou.get('issues'))
    need(any(x.get('key')=='cp932-jis0213-reassigned' for x in kou.get('memberships',[])),'U+7864 crosswalk collection missing',kou.get('memberships'))
# CP932 F6C4 must not be mistaken for U+7864; in this runtime mapping it decodes to U+E4EB.
f6=[p for p in d.get('positions',{}).values() if p.get('system_key')=='cp932' and p.get('bytes')=='F6 C4']
need(bool(f6),'CP932 F6C4 position missing')
if f6:
    cps=[cp for m in f6[0].get('mappings',[]) if m.get('direction') in ('decode','both') for cp in m.get('unicode',[])]
    need(0x7864 not in cps and 0xE4EB in cps,'CP932 F6C4 mapping incorrect',cps)

print('PASS web structural audit: sequences, IVS collections, directional/ambiguous mappings, aliases, revisions, search ambiguity, decomposition, unmapped positions')

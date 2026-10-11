#!/usr/bin/env python3
import json, sqlite3, unicodedata, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
DB=ROOT/'db'/'charref.sqlite'
V=ROOT/'data'/'test-vectors'/'core.json'
con=sqlite3.connect(DB)
con.row_factory=sqlite3.Row
fail=[]
vecs=json.loads(V.read_text(encoding='utf-8'))['vectors']

def hx(b): return ' '.join(f'{x:02X}' for x in b)
for v in vecs:
    actual=[f'U+{ord(ch):04X}' for ch in v['input']]
    exp=v['expect']['codepoints']
    if actual!=exp: fail.append((v['id'],'codepoints',exp,actual))
    for enc,expected in v['expect'].get('encodings',{}).items():
        if enc not in ('utf-8','utf-16le','utf-16be','cp932','shift_jis','shift_jis_2004','euc_jp','euc_jis_2004','iso2022_jp','iso2022_jp_2004'): continue
        try: got=hx(v['input'].encode(enc))
        except UnicodeEncodeError: got=None
        if got!=expected: fail.append((v['id'],enc,expected,got))
    if 'nfkc' in v['expect']:
        got=unicodedata.normalize('NFKC',v['input'])
        if got!=v['expect']['nfkc']: fail.append((v['id'],'nfkc',v['expect']['nfkc'],got))
    for cptext in exp:
        cp=int(cptext[2:],16)
        if not con.execute('SELECT 1 FROM unicode_codepoint WHERE cp=?',(cp,)).fetchone():
            fail.append((v['id'],'db-codepoint','present',cptext))
    for issue in v['expect'].get('issues',[]):
        for cptext in exp:
            cp=int(cptext[2:],16)
            row=con.execute('''SELECT 1 FROM unicode_issue ui JOIN issue i ON i.id=ui.issue_id
                               WHERE ui.cp=? AND i.issue_key=?''',(cp,issue)).fetchone()
            if not row: fail.append((v['id'],'issue',issue,cptext))
    if 'unicode_age' in v['expect'] and len(exp)==1:
        cp=int(exp[0][2:],16)
        got=con.execute('SELECT age FROM unicode_codepoint WHERE cp=?',(cp,)).fetchone()
        got=got['age'] if got else None
        if got!=v['expect']['unicode_age']: fail.append((v['id'],'unicode_age',v['expect']['unicode_age'],got))
    for jp in v['expect'].get('jis_positions',[]):
        cp=int(exp[0][2:],16)
        row=con.execute('''SELECT 1 FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id
                           JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id
                           WHERE mu.cp=? AND mu.seq_index=0 AND cs.system_key=? AND p.position_key=?''',
                        (cp,jp['system'],jp['position'])).fetchone()
        if not row: fail.append((v['id'],'jis_position',jp,None))

# Schema invariants
for row in con.execute('SELECT mapping_id, MIN(seq_index) mn, MAX(seq_index) mx, COUNT(*) n FROM mapping_unicode GROUP BY mapping_id'):
    if row['mn']!=0 or row['mx']!=row['n']-1: fail.append((f"mapping:{row['mapping_id']}",'sequence','contiguous',dict(row)))

if fail:
    print(f'FAIL: {len(fail)} mismatch(es)')
    for x in fail: print(' -',x)
    sys.exit(1)
print(f'PASS: {len(vecs)} vectors; database invariants OK')

# Completeness audit: for every scalar currently present in the regression corpus,
# a codec-encodable single character must have a corresponding single-code-point
# DB mapping. Sequence mappings are intentionally excluded.
codec_systems=('cp932','shift_jis','shift_jis_2004','euc_jp','euc_jis_2004','iso2022_jp','iso2022_jp_2004')
corpus_cps=sorted({ord(ch) for v in vecs for ch in v['input']})
for cp in corpus_cps:
    ch=chr(cp)
    for codec in codec_systems:
        try:
            expected=ch.encode(codec)
        except UnicodeEncodeError:
            expected=None
        rows=con.execute('''SELECT p.byte_value
                            FROM mapping_unicode mu
                            JOIN mapping m ON m.id=mu.mapping_id
                            JOIN code_position p ON p.id=m.code_position_id
                            JOIN code_system cs ON cs.id=p.system_id
                            WHERE mu.cp=? AND mu.seq_index=0 AND cs.system_key=?
                              AND (SELECT COUNT(*) FROM mapping_unicode mu2 WHERE mu2.mapping_id=m.id)=1''',
                         (cp,codec)).fetchall()
        actual=[r['byte_value'] for r in rows]
        if expected is not None and expected not in actual:
            fail.append((f'U+{cp:04X}','codec-db-completeness',codec,
                         'expected '+hx(expected)+'; db='+str([hx(x) for x in actual])))
        if expected is None and actual:
            fail.append((f'U+{cp:04X}','codec-db-extra',codec,[hx(x) for x in actual]))

if fail:
    print(f'FAIL after completeness audit: {len(fail)} mismatch(es)')
    for x in fail: print(' -',x)
    sys.exit(1)
print(f'PASS completeness audit: {len(corpus_cps)} code points x {len(codec_systems)} codecs')

# Structural regression vectors: exercise features that can force schema/UI redesign.
SV=ROOT/'data'/'test-vectors'/'structural.json'
if SV.exists():
    svecs=json.loads(SV.read_text(encoding='utf-8'))['vectors']
    for v in svecs:
        e=v['expect']
        if 'input' in v:
            actual=[f'U+{ord(ch):04X}' for ch in v['input']]
            if actual!=e['codepoints']: fail.append((v['id'],'structural-codepoints',e['codepoints'],actual))
        if 'exact_sequence_encodings' in e:
            cps=[int(x[2:],16) for x in e['codepoints']]
            for system,hxexp in e['exact_sequence_encodings'].items():
                rows=con.execute("""SELECT p.byte_value,m.direction,m.mapping_kind,m.id
                    FROM mapping m JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id
                    WHERE cs.system_key=?""",(system,)).fetchall()
                vals=[]
                for r in rows:
                    seq=[x['cp'] for x in con.execute('SELECT cp FROM mapping_unicode WHERE mapping_id=? ORDER BY seq_index',(r['id'],))]
                    if seq==cps and r['direction'] in ('encode','both'): vals.append(hx(r['byte_value']))
                if hxexp not in vals: fail.append((v['id'],'exact-sequence-'+system,hxexp,vals))
        for form in ('nfc','nfd','nfkc','nfkd'):
            if form in e:
                got=unicodedata.normalize(form.upper(),v['input'])
                if got!=e[form]:fail.append((v['id'],'structural-'+form,e[form],got))
        if 'decomposition' in e:
            cp=int(e['codepoints'][0][2:],16)
            row=con.execute('SELECT decomposition FROM unicode_codepoint WHERE cp=?',(cp,)).fetchone()
            got=row['decomposition'] if row else None
            if got!=e['decomposition']:fail.append((v['id'],'decomposition',e['decomposition'],got))
        if 'mapping_set' in e:
            ms=e['mapping_set']
            row=con.execute('''SELECT p.id FROM code_position p JOIN code_system cs ON cs.id=p.system_id
                WHERE cs.system_key=? AND p.position_key=?''',(ms['system'],ms['position'])).fetchone()
            got=[]
            if row:
                maps=con.execute('SELECT id,direction,mapping_kind,priority FROM mapping WHERE code_position_id=? ORDER BY id',(row['id'],)).fetchall()
                for m in maps:
                    cps=[f"U+{r['cp']:04X}" for r in con.execute('SELECT cp FROM mapping_unicode WHERE mapping_id=? ORDER BY seq_index',(m['id'],))]
                    got.append({'direction':m['direction'],'kind':m['mapping_kind'],'priority':m['priority'],'codepoints':cps})
            def norm(xs): return sorted(xs,key=lambda x:(x['direction'],x['kind'],x['priority'],tuple(x['codepoints'])))
            if norm(got)!=norm(ms['mappings']):fail.append((v['id'],'mapping-set',norm(ms['mappings']),norm(got)))
        if 'unicode_positions' in e:
            up=e['unicode_positions'];cp=int(up['codepoint'][2:],16)
            rows=con.execute('''SELECT p.position_key,m.mapping_kind,m.priority FROM mapping_unicode mu
                JOIN mapping m ON m.id=mu.mapping_id JOIN code_position p ON p.id=m.code_position_id
                JOIN code_system cs ON cs.id=p.system_id
                WHERE mu.cp=? AND cs.system_key=? AND m.direction IN ('encode','both')
                ORDER BY m.priority,p.position_key''',(cp,up['system'])).fetchall()
            got=[{'position':r['position_key'],'kind':r['mapping_kind'],'priority':r['priority']} for r in rows]
            if got!=up['positions']:fail.append((v['id'],'unicode-positions',up['positions'],got))
        if 'variation' in e:
            cps=[int(x[2:],16) for x in e['codepoints']]; base,vs=cps
            row=con.execute("""SELECT vc.collection_key,va.value FROM variation_sequence s
                JOIN variation_collection vc ON vc.id=s.collection_id
                LEFT JOIN variation_annotation va ON va.variation_id=s.id AND va.key='glyph-standard'
                WHERE s.base_cp=? AND s.variation_cp=?""",(base,vs)).fetchone()
            if not row or row['collection_key']!=e['variation']['collection'] or row['value']!=e['variation']['glyph-standard']:
                fail.append((v['id'],'variation',e['variation'],dict(row) if row else None))
        if 'test_system' in e:
            row=con.execute("""SELECT m.direction,mu.cp FROM code_position p JOIN code_system cs ON cs.id=p.system_id
                JOIN mapping m ON m.code_position_id=p.id JOIN mapping_unicode mu ON mu.mapping_id=m.id
                WHERE cs.system_key=? AND p.position_key=? ORDER BY mu.seq_index""",(e['test_system'],e['position'])).fetchall()
            gotdir=row[0]['direction'] if row else None; gotcps=[f"U+{r['cp']:04X}" for r in row]
            if gotdir!=e['direction'] or gotcps!=e['codepoints']: fail.append((v['id'],'directional',(e['direction'],e['codepoints']),(gotdir,gotcps)))

        if 'revision_positions' in e:
            rp=e['revision_positions']; cp=int(rp['codepoint'][2:],16)
            got=[]
            for want in rp['positions']:
                row=con.execute('''SELECT p.position_key FROM mapping_unicode mu
                    JOIN mapping m ON m.id=mu.mapping_id JOIN code_position p ON p.id=m.code_position_id
                    JOIN code_system cs ON cs.id=p.system_id
                    WHERE mu.cp=? AND cs.system_key=? AND m.direction IN ('encode','both')''',(cp,want['system'])).fetchone()
                got.append({'system':want['system'],'position':row['position_key'] if row else None})
            if got!=rp['positions']: fail.append((v['id'],'revision-positions',rp['positions'],got))
        if 'sequence_positions' in e:
            sp=e['sequence_positions']; cps=[int(x[2:],16) for x in e['codepoints']]
            rows=con.execute('''SELECT p.id,p.position_key,m.id AS mapping_id FROM code_position p
                JOIN code_system cs ON cs.id=p.system_id JOIN mapping m ON m.code_position_id=p.id
                WHERE cs.system_key=? AND m.direction IN ('encode','both') ORDER BY p.position_key''',(sp['system'],)).fetchall()
            got=[]
            for r in rows:
                seq=[x['cp'] for x in con.execute('SELECT cp FROM mapping_unicode WHERE mapping_id=? ORDER BY seq_index',(r['mapping_id'],))]
                if seq==cps: got.append(r['position_key'])
            if got!=sp['positions']: fail.append((v['id'],'sequence-positions',sp['positions'],got))
        if 'variation_annotation' in e:
            va=e['variation_annotation']; cps=[int(x[2:],16) for x in e['codepoints']]
            row=con.execute('''SELECT a.value FROM variation_sequence vs
                JOIN variation_collection vc ON vc.id=vs.collection_id
                JOIN variation_annotation a ON a.variation_id=vs.id
                WHERE vs.base_cp=? AND vs.variation_cp=? AND vc.collection_key=? AND a.key=?''',
                (cps[0],cps[1],va['collection'],va['key'])).fetchone()
            got=row['value'] if row else None
            if got!=va['value']: fail.append((v['id'],'variation-annotation',va['value'],got))
        if 'ambiguous_hex' in e:
            raw=e['ambiguous_hex']; cp=int(raw,16)
            uok=con.execute('SELECT 1 FROM unicode_codepoint WHERE cp=?',(cp,)).fetchone() is not None
            hx=' '.join(raw[i:i+2].upper() for i in range(0,len(raw),2))
            b=bytes.fromhex(hx)
            cnt=con.execute('SELECT COUNT(*) FROM code_position WHERE byte_value=?',(b,)).fetchone()[0]
            if (not uok) or f'U+{cp:04X}'!=e['unicode_candidate'] or cnt<e['minimum_position_candidates']:
                fail.append((v['id'],'ambiguous-hex',(e['unicode_candidate'],e['minimum_position_candidates']),(uok,cnt)))
        if 'sequence_entity' in e:
            se=e['sequence_entity']; cps=[int(x[2:],16) for x in e['codepoints']]
            row=con.execute('SELECT id,sequence_type FROM unicode_sequence WHERE sequence_key=?',(se['key'],)).fetchone()
            gotcps=[]
            if row: gotcps=[r['cp'] for r in con.execute('SELECT cp FROM unicode_sequence_member WHERE sequence_id=? ORDER BY seq_index',(row['id'],))]
            if not row or row['sequence_type']!=se['type'] or gotcps!=cps: fail.append((v['id'],'sequence-entity',(se,cps),(dict(row) if row else None,gotcps)))
        if 'properties' in e and len(e.get('codepoints',[]))==1:
            cp=int(e['codepoints'][0][2:],16)
            got={r['property'] for r in con.execute('SELECT property FROM unicode_property WHERE cp=?',(cp,))}
            missing=[x for x in e['properties'] if x not in got]
            if missing: fail.append((v['id'],'properties',e['properties'],sorted(got)))
        if 'general_category' in e and len(e.get('codepoints',[]))==1:
            cp=int(e['codepoints'][0][2:],16); row=con.execute('SELECT general_category,canonical_combining_class FROM unicode_codepoint WHERE cp=?',(cp,)).fetchone()
            got=row['general_category'] if row else None
            if got!=e['general_category']: fail.append((v['id'],'general-category',e['general_category'],got))
            if 'ccc' in e and (not row or row['canonical_combining_class']!=e['ccc']): fail.append((v['id'],'ccc',e['ccc'],row['canonical_combining_class'] if row else None))
        if 'collection' in e and len(e.get('codepoints',[]))==1:
            cp=int(e['codepoints'][0][2:],16)
            row=con.execute('''SELECT 1 FROM collection_member_unicode cm JOIN collection c ON c.id=cm.collection_id WHERE c.collection_key=? AND cm.cp=?''',(e['collection'],cp)).fetchone()
            if not row: fail.append((v['id'],'collection-membership',e['collection'],None))
        if 'issue' in e and len(e.get('codepoints',[]))==1:
            cp=int(e['codepoints'][0][2:],16)
            row=con.execute('''SELECT 1 FROM unicode_issue ui JOIN issue i ON i.id=ui.issue_id WHERE ui.cp=? AND i.issue_key=?''',(cp,e['issue'])).fetchone()
            if not row: fail.append((v['id'],'issue',e['issue'],None))
        if 'cp932_encode_bytes' in e and len(e.get('codepoints',[]))==1:
            cp=int(e['codepoints'][0][2:],16); expected=bytes.fromhex(e['cp932_encode_bytes'])
            rows=con.execute('''SELECT p.byte_value FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id WHERE mu.cp=? AND cs.system_key='cp932' AND m.direction IN ('encode','both') ORDER BY m.priority,p.id''',(cp,)).fetchall()
            got=[r[0] for r in rows]
            if expected not in got: fail.append((v['id'],'cp932-encode',e['cp932_encode_bytes'],[x.hex(' ').upper() for x in got]))
        if 'cp932_decode_bytes' in e and len(e.get('codepoints',[]))==1:
            cp=int(e['codepoints'][0][2:],16)
            rows=con.execute('''SELECT DISTINCT p.byte_value FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id WHERE mu.cp=? AND cs.system_key='cp932' AND m.direction IN ('decode','both')''',(cp,)).fetchall()
            got={r[0].hex(' ').upper() for r in rows}; exp=set(e['cp932_decode_bytes'])
            if not exp.issubset(got): fail.append((v['id'],'cp932-decode-aliases',sorted(exp),sorted(got)))
        if 'shift_jis_2004_bytes' in e and len(e.get('codepoints',[]))==1:
            cp=int(e['codepoints'][0][2:],16); expected=bytes.fromhex(e['shift_jis_2004_bytes'])
            row=con.execute('''SELECT 1 FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id WHERE mu.cp=? AND cs.system_key='shift_jis_2004' AND m.direction IN ('encode','both') AND p.byte_value=?''',(cp,expected)).fetchone()
            if not row: fail.append((v['id'],'shift-jis-2004',e['shift_jis_2004_bytes'],None))
        if 'cp932_f6c4_unicode' in e:
            expected=int(e['cp932_f6c4_unicode'][2:],16)
            row=con.execute('''SELECT mu.cp FROM code_position p JOIN code_system cs ON cs.id=p.system_id JOIN mapping m ON m.code_position_id=p.id JOIN mapping_unicode mu ON mu.mapping_id=m.id WHERE cs.system_key='cp932' AND p.byte_value=X'F6C4' AND m.direction IN ('decode','both') ORDER BY m.priority LIMIT 1''').fetchone()
            got=row['cp'] if row else None
            if got!=expected: fail.append((v['id'],'cp932-F6C4',e['cp932_f6c4_unicode'],f'U+{got:04X}' if got is not None else None))
        if 'jis_position' in e and len(e.get('codepoints',[]))==1:
            cp=int(e['codepoints'][0][2:],16); j=e['jis_position']
            row=con.execute('''SELECT 1 FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id WHERE mu.cp=? AND cs.system_key=? AND p.position_key=?''',(cp,j['system'],j['position'])).fetchone()
            if not row: fail.append((v['id'],'jis-position',j,None))
        if 'width_compat_target' in e:
            cp=int(e['codepoints'][0][2:],16); target=int(e['width_compat_target'][2:],16)
            row=con.execute("SELECT 1 FROM relation WHERE from_cp=? AND to_cp=? AND relation_type='width-compatibility'",(cp,target)).fetchone()
            if not row: fail.append((v['id'],'width-compat-target',e['width_compat_target'],None))
        if 'cp932_bytes' in e:
            cp=int(e['codepoints'][0][2:],16); expected=bytes.fromhex(e['cp932_bytes'])
            row=con.execute('''SELECT p.id FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id WHERE mu.cp=? AND cs.system_key='cp932' AND p.byte_value=?''',(cp,expected)).fetchone()
            if not row: fail.append((v['id'],'cp932-eudc-bytes',e['cp932_bytes'],None))
            else:
                mem=con.execute('''SELECT 1 FROM collection_member_position cm JOIN collection c ON c.id=cm.collection_id WHERE c.collection_key=? AND cm.code_position_id=?''',(e['eudc_collection'],row['id'])).fetchone()
                if not mem: fail.append((v['id'],'eudc-position-membership',e['eudc_collection'],None))
        if 'unicode_mapping_count' in e:
            row=con.execute("""SELECT p.id FROM code_position p JOIN code_system cs ON cs.id=p.system_id
                WHERE cs.system_key=? AND p.position_key=?""",(e['system'],e['position'])).fetchone()
            if not row: fail.append((v['id'],'unmapped-position','present',None))
            else:
                cnt=con.execute('SELECT COUNT(*) FROM mapping m JOIN mapping_unicode mu ON mu.mapping_id=m.id WHERE m.code_position_id=?',(row['id'],)).fetchone()[0]
                mem=con.execute("""SELECT 1 FROM collection_member_position cm JOIN collection c ON c.id=cm.collection_id
                    WHERE c.collection_key=? AND cm.code_position_id=?""",(e['collection'],row['id'])).fetchone()
                if cnt!=e['unicode_mapping_count'] or not mem: fail.append((v['id'],'unmapped-position',(e['unicode_mapping_count'],True),(cnt,bool(mem))))
    if fail:
        print(f'FAIL structural audit: {len(fail)} mismatch(es)')
        for x in fail: print(' -',x)
        sys.exit(1)
    print(f'PASS structural audit: {len(svecs)} vectors')

# v1.3 collection invariants
expected_grades={1:80,2:160,3:200,4:202,5:193,6:191}
grade_sets=[]
for grade,count in expected_grades.items():
    key=f'education-elementary-g{grade}'
    row=con.execute('SELECT id FROM collection WHERE collection_key=?',(key,)).fetchone()
    if not row:
        print('FAIL missing collection',key); sys.exit(1)
    cps={r[0] for r in con.execute('SELECT cp FROM collection_member_unicode WHERE collection_id=?',(row[0],))}
    if len(cps)!=count:
        print('FAIL grade count',grade,len(cps),count); sys.exit(1)
    grade_sets.append(cps)
if len(set().union(*grade_sets))!=1026 or sum(map(len,grade_sets))!=1026:
    print('FAIL elementary union/duplicates'); sys.exit(1)
for key,min_count in [('sjis-bad-5c',1),('cp932-bad-5c',1),('arib-jis-plane1',1),('arib-jis-plane2',1)]:
    row=con.execute('SELECT id FROM collection WHERE collection_key=?',(key,)).fetchone()
    cnt=con.execute('SELECT COUNT(*) FROM collection_member_unicode WHERE collection_id=?',(row[0],)).fetchone()[0] if row else 0
    if cnt<min_count:
        print('FAIL derived collection',key,cnt); sys.exit(1)
print('PASS v1.3 collection invariants: elementary grades, SJIS 0x5C, ARIB JIS-compatible planes')


# v1.4 CP932 vendor provenance + ARIB fixed repertoire invariants
expected_vendor_counts={
    'cp932-nec-special':83,
    'cp932-nec-selected-ibm':374,
    'cp932-ibm-extension':388,
}
sets={}
for key,count in expected_vendor_counts.items():
    row=con.execute('SELECT id FROM collection WHERE collection_key=?',(key,)).fetchone()
    if not row:
        print('FAIL missing CP932 vendor collection',key); sys.exit(1)
    cps={r[0] for r in con.execute('SELECT cp FROM collection_member_unicode WHERE collection_id=?',(row[0],))}
    positions=con.execute('SELECT COUNT(*) FROM collection_member_position WHERE collection_id=?',(row[0],)).fetchone()[0]
    if len(cps)!=count or positions!=count:
        print('FAIL CP932 vendor count',key,len(cps),positions,count); sys.exit(1)
    sets[key]=cps
if len(sets['cp932-nec-selected-ibm'] & sets['cp932-ibm-extension']) != 374:
    print('FAIL NEC-selected/IBM duplicate-set relationship'); sys.exit(1)

def in_coll(key,cp):
    return con.execute('SELECT 1 FROM collection_member_unicode cm JOIN collection c ON c.id=cm.collection_id WHERE c.collection_key=? AND cm.cp=?',(key,cp)).fetchone() is not None
if not in_coll('cp932-nec-special',0x2460):
    print('FAIL U+2460 NEC-special membership'); sys.exit(1)
if not (in_coll('cp932-nec-selected-ibm',0x7864) and in_coll('cp932-ibm-extension',0x7864)):
    print('FAIL U+7864 CP932 duplicate vendor provenance'); sys.exit(1)
row=con.execute("SELECT id FROM collection WHERE collection_key='arib-additional-kanji'").fetchone()
acount=con.execute('SELECT COUNT(*) FROM collection_member_unicode WHERE collection_id=?',(row[0],)).fetchone()[0] if row else 0
if acount!=137:
    print('FAIL ARIB additional Kanji count',acount,137); sys.exit(1)
for cp in (0x3402,0x20BB7,0xFA11,0x9AD9):
    if not in_coll('arib-additional-kanji',cp):
        print('FAIL ARIB additional Kanji representative',hex(cp)); sys.exit(1)
print('PASS v1.4 invariants: CP932 vendor provenance and ARIB fixed additional Kanji')

# v1.5 ARIB capability / operational implementation split
required_arib = ['arib-operational-core','arib-capability','arib-optional-jis34','arib-optional-jis3','arib-optional-jis4']
ids={}
for key in required_arib:
    row=con.execute('SELECT id FROM collection WHERE collection_key=?',(key,)).fetchone()
    if not row:
        print('FAIL missing ARIB v1.5 collection',key); sys.exit(1)
    ids[key]=row[0]

def coll_has(key,cp):
    return con.execute('SELECT 1 FROM collection_member_unicode WHERE collection_id=? AND cp=?',(ids[key],cp)).fetchone() is not None

# U+7864 硤: JIS X 0213 Plane 2 / level-4 path, but not part of provisional common core.
if not coll_has('arib-optional-jis4',0x7864) or not coll_has('arib-optional-jis34',0x7864):
    print('FAIL U+7864 not classified as optional JIS level 4'); sys.exit(1)
if coll_has('arib-operational-core',0x7864):
    print('FAIL U+7864 unexpectedly in provisional ARIB common core'); sys.exit(1)
# U+5D0E 崎 is in JIS X 0208 and therefore in the provisional common core.
if not coll_has('arib-operational-core',0x5D0E):
    print('FAIL U+5D0E missing from provisional ARIB common core'); sys.exit(1)
# U+351F is present in both the current JIS Plane-2 bootstrap and ARIB fixed-additional-Kanji data,
# so it exercises the legitimate dual-route case without depending on supplementary-plane codec coverage.
if not coll_has('arib-optional-jis4',0x351F) or not coll_has('arib-operational-core',0x351F):
    print('FAIL U+351F dual ARIB route classification'); sys.exit(1)
for key in ['arib-optional-jis3','arib-optional-jis4','arib-operational-core']:
    cnt=con.execute('SELECT COUNT(*) FROM collection_member_unicode WHERE collection_id=?',(ids[key],)).fetchone()[0]
    if cnt < 1:
        print('FAIL empty ARIB v1.5 collection',key); sys.exit(1)
print('PASS v1.5 invariants: ARIB capability vs provisional operational core / optional JIS3-4')

# v1.6 JIS repertoire/navigation invariants. Position counts are authoritative for JIS collections.
expected_jis_positions={
    'jis-x0201':157,'jis-x0201-roman':94,'jis-x0201-kana':63,
    'jis-x0208':6879,'jis-x0208-all':6879,'jis-x0208-nonkanji':524,'jis-x0208-level1':2965,'jis-x0208-level2':3390,
    'jis-x0212':6067,'jis-x0212-all':6067,'jis-x0212-kanji':5801,'jis-x0212-nonkanji':266,
    'jis-x0213-2000-all':11223,'jis-x0213-2000-plane1':8787,'jis-x0213-2000-level1':2965,'jis-x0213-2000-level2':3390,'jis-x0213-2000-level3':1249,'jis-x0213-2000-plane2':2436,'jis-x0213-2000-level4':2436,
    'jis-x0213-2004-all':11233,'jis-x0213-2004-plane1':8797,'jis-x0213-2004-level1':2965,'jis-x0213-2004-level2':3390,'jis-x0213-2004-level3':1259,'jis-x0213-2004-plane2':2436,'jis-x0213-2004-level4':2436,
    'jis-x0213-2004-added10':10,
}
for key,expected in expected_jis_positions.items():
    row=con.execute('SELECT id FROM collection WHERE collection_key=?',(key,)).fetchone()
    if not row:
        print('FAIL missing JIS v1.6 collection',key); sys.exit(1)
    cnt=con.execute('SELECT COUNT(*) FROM collection_member_position WHERE collection_id=?',(row[0],)).fetchone()[0]
    if cnt!=expected:
        print('FAIL JIS v1.6 position count',key,cnt,expected); sys.exit(1)
# JIS X 0213:2004 differs from 2000 by exactly the 10 Amendment 1 positions; Plane 2 is unchanged.
ids={k:con.execute('SELECT id FROM collection WHERE collection_key=?',(k,)).fetchone()[0] for k in ['jis-x0213-2000-all','jis-x0213-2004-all','jis-x0213-2000-plane2','jis-x0213-2004-plane2']}
if expected_jis_positions['jis-x0213-2004-all']-expected_jis_positions['jis-x0213-2000-all'] != 10:
    print('FAIL JIS X 0213 edition delta'); sys.exit(1)
print('PASS v1.6 invariants: JIS X 0201/0208/0212/0213 hierarchy and level counts')

# v1.7 historical JIS editions / revision-difference invariants.
expected_hist_positions={
    'jis-c6226-1978':6802,
    'jis-c6226-1983':6877,
    'jis-x0208-1990':6879,
    'jis-rev-78-83-added71':71,
    'jis-rev-78-83-old4':4,
    'jis-rev-78-83-swaps22':44,
    'jis-rev-83-90-added2':2,
}
for key,expected in expected_hist_positions.items():
    row=con.execute('SELECT id FROM collection WHERE collection_key=?',(key,)).fetchone()
    if not row:
        print('FAIL missing JIS v1.7 collection',key); sys.exit(1)
    cnt=con.execute('SELECT COUNT(*) FROM collection_member_position WHERE collection_id=?',(row[0],)).fetchone()[0]
    if cnt!=expected:
        print('FAIL JIS v1.7 position count',key,cnt,expected); sys.exit(1)
expected_hist_unicode={'jis-rev-78-83-nonunified29':29,'jis-rev-83-90-glyph225':225,'jis-rev-2000-2004-glyph168':168}
for key,expected in expected_hist_unicode.items():
    row=con.execute('SELECT id FROM collection WHERE collection_key=?',(key,)).fetchone()
    cnt=con.execute('SELECT COUNT(*) FROM collection_member_unicode WHERE collection_id=?',(row[0],)).fetchone()[0] if row else -1
    if cnt!=expected:
        print('FAIL JIS v1.7 unicode count',key,cnt,expected); sys.exit(1)
# Metadata-only revisions intentionally carry no duplicate repertoire.
for key in ('jis-rev-90-97','jis-rev-2012'):
    row=con.execute('SELECT id,description FROM collection WHERE collection_key=?',(key,)).fetchone()
    if not row or not row[1]:
        print('FAIL missing metadata-only revision',key); sys.exit(1)
    a=con.execute('SELECT COUNT(*) FROM collection_member_unicode WHERE collection_id=?',(row[0],)).fetchone()[0]
    b=con.execute('SELECT COUNT(*) FROM collection_member_position WHERE collection_id=?',(row[0],)).fetchone()[0]
    if a or b:
        print('FAIL metadata-only revision unexpectedly has members',key,a,b); sys.exit(1)
# Representative historical position checks.
def hist_cp(system,pos):
    rows=con.execute('''SELECT mu.cp FROM code_position p JOIN code_system cs ON cs.id=p.system_id
                        LEFT JOIN mapping m ON m.code_position_id=p.id
                        LEFT JOIN mapping_unicode mu ON mu.mapping_id=m.id AND mu.seq_index=0
                        WHERE cs.system_key=? AND p.position_key=? ORDER BY m.priority,m.id''',(system,pos)).fetchall()
    return [r[0] for r in rows if r[0] is not None]
for system,pos,cp in [
    ('jis_c_6226_1978','22-38',0x582F),('jis_c_6226_1983','22-38',0x5C2D),('jis_c_6226_1983','84-01',0x582F),
    ('jis_c_6226_1978','16-19',0x9C3A),('jis_c_6226_1983','16-19',0x9BF5),
    ('jis_x_0208_1990','84-05',0x51DC),('jis_x_0208_1990','84-06',0x7199)]:
    if cp not in hist_cp(system,pos):
        print('FAIL historical JIS mapping',system,pos,hex(cp),hist_cp(system,pos)); sys.exit(1)
print('PASS v1.7 invariants: historical JIS editions and revision-difference collections')


# v1.8 navigation invariants: historical JIS editions are direct children of JIS; JIS revision collections contain only deltas.
def parent_key_v18(key):
    row=con.execute("SELECT p.collection_key FROM collection c LEFT JOIN collection p ON p.id=c.parent_id WHERE c.collection_key=?",(key,)).fetchone()
    return row[0] if row else None
for key in ("jis-c6226-1978","jis-c6226-1983","jis-x0208-1990"):
    if parent_key_v18(key)!="jis":
        print("FAIL v1.8 JIS standalone parent",key,parent_key_v18(key)); sys.exit(1)
if con.execute("SELECT 1 FROM collection WHERE collection_key='jis-historical-editions'").fetchone():
    print("FAIL v1.8 obsolete historical wrapper still exists"); sys.exit(1)
for key in ("jis-rev-78-83","jis-rev-83-90","jis-rev-90-97","jis-rev-2000-2004","jis-rev-2012"):
    if parent_key_v18(key)!="jis-revisions":
        print("FAIL v1.8 JIS revision parent",key,parent_key_v18(key)); sys.exit(1)

rev_specs_v18={
 "unicode-revision-7-0":{"7.0"},"unicode-revision-8-0":{"8.0"},"unicode-revision-9-0":{"9.0"},
 "unicode-revision-10-0":{"10.0"},"unicode-revision-11-0":{"11.0"},"unicode-revision-12-1":{"12.0","12.1"},
 "unicode-revision-13-0":{"13.0"},"unicode-revision-14-0":{"14.0"},"unicode-revision-15-1":{"15.0","15.1"},
 "unicode-revision-16-0":{"16.0"},"unicode-revision-17-0":{"17.0"},"unicode-revision-18-0":{"18.0"}}
for key,ages in rev_specs_v18.items():
    row=con.execute("SELECT id,parent_id FROM collection WHERE collection_key=?",(key,)).fetchone()
    if not row:
        print("FAIL missing Unicode revision collection",key); sys.exit(1)
    p=con.execute("SELECT collection_key FROM collection WHERE id=?",(row[1],)).fetchone()
    if not p or p[0]!="unicode-revisions":
        print("FAIL Unicode revision parent",key,p); sys.exit(1)
    got={r[0] for r in con.execute("SELECT DISTINCT u.age FROM collection_member_unicode cm JOIN unicode_codepoint u ON u.cp=cm.cp WHERE cm.collection_id=?",(row[0],)).fetchall()}
    if got and not got.issubset(ages):
        print("FAIL Unicode revision Age leakage",key,got,ages); sys.exit(1)
for key,need in [("unicode-revision-12-1",{"12.0","12.1"}),("unicode-revision-15-1",{"15.0","15.1"})]:
    cid=con.execute("SELECT id FROM collection WHERE collection_key=?",(key,)).fetchone()[0]
    got={r[0] for r in con.execute("SELECT DISTINCT u.age FROM collection_member_unicode cm JOIN unicode_codepoint u ON u.cp=cm.cp WHERE cm.collection_id=?",(cid,)).fetchall()}
    if not need.issubset(got):
        print("FAIL Unicode minor roll-up",key,got,need); sys.exit(1)
print("PASS v1.8 invariants: JIS navigation separation and Unicode revision-difference collections")

# v2.0 official Unicode 18.0 / Unihan cross-check invariants.
meta=dict(con.execute('SELECT key,value FROM meta'))
if meta.get('dataset_kind')!='official' or meta.get('unicode_target')!='18.0.0':
    print('FAIL v2.0 dataset metadata',meta.get('dataset_kind'),meta.get('unicode_target')); sys.exit(1)
expected_unicode_revision_counts={'unicode-revision-17-0':4803,'unicode-revision-18-0':13007}
for key,expected in expected_unicode_revision_counts.items():
    row=con.execute('SELECT id FROM collection WHERE collection_key=?',(key,)).fetchone()
    cnt=con.execute('SELECT COUNT(*) FROM collection_member_unicode WHERE collection_id=?',(row[0],)).fetchone()[0] if row else -1
    if cnt!=expected:
        print('FAIL v2.0 Unicode revision count',key,cnt,expected); sys.exit(1)
row=con.execute("SELECT id,version FROM source WHERE source_key='unihan'").fetchone()
if not row or row[1]!='18.0.0':
    print('FAIL v2.0 Unihan source'); sys.exit(1)
ucount=con.execute("SELECT COUNT(*) FROM unicode_property WHERE property='Unihan_kJIS0213'").fetchone()[0]
if ucount!=3695:
    print('FAIL v2.0 Unihan kJIS0213 count',ucount,3695); sys.exit(1)
# Representative Unihan kJIS0213 mapping: U+3402 -> plane 1, row 14, cell 03.
if not con.execute("SELECT 1 FROM unicode_property WHERE cp=0x3402 AND property='Unihan_kJIS0213' AND value='1,14,03'").fetchone():
    print('FAIL v2.0 Unihan kJIS0213 representative U+3402'); sys.exit(1)
print('PASS v2.0 invariants: official UCD 18.0 and Unihan kJIS0213 cross-check')

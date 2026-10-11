#!/usr/bin/env python3
import json, sqlite3, unicodedata, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / 'db' / 'charref.sqlite'
SCHEMA = ROOT / 'db' / 'schema.sql'
VECTORS = ROOT / 'data' / 'test-vectors' / 'core.json'
ISSUES = ROOT / 'data' / 'custom' / 'issues' / 'issues.json'


def bhex(s):
    if s is None: return None
    return bytes.fromhex(s)


def prototype_age(cp):
    # Prototype coverage for the current regression corpus.
    # Full builds will import Unicode 18.0 DerivedAge.txt.
    if cp == 0x1F600:
        return '6.1'
    if 0x20000 <= cp <= 0x2A6D6:
        return '3.1'
    if cp in (0xE0100, 0xE0101):
        return '4.0'
    # All remaining code points currently present in the prototype corpus
    # are assigned in Unicode 1.1.
    return '1.1'

def add_mapping(cur, systems, cache, system_key, hx, cps, source_id, note, *, plane=None, row=None, cell=None, position_key=None):
    key=(position_key or hx.replace(' ','').upper())
    ck=(system_key,key)
    if ck not in cache:
        raw=bytes.fromhex(hx) if hx else None
        numeric=int.from_bytes(raw,'big') if raw is not None and len(raw) <= 8 else None
        cur.execute('INSERT INTO code_position(system_id,position_key,plane,row_no,cell_no,byte_value,numeric_value,source_id) VALUES (?,?,?,?,?,?,?,?)',
                    (systems[system_key],key,plane,row,cell,raw,numeric,source_id))
        cache[ck]=cur.lastrowid
    posid=cache[ck]
    cur.execute('INSERT INTO mapping(code_position_id,direction,mapping_kind,source_id,notes) VALUES (?,?,?,?,?)',
                (posid,'both','prototype',source_id,note))
    mid=cur.lastrowid
    for i,cp in enumerate(cps):
        cur.execute('INSERT INTO mapping_unicode(mapping_id,seq_index,cp) VALUES (?,?,?)',(mid,i,cp))
    return posid

def add_derived_encodings_and_jis(cur, systems, cache, cps, source_id, note):
    text=''.join(chr(cp) for cp in cps)
    if len(cps) != 1:
        return
    cp=cps[0]
    ch=chr(cp)
    for syskey,codec in [('cp932','cp932'),('shift_jis','shift_jis'),('shift_jis_2004','shift_jis_2004'),('euc_jp','euc_jp'),('euc_jis_2004','euc_jis_2004'),('iso2022_jp','iso2022_jp'),('iso2022_jp_2004','iso2022_jp_2004')]:
        try:
            hx=ch.encode(codec).hex(' ').upper()
        except UnicodeEncodeError:
            continue
        add_mapping(cur,systems,cache,syskey,hx,[cp],source_id,note)

    # JIS X 0201 / 0208 positions from EUC-JP.
    try:
        b=ch.encode('euc_jp')
        if len(b)==2 and b[0]==0x8E and 0xA1 <= b[1] <= 0xDF:
            jisbyte=b[1]-0x80
            add_mapping(cur,systems,cache,'jis_x_0201_kana',f'{jisbyte:02X}',[cp],source_id,note,position_key=f'0x{jisbyte:02X}')
        elif len(b)==2 and all(0xA1 <= x <= 0xFE for x in b):
            row,cell=b[0]-0xA0,b[1]-0xA0
            add_mapping(cur,systems,cache,'jis_x_0208',b.hex(' ').upper(),[cp],source_id,note,row=row,cell=cell,position_key=f'{row:02d}-{cell:02d}')
    except UnicodeEncodeError:
        pass

    # JIS X 0213:2004 positions from EUC-JIS-2004.
    try:
        b=ch.encode('euc_jis_2004')
        if len(b)==2 and all(0xA1 <= x <= 0xFE for x in b):
            plane,row,cell=1,b[0]-0xA0,b[1]-0xA0
            add_mapping(cur,systems,cache,'jis_x_0213_2004',b.hex(' ').upper(),[cp],source_id,note,plane=plane,row=row,cell=cell,position_key=f'{plane}-{row:02d}-{cell:02d}')
        elif len(b)==3 and b[0]==0x8F and all(0xA1 <= x <= 0xFE for x in b[1:]):
            plane,row,cell=2,b[1]-0xA0,b[2]-0xA0
            add_mapping(cur,systems,cache,'jis_x_0213_2004',b.hex(' ').upper(),[cp],source_id,note,plane=plane,row=row,cell=cell,position_key=f'{plane}-{row:02d}-{cell:02d}')
    except UnicodeEncodeError:
        pass

if DB.exists(): DB.unlink()
con = sqlite3.connect(DB)
con.executescript(SCHEMA.read_text(encoding='utf-8'))
cur = con.cursor()

cur.executemany('INSERT INTO meta(key,value) VALUES (?,?)', [
    ('schema_version','0.1'),('dataset_kind','prototype'),('unicode_target','18.0.0')])

cur.execute("INSERT INTO source(source_key,title,publisher,version,notes) VALUES (?,?,?,?,?)",
            ('prototype','Prototype/test-vector data','charref','0.1','Values are for schema/UI bring-up; authoritative importers will replace this dataset.'))
source_id = cur.lastrowid

systems = {}
for key,title,typ in [
    ('cp932','Windows-31J / CP932','encoding'),
    ('shift_jis','Shift_JIS (JIS X 0208)','encoding'),
    ('shift_jis_2004','Shift_JIS-2004 (JIS X 0213:2004)','encoding'),
    ('euc_jp','EUC-JP','encoding'),
    ('euc_jis_2004','EUC-JIS-2004 (JIS X 0213:2004)','encoding'),
    ('iso2022_jp','ISO-2022-JP','encoding'),
    ('iso2022_jp_2004','ISO-2022-JP-2004','encoding'),
    ('jis_x_0201_kana','JIS X 0201 Katakana','standard-position'),
    ('jis_x_0208','JIS X 0208','standard-position'),
    ('jis_x_0213_2004','JIS X 0213:2004','standard-position'),
]:
    cur.execute('INSERT INTO code_system(system_key,title,system_type,source_id) VALUES (?,?,?,?)',(key,title,typ,source_id))
    systems[key]=cur.lastrowid

# Root collections for initial UI tree.
collections = [
 ('unicode',None,'Unicode','root',10),
 ('jis',None,'JIS','root',20),
 ('pc-net',None,'PC / ネット','root',30),
 ('society',None,'社会','root',40),
 ('issues',None,'文字コード問題','root',50),
]
ids={}
for key,parent,title,typ,order in collections:
    cur.execute('INSERT INTO collection(collection_key,parent_id,title,collection_type,source_id,sort_order) VALUES (?,?,?,?,?,?)',
                (key, ids.get(parent), title, typ, source_id, order))
    ids[key]=cur.lastrowid
for key,parent,title,typ,order in [
    ('cp932-repertoire','pc-net','CP932','encoding-repertoire',10),
    ('sjis-bad','issues','SJISダメ文字','issue',10),
    ('wave-dash','issues','波ダッシュ問題','issue',20),
    ('jis2004-glyph','issues','JIS90/JIS2004字形差','issue',30),
]:
    cur.execute('INSERT INTO collection(collection_key,parent_id,title,collection_type,source_id,sort_order) VALUES (?,?,?,?,?,?)',
                (key,ids[parent],title,typ,source_id,order)); ids[key]=cur.lastrowid

issue_ids={}
for it in json.loads(ISSUES.read_text(encoding='utf-8'))['issues']:
    cur.execute('INSERT INTO issue(issue_key,title,category,severity,description,source_id) VALUES (?,?,?,?,?,?)',
                (it['key'],it['title'],it['category'],it.get('severity'),it.get('description'),source_id))
    issue_ids[it['key']]=cur.lastrowid

vectors=json.loads(VECTORS.read_text(encoding='utf-8'))['vectors']
seen=set()
for v in vectors:
    for ch in v['input']:
        cp=ord(ch)
        if cp in seen: continue
        seen.add(cp)
        try: name=unicodedata.name(ch)
        except ValueError: name=None
        cur.execute('''INSERT OR IGNORE INTO unicode_codepoint
            (cp,name,age,general_category,canonical_combining_class,bidi_class,decomposition,east_asian_width,source_id)
            VALUES (?,?,?,?,?,?,?,?,?)''',(
            cp,name,prototype_age(cp),unicodedata.category(ch),unicodedata.combining(ch),unicodedata.bidirectional(ch),
            unicodedata.decomposition(ch) or None,unicodedata.east_asian_width(ch),source_id))

# Ensure variation selectors referenced later can exist even if not in current literal input set.
for cp in [0xE0100,0xE0101]:
    ch=chr(cp)
    try:name=unicodedata.name(ch)
    except ValueError:name=None
    cur.execute('INSERT OR IGNORE INTO unicode_codepoint(cp,name,general_category,source_id) VALUES (?,?,?,?)',
                (cp,name,unicodedata.category(ch),source_id))
    cur.execute('UPDATE unicode_codepoint SET age=? WHERE cp=?',(prototype_age(cp),cp))

# Derive all single-code-point encoding mappings from the runtime codec tables.
# Test-vector expectations validate these values; omission from a vector must never mean
# that a valid mapping is absent from the database.
position_cache={}
for cp in sorted(seen):
    add_derived_encodings_and_jis(cur, systems, position_cache, [cp], source_id, 'derived-single-codepoint')
    try:
        chr(cp).encode('cp932')
    except UnicodeEncodeError:
        pass
    else:
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(ids['cp932-repertoire'],cp))

# Preserve explicit multi-code-point sequence mappings (e.g. halfwidth kana + dakuten).
# These are sequence mappings and must not leak into a single-code-point detail view.
for v in vectors:
    cps=[int(x[2:],16) for x in v['expect']['codepoints']]
    if len(cps) <= 1:
        continue
    for enc in ('cp932','shift_jis','shift_jis_2004','euc_jp','euc_jis_2004','iso2022_jp','iso2022_jp_2004'):
        hx=v['expect'].get('encodings',{}).get(enc)
        if hx is None:
            continue
        key=hx.replace(' ','').upper()
        ck=(enc,key)
        if ck not in position_cache:
            cur.execute('INSERT INTO code_position(system_id,position_key,byte_value,numeric_value,source_id) VALUES (?,?,?,?,?)',
                        (systems[enc],key,bytes.fromhex(hx),int(key,16),source_id))
            position_cache[ck]=cur.lastrowid
        posid=position_cache[ck]
        cur.execute('INSERT INTO mapping(code_position_id,direction,mapping_kind,source_id,notes) VALUES (?,?,?,?,?)',
                    (posid,'both','prototype-sequence',source_id,v['id']))
        mid=cur.lastrowid
        for i,cp in enumerate(cps):
            cur.execute('INSERT INTO mapping_unicode(mapping_id,seq_index,cp) VALUES (?,?,?)',(mid,i,cp))

# Issues and memberships.
for v in vectors:
    cps=[int(x[2:],16) for x in v['expect']['codepoints']]
    for ikey in v['expect'].get('issues',[]):
        iid=issue_ids[ikey]
        for cp in cps:
            cur.execute('INSERT OR IGNORE INTO unicode_issue(cp,issue_id,notes) VALUES (?,?,?)',(cp,iid,v['id']))
            coll={'sjis-trailing-5c':'sjis-bad','wave-dash-mapping':'wave-dash','jis90-jis2004-glyph-change':'jis2004-glyph'}.get(ikey)
            if coll:
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(ids[coll],cp,v['id']))

# Known variant relations for the prototype; authoritative imports will later source these.
for a,b,t in [(0x9AD8,0x9AD9,'variant'),(0x5D0E,0xFA11,'variant'),(0x585A,0xFA10,'compatibility-variant')]:
    for x,y in [(a,b),(b,a)]:
        cur.execute('INSERT OR IGNORE INTO relation(from_cp,to_cp,relation_type,source_id) VALUES (?,?,?,?)',(x,y,t,source_id))

# Prototype IVS records for Tsuji. These will be replaced/verified by IVD importer.
cur.execute("INSERT INTO variation_collection(collection_key,title,version,source_id) VALUES ('adobe-japan1','Adobe-Japan1',NULL,?)",(source_id,))
vcid=cur.lastrowid
for base,vs,label in [(0x8FBB,0xE0100,'JIS90'),(0x8FBB,0xE0101,'JIS2004')]:
    cur.execute('INSERT INTO variation_sequence(base_cp,variation_cp,collection_id,source_id) VALUES (?,?,?,?)',(base,vs,vcid,source_id))
    vid=cur.lastrowid
    cur.execute('INSERT INTO variation_annotation(variation_id,key,value) VALUES (?,?,?)',(vid,'glyph-standard',label))

con.commit()
con.close()
print(DB)

#!/usr/bin/env python3
from pathlib import Path
import argparse, bisect, json, sqlite3, unicodedata, re, sys, time, zipfile

ROOT=Path(__file__).resolve().parents[1]
SCHEMA=ROOT/'db'/'schema.sql'; DB=ROOT/'db'/'charref.sqlite'
VECTORS=ROOT/'data'/'test-vectors'/'core.json'
ISSUES=ROOT/'data'/'custom'/'issues'/'issues.json'
ELEMENTARY=ROOT/'data'/'custom'/'education'/'elementary-kanji.json'
KANKEN=ROOT/'data'/'custom'/'education'/'kanken-kanji.json'
EMOJI_DIR=ROOT/'data'/'raw'/'emoji'
ARIB_FIXED=ROOT/'data'/'custom'/'arib'/'std-b24-fixed.json'
JIS_HISTORY=ROOT/'data'/'custom'/'jis'/'historical.json'

def parse_ranges(path, value_transform=lambda s:s):
    out=[]
    if not path.exists(): return out
    for line in path.read_text(encoding='utf-8').splitlines():
        line=line.split('#',1)[0].strip()
        if not line or ';' not in line: continue
        a,v=[x.strip() for x in line.split(';',1)]
        if '..' in a: x,y=[int(z,16) for z in a.split('..')]
        else: x=y=int(a,16)
        out.append((x,y,value_transform(v)))
    out.sort()
    return out

def lookup(ranges, cp, default=None):
    # binary search by range start
    i=bisect.bisect_right(ranges,(cp,10**9,chr(0x10ffff)))-1
    if i>=0:
        a,b,v=ranges[i]
        if a<=cp<=b:return v
    return default

def unicode_records(path):
    """Yield expanded assigned code points from UnicodeData.txt."""
    pending=None
    for line in path.read_text(encoding='utf-8').splitlines():
        f=line.split(';'); cp=int(f[0],16); name=f[1]
        rec={'cp':cp,'name':name,'gc':f[2],'ccc':int(f[3]),'bidi':f[4],'decomp':f[5] or None,
             'dec':f[6] or None,'digit':f[7] or None,'num':f[8] or None,'mirrored':1 if f[9]=='Y' else 0}
        if name.endswith(', First>'):
            pending=rec; continue
        if name.endswith(', Last>') and pending:
            base=pending.copy(); label=pending['name'][1:-8]
            for n in range(pending['cp'],cp+1):
                r=base.copy(); r['cp']=n
                if label.startswith('CJK Ideograph') or label.startswith('CJK Unified Ideograph'):
                    r['name']=f'CJK UNIFIED IDEOGRAPH-{n:X}'
                elif label.startswith('CJK Compatibility Ideograph'):
                    r['name']=f'CJK COMPATIBILITY IDEOGRAPH-{n:X}'
                elif label.startswith('Hangul Syllable'):
                    try:r['name']=unicodedata.name(chr(n))
                    except ValueError:r['name']=f'HANGUL SYLLABLE-{n:X}'
                else:r['name']=f'{label.upper()}-{n:X}'
                yield r
            pending=None; continue
        yield rec

def bytes_hex(b): return b.hex(' ').upper()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--ucd-dir',type=Path,required=True)
    ap.add_argument('--unicode-version',required=True)
    ap.add_argument('--dataset-kind',default='official')
    ap.add_argument('--cp932-file',type=Path)
    ap.add_argument('--unihan-zip',type=Path, help='Optional official Unihan.zip; kJIS0213 is imported as a cross-check property, not as normative JIS repertoire data.')
    args=ap.parse_args()
    u=args.ucd_dir
    # Release builds fail closed: do not allow a directory merely labelled 18.0.0
    # to contain the older bootstrap UCD. The standalone verifier also checks
    # release-specific cardinalities and spot vectors.
    if args.dataset_kind == 'official' and args.unicode_version == '18.0.0':
        subprocess_args=[sys.executable, str(ROOT/'scripts'/'verify_ucd18.py'), '--ucd-dir', str(u)]
        import subprocess
        subprocess.run(subprocess_args, check=True)
    required=['UnicodeData.txt','DerivedAge.txt','Scripts.txt','EastAsianWidth.txt']
    missing=[x for x in required if not (u/x).exists()]
    if missing: raise SystemExit('missing UCD files: '+', '.join(missing))
    if DB.exists(): DB.unlink()
    con=sqlite3.connect(DB); con.executescript(SCHEMA.read_text(encoding='utf-8')); cur=con.cursor()
    con.execute('PRAGMA journal_mode=OFF'); con.execute('PRAGMA synchronous=OFF'); con.execute('PRAGMA temp_store=MEMORY')
    cur.executemany('INSERT INTO meta(key,value) VALUES (?,?)',[
      ('schema_version','0.3'),('dataset_kind',args.dataset_kind),('unicode_target',args.unicode_version),('build_pipeline','ucd')])
    cur.execute('''INSERT INTO source(source_key,title,publisher,version,url,notes)
                   VALUES (?,?,?,?,?,?)''',('ucd',f'Unicode Character Database {args.unicode_version}','Unicode Consortium',args.unicode_version,
                   f'https://www.unicode.org/Public/{args.unicode_version}/ucd/',
                   'Authoritative UCD when built from fetched sources; bootstrap builds are explicitly marked in meta.'))
    ucd_src=cur.lastrowid
    unihan_src=None
    if args.unihan_zip and args.unihan_zip.is_file():
        cur.execute('''INSERT INTO source(source_key,title,publisher,version,url,notes)
                       VALUES (?,?,?,?,?,?)''',('unihan',f'Unihan Database {args.unicode_version}','Unicode Consortium',args.unicode_version,
                       f'https://www.unicode.org/Public/{args.unicode_version}/ucd/Unihan.zip',
                       'Supplementary CJK cross-check data. kJIS0213 is Provisional and is not treated as the normative JIS repertoire/code-position source.'))
        unihan_src=cur.lastrowid
    cur.execute('''INSERT INTO source(source_key,title,publisher,version,url,notes)
                   VALUES (?,?,?,?,?,?)''',('python-codecs','Python codec tables','Python runtime',sys.version.split()[0],None,
                   'Provisional encoding conversion source; CP932 can be replaced by vendor mapping import.'))
    codec_src=cur.lastrowid
    cur.execute('''INSERT INTO source(source_key,title,publisher,version,notes) VALUES (?,?,?,?,?)''',
                ('custom','CharRef curated issue/test data','CharRef','0.3','Curated regression annotations; not a standards source.'))
    custom_src=cur.lastrowid
    cur.execute('''INSERT INTO source(source_key,title,publisher,url,notes) VALUES (?,?,?,?,?)''',
                ('ms-eudc','Windows EUDC code ranges','Microsoft','https://learn.microsoft.com/windows/win32/intl/eudccoderange','CP932 EUDC range F040-F9FC; Unicode PUA is separate and mappings can be implementation-dependent.'))
    ms_eudc_src=cur.lastrowid
    cur.execute('''INSERT INTO source(source_key,title,publisher,url,notes) VALUES (?,?,?,?,?)''',
                ('unicode-width','Unicode Halfwidth/Fullwidth compatibility data','Unicode Consortium','https://www.unicode.org/reports/tr11/','Derived from Unicode compatibility decomposition and East_Asian_Width semantics.'))
    width_src=cur.lastrowid
    cur.execute('''INSERT INTO source(source_key,title,publisher,url,notes) VALUES (?,?,?,?,?)''',
                ('arib-fixed-test','ARIB fixed broadcast symbols (representative subset)','ARIB / Unicode Consortium','https://www.arib.or.jp/kikaku/kikaku_hoso/desc/std-b24.html','Representative fixed symbols only; DRCS intentionally excluded. Full authoritative ARIB repertoire import is pending.'))
    arib_src=cur.lastrowid
    cur.execute('''INSERT INTO source(source_key,title,publisher,url,notes) VALUES (?,?,?,?,?)''',
                ('x0213-crosswalk','JIS X 0213 / CP932 crosswalk references','Project X0213 / Unicode Consortium','https://x0213.org/wiki/wiki.cgi?page=CP932','Cross-check source for CP932 vendor extensions and Shift_JIS-2004 differences. Individual historical provenance should be verified against primary JIS material before being treated as authoritative.'))
    x0213_src=cur.lastrowid
    cur.execute('''INSERT INTO source(source_key,title,publisher,url,notes) VALUES (?,?,?,?,?)''',
                ('iana-windows31j','IANA Windows-31J charset registration','IANA','https://www.iana.org/assignments/character-sets/','Defines Windows-31J as Shift_JIS extended with NEC special characters (row 13), NEC selection of IBM extensions (rows 89-92), and IBM extensions (rows 115-119).'))
    iana_cp932_src=cur.lastrowid
    cur.execute('''INSERT INTO source(source_key,title,publisher,version,url,notes) VALUES (?,?,?,?,?,?)''',
                ('arib-b24-5.2','ARIB STD-B24 Data Coding and Transmission Specification for Digital Broadcasting','ARIB','5.2-E1','https://www.arib.or.jp/english/html/overview/doc/6-STD-B24v5_2-1p3-E1.pdf','Primary source used for ARIB fixed additional Kanji structure and repertoire checks; DRCS is out of scope.'))
    arib_primary_src=cur.lastrowid
    cur.execute('''INSERT INTO source(source_key,title,publisher,url,notes) VALUES (?,?,?,?,?)''',
                ('jis-history-adobe','Adobe-Japan1 historical JIS CMap crosswalk','Adobe','https://github.com/adobe-type-tools/Adobe-Japan1','Machine-readable historical code-position/glyph cross-check derived from Adobe-Japan1 CMaps. Not a replacement for the JIS standards themselves.'))
    jis_history_adobe_src=cur.lastrowid
    cur.execute('''INSERT INTO source(source_key,title,publisher,url,notes) VALUES (?,?,?,?,?)''',
                ('jis-history-reference','JIS X 0208 / X 0213 revision difference reference','CyberLibrarian','https://www.asahi-net.or.jp/~ax2s-kmtn/ref/jisrev.html','Secondary historical summary cross-checked against JIS revision descriptions. Glyph-change counts depend on definition; glyph changes are kept separate from repertoire/code-position changes.'))
    jis_history_ref_src=cur.lastrowid
    edu_data=json.loads(ELEMENTARY.read_text(encoding='utf-8')) if ELEMENTARY.exists() else None
    kanken_data=json.loads(KANKEN.read_text(encoding='utf-8')) if KANKEN.exists() else None
    jis_history=json.loads(JIS_HISTORY.read_text(encoding='utf-8')) if JIS_HISTORY.exists() else None
    arib_data=json.loads(ARIB_FIXED.read_text(encoding='utf-8')) if ARIB_FIXED.exists() else {'additional_kanji':[],'additional_symbols_partial':[]}
    if edu_data:
        es=edu_data['source']
        cur.execute('''INSERT INTO source(source_key,title,publisher,version,url,notes) VALUES (?,?,?,?,?,?)''',
                    (es['key'],es['title'],es.get('publisher'),es.get('version'),es.get('url'),es.get('notes')))
        education_src=cur.lastrowid
    else:
        education_src=custom_src
    # Current Joyo Kanji and Kanken grade lists. The Kanken official 2-10 list
    # is also used as an independent cross-check that the cumulative 2-kyu set
    # covers all 2,136 Joyo Kanji.
    cur.execute('''INSERT INTO source(source_key,title,publisher,version,url,notes) VALUES (?,?,?,?,?,?)''',
                ('joyo-2010','常用漢字表（平成22年内閣告示第2号）','文化庁 / 内閣','2010-11-30',
                 'https://www.bunka.go.jp/kokugo_nihongo/sisaku/joho/joho/kijun/naikaku/kanji/',
                 '2,136字。CharRefではU+20B9F 𠮟を正規Unicode代表として扱い、U+53F1 叱はJIS等での代替・異体関係として別コードポイントのまま保持する。'))
    joyo_src=cur.lastrowid
    if kanken_data:
        ks=kanken_data['source']
        cur.execute('''INSERT INTO source(source_key,title,publisher,version,url,notes) VALUES (?,?,?,?,?,?)''',
                    (ks['key'],ks['title'],ks.get('publisher'),ks.get('version'),ks.get('url'),ks.get('notes')))
        kanken_src=cur.lastrowid
    else:
        kanken_src=custom_src
    emoji_src=None
    if (EMOJI_DIR/'emoji-sequences.txt').exists() and (EMOJI_DIR/'emoji-zwj-sequences.txt').exists() and (EMOJI_DIR/'emoji-test.txt').exists():
        cur.execute('''INSERT INTO source(source_key,title,publisher,version,url,notes) VALUES (?,?,?,?,?,?)''',
                    ('unicode-emoji-18','Unicode Emoji / UTS #51 data','Unicode Consortium','18.0',
                     'https://www.unicode.org/Public/emoji/18.0/',
                     'emoji-sequences.txt, emoji-zwj-sequences.txt, emoji-test.txt. RGI ordering is taken from emoji-test.txt (CLDR order).'))
        emoji_src=cur.lastrowid

    ages=parse_ranges(u/'DerivedAge.txt'); scripts=parse_ranges(u/'Scripts.txt'); eaws=parse_ranges(u/'EastAsianWidth.txt')
    blocks=parse_ranges(u/'Blocks.txt') if (u/'Blocks.txt').exists() else []
    # block tables
    block_ids={}
    block_id_by_name={}
    for a,b,name in blocks:
        key=re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-')
        cur.execute('INSERT INTO unicode_block(block_key,name,first_cp,last_cp,source_id) VALUES (?,?,?,?,?)',(key,name,a,b,ucd_src)); block_ids[(a,b,name)]=cur.lastrowid; block_id_by_name[name]=cur.lastrowid
    script_names=sorted({v for _,_,v in scripts}); script_ids={}
    for s in script_names:
        cur.execute('INSERT INTO unicode_script(script_key,name,source_id) VALUES (?,?,?)',(s.lower().replace('_','-'),s,ucd_src)); script_ids[s]=cur.lastrowid

    # collections roots and standard Unicode navigation
    coll={}
    def add_coll(key,parent,title,typ,order,source=ucd_src,description=None):
        cur.execute('INSERT INTO collection(collection_key,parent_id,title,collection_type,description,source_id,sort_order) VALUES (?,?,?,?,?,?,?)',
                    (key,coll.get(parent),title,typ,description,source,order)); coll[key]=cur.lastrowid
    add_coll('unicode',None,'Unicode','root',10); add_coll('unicode-blocks','unicode','Blocks','unicode-group',10); add_coll('unicode-scripts','unicode','Scripts','unicode-group',20); add_coll('unicode-sequences','unicode','Sequences','unicode-group',30); add_coll('unicode-named-sequences','unicode-sequences','Named Sequences','unicode-sequence-standard',10,ucd_src,'UCD NamedSequences.txt に定義されたUnicode Named Character Sequencesを全件収録。'); add_coll('unicode-revisions','unicode','Unicode改定差分','unicode-history',40,ucd_src,'表示対象版の直前に表示している版から、新たに割り当てられたコードポイントを一覧化。12.1は12.0+12.1、15.1は15.0+15.1を含む。')
    if emoji_src:
        add_coll('emoji18','unicode-sequences','Emoji 18.0','unicode-emoji',20,emoji_src,'UTS #51 Emoji 18.0の公式machine-readable data。')
        add_coll('emoji18-rgi','emoji18','RGI Emoji（CLDR順）','unicode-emoji-rgi',5,emoji_src,'emoji-test.txtのcomponent + fully-qualified。キーボード/表示向けの推奨順序。')
        add_coll('emoji18-basic','emoji18','Basic Emoji','unicode-emoji-sequence',10,emoji_src)
        add_coll('emoji18-keycap','emoji18','Keycap Sequences','unicode-emoji-sequence',20,emoji_src)
        add_coll('emoji18-flag','emoji18','Flag Sequences','unicode-emoji-sequence',30,emoji_src)
        add_coll('emoji18-tag','emoji18','Tag Sequences','unicode-emoji-sequence',40,emoji_src)
        add_coll('emoji18-modifier','emoji18','Modifier Sequences','unicode-emoji-sequence',50,emoji_src)
        add_coll('emoji18-zwj','emoji18','ZWJ Sequences','unicode-emoji-sequence',60,emoji_src)
    add_coll('jis',None,'JIS','root',20); add_coll('pc-net',None,'PC / ネット','root',30); add_coll('society',None,'社会','root',40); add_coll('compatibility',None,'互換・幅','root',45); add_coll('broadcast',None,'放送','root',47); add_coll('issues',None,'文字コード問題','root',50); add_coll('debug',None,'デバッグ','root',90,custom_src,'開発・回帰試験用。規格上の文字集合ではありません。'); add_coll('debug-structural','debug','構造試験','test-mixed',10,custom_src,'スキーマ/UIの境界条件を検証する代表fixtureを1リストに集約。正式な規格集合ではありません。')
    # JIS repertoire navigation. Encoding forms (Shift_JIS/EUC/ISO-2022) remain under Encoding details.
    add_coll('jis-x0201','jis','JIS X 0201','jis-standard',10,x0213_src,'1バイトのラテン文字集合・片仮名文字集合。')
    add_coll('jis-x0201-roman','jis-x0201','ラテン文字集合','jis-repertoire',10,x0213_src)
    add_coll('jis-x0201-kana','jis-x0201','片仮名文字集合','jis-repertoire',20,x0213_src)
    add_coll('jis-x0208','jis','JIS X 0208','jis-standard',50,x0213_src,'JIS X 0213の基礎となる2バイト文字集合。')
    add_coll('jis-x0208-all','jis-x0208','全体','jis-repertoire',5,x0213_src)
    add_coll('jis-x0208-nonkanji','jis-x0208','非漢字','jis-repertoire',10,x0213_src)
    add_coll('jis-x0208-level1','jis-x0208','第1水準漢字','jis-level',20,x0213_src,'16区〜47区。')
    add_coll('jis-x0208-level2','jis-x0208','第2水準漢字','jis-level',30,x0213_src,'48区〜84区。')
    add_coll('jis-x0212','jis','JIS X 0212:1990','jis-standard',60,x0213_src,'補助漢字集合。Shift_JISでは通常直接扱わず、EUC-JP/ISO-2022系で利用される。')
    add_coll('jis-x0212-all','jis-x0212','全体','jis-repertoire',5,x0213_src)
    add_coll('jis-x0212-kanji','jis-x0212','補助漢字','jis-repertoire',10,x0213_src)
    add_coll('jis-x0212-nonkanji','jis-x0212','非漢字','jis-repertoire',20,x0213_src)
    add_coll('jis-x0213-2000','jis','JIS X 0213:2000','jis-standard',70,x0213_src,'初版。2004版との差は主に第3水準への10文字追加と例示字形改正。')
    add_coll('jis-x0213-2000-all','jis-x0213-2000','全体','jis-repertoire',5,x0213_src)
    add_coll('jis-x0213-2000-plane1','jis-x0213-2000','Plane 1','jis-plane',10,x0213_src)
    add_coll('jis-x0213-2000-level1','jis-x0213-2000-plane1','第1水準漢字','jis-level',10,x0213_src)
    add_coll('jis-x0213-2000-level2','jis-x0213-2000-plane1','第2水準漢字','jis-level',20,x0213_src)
    add_coll('jis-x0213-2000-level3','jis-x0213-2000-plane1','第3水準漢字','jis-level',30,x0213_src)
    add_coll('jis-x0213-2000-plane2','jis-x0213-2000','Plane 2','jis-plane',20,x0213_src)
    add_coll('jis-x0213-2000-level4','jis-x0213-2000-plane2','第4水準漢字','jis-level',10,x0213_src)
    add_coll('jis-x0213-2004','jis','JIS X 0213:2004','jis-standard',80,x0213_src,'2004年改正版。Plane 1にUCS互換の10文字を追加し、168漢字の例示字形を変更。')
    add_coll('jis-x0213-2004-all','jis-x0213-2004','全体','jis-repertoire',5,x0213_src)
    add_coll('jis-x0213-2004-plane1','jis-x0213-2004','Plane 1','jis-plane',10,x0213_src)
    add_coll('jis-x0213-2004-level1','jis-x0213-2004-plane1','第1水準漢字','jis-level',10,x0213_src)
    add_coll('jis-x0213-2004-level2','jis-x0213-2004-plane1','第2水準漢字','jis-level',20,x0213_src)
    add_coll('jis-x0213-2004-level3','jis-x0213-2004-plane1','第3水準漢字','jis-level',30,x0213_src)
    add_coll('jis-x0213-2004-plane2','jis-x0213-2004','Plane 2','jis-plane',20,x0213_src)
    add_coll('jis-x0213-2004-level4','jis-x0213-2004-plane2','第4水準漢字','jis-level',10,x0213_src)
    add_coll('jis-revisions','jis','JIS改定差','jis-history',90,jis_history_ref_src,'収録文字差・符号位置差・例示字形差を分離して表示。例示字形は文字コード値そのものの変更とは限らない。')
    add_coll('jis-c6226-1978','jis','JIS C 6226:1978（78JIS）','jis-historical-edition',20,jis_history_adobe_src,'6,802位置。第1水準2965字、第2水準3384字、非漢字453字。Adobe-Japan1 CMap由来の機械可読crosswalkで収録。')
    add_coll('jis-c6226-1978-nonkanji','jis-c6226-1978','非漢字（453）','jis-repertoire',10,jis_history_adobe_src)
    add_coll('jis-c6226-1978-level1','jis-c6226-1978','第1水準漢字（2965）','jis-level',20,jis_history_adobe_src)
    add_coll('jis-c6226-1978-level2','jis-c6226-1978','第2水準漢字（3384）','jis-level',30,jis_history_adobe_src)
    add_coll('jis-c6226-1983','jis','JIS C 6226:1983（83JIS）','jis-historical-edition',30,jis_history_adobe_src,'6,877位置。78JISから非漢字71字と旧字形4字の別符号を追加し、22組の符号位置入替を実施。')
    add_coll('jis-c6226-1983-nonkanji','jis-c6226-1983','非漢字（524）','jis-repertoire',10,jis_history_adobe_src)
    add_coll('jis-c6226-1983-level1','jis-c6226-1983','第1水準漢字（2965）','jis-level',20,jis_history_adobe_src)
    add_coll('jis-c6226-1983-level2','jis-c6226-1983','第2水準漢字（3388）','jis-level',30,jis_history_adobe_src)
    add_coll('jis-x0208-1990','jis','JIS X 0208:1990（90JIS）','jis-historical-edition',40,jis_history_adobe_src,'6,879位置。83JISに凜・熙の2字を追加。')
    add_coll('jis-x0208-1990-nonkanji','jis-x0208-1990','非漢字（524）','jis-repertoire',10,jis_history_adobe_src)
    add_coll('jis-x0208-1990-level1','jis-x0208-1990','第1水準漢字（2965）','jis-level',20,jis_history_adobe_src)
    add_coll('jis-x0208-1990-level2','jis-x0208-1990','第2水準漢字（3390）','jis-level',30,jis_history_adobe_src)
    add_coll('jis-rev-78-83','jis-revisions','78JIS → 83JIS','jis-revision-group',10,jis_history_ref_src)
    add_coll('jis-rev-78-83-added71','jis-rev-78-83','追加71文字','jis-revision-repertoire',10,jis_history_adobe_src,'83JISで新規に追加された71位置（旧字形4位置は別Collection）。')
    add_coll('jis-rev-78-83-old4','jis-rev-78-83','旧字形の別符号追加4文字','jis-revision-repertoire',20,jis_history_adobe_src,'堯・槇・遙・瑤を84区1〜4点へ別符号として追加。')
    add_coll('jis-rev-78-83-swaps22','jis-rev-78-83','符号位置入替 22組（44位置）','jis-revision-position',30,jis_history_adobe_src,'78JISと83JISで22組の漢字の符号位置が相互に入れ替わった。')
    add_coll('jis-rev-78-83-glyph254','jis-rev-78-83','例示字形・字体変更 254字（全件membership整備中）','jis-revision-glyph',40,jis_history_ref_src,'公称254字。字形レベル差はUnicodeコードポイントだけでは完全に表現できないため、全件の位置membershipはJIS97附属書等との照合を継続。')
    add_coll('jis-rev-78-83-nonunified29','jis-rev-78-83-glyph254','うちJIS97で非包摂とされた29字','jis-revision-glyph',10,jis_history_ref_src,'83JISの字形変更のうち、JIS97で包摂されない別字体として扱われた29字。')
    add_coll('jis-rev-83-90','jis-revisions','83JIS → 90JIS','jis-revision-group',20,jis_history_ref_src)
    add_coll('jis-rev-83-90-added2','jis-rev-83-90','追加2文字（凜・熙）','jis-revision-repertoire',10,jis_history_adobe_src)
    add_coll('jis-rev-83-90-glyph225','jis-rev-83-90','例示字形変更 225字','jis-revision-glyph',20,jis_history_ref_src,'JIS90で例示字形が変更された225字。')
    add_coll('jis-rev-90-97','jis-revisions','90JIS → 97JIS','jis-revision-group',30,jis_history_ref_src,'文字集合・符号位置・例示字形の変更なし。規定・包摂規準・履歴説明等を大幅に整理。')
    add_coll('jis-rev-2000-2004','jis-revisions','JIS2000 → JIS2004','jis-revision-group',40,x0213_src)
    add_coll('jis-x0213-2004-added10','jis-rev-2000-2004','追加10文字','jis-revision-repertoire',10,x0213_src,'2004年改正でPlane 1の第3水準に追加されたUCS互換10文字。')
    add_coll('jis-rev-2000-2004-glyph168','jis-rev-2000-2004','例示字形変更 168字','jis-revision-glyph',20,jis_history_ref_src,'JIS X 0213:2004で例示字形が変更された168字。コードポイントmapping自体は変更されない。')
    add_coll('jis-rev-2012','jis-revisions','2012追補（文字集合差なし）','jis-revision-group',50,jis_history_ref_src,'JIS X 0208:2012 / JIS X 0213:2012は常用漢字表改定に伴う参考情報・字形実現の明確化が中心で、文字集合追加はない。')
    add_coll('education','society','学校教育','social-group',10,education_src)
    add_coll('education-joyo','education','常用漢字（2,136字）','education-standard',5,joyo_src,'平成22年内閣告示第2号の常用漢字。')
    add_coll('education-elementary','education','小学校 学年別漢字配当表（平成29年告示）','education-standard',10,education_src,'文部科学省の学年別漢字配当表。2020年度全面実施。')
    for grade,count in [(1,80),(2,160),(3,200),(4,202),(5,193),(6,191)]:
        add_coll(f'education-elementary-g{grade}','education-elementary',f'小学{grade}年で習う漢字（{count}字）','education-grade',grade*10,education_src)
    add_coll('education-junior-high','education','中学校で新たに学ぶ常用漢字（1,110字）','education-standard',20,joyo_src,'常用漢字2,136字から小学校学年別漢字配当表1,026字を除いた集合。中学校では学年別の固定配当ではない。')
    if kanken_data:
        add_coll('kanken','society','日本漢字能力検定（2〜10級）','qualification-group',20,kanken_src,'公式「級別漢字表」で公開されている2〜10級のみ収録。各Collectionは当該級の累積出題範囲。')
        for key,title,count,order in [('10','10級',80,10),('9','9級',240,20),('8','8級',440,30),('7','7級',642,40),('6','6級',835,50),('5','5級',1026,60),('4','4級',1339,70),('3','3級',1623,80),('pre2','準2級',1951,90),('2','2級',2136,100)]:
            add_coll(f'kanken-{key}','kanken',f'{title}（{count:,}字）','qualification-repertoire',order,kanken_src)
    add_coll('width-compat','compatibility','半角・全角互換','unicode-compatibility',10,width_src)
    add_coll('width-full','width-compat','Fullwidth variants','unicode-compatibility',10,width_src)
    add_coll('width-half','width-compat','Halfwidth variants','unicode-compatibility',20,width_src)
    add_coll('cp932-extensions','pc-net','CP932独自候補（JIS X 0201/0208外）','encoding-derived',20,codec_src,'CP932で表現でき、JIS X 0201/0208位置を持たない差集合。JIS X 0213等との関係は別表示。')
    add_coll('cp932-vendor','pc-net','CP932ベンダー拡張','encoding-group',21,iana_cp932_src,'Windows-31JでShift_JIS/JIS X 0208に追加されたベンダー拡張。')
    add_coll('cp932-nec-special','cp932-vendor','NEC特殊文字（13区）','encoding-vendor-extension',10,iana_cp932_src,'CP932 0x8740-0x879C付近。IANA Windows-31J登録のNEC special characters (Row 13)。')
    add_coll('cp932-nec-selected-ibm','cp932-vendor','NEC選定IBM拡張（89〜92区）','encoding-vendor-extension',20,iana_cp932_src,'CP932 0xED40-0xEEFC。IBM拡張文字をJIS X 0208空き領域へ重複収録した領域。')
    add_coll('cp932-ibm-extension','cp932-vendor','IBM拡張（115〜119区）','encoding-vendor-extension',30,iana_cp932_src,'CP932 0xFA40-0xFC4B。Windows-31JのIBM extensions。')
    add_coll('cp932-jis0213-reassigned','pc-net','CP932拡張 / JIS X 0213 共通文字（符号位置差）','encoding-crosswalk',25,x0213_src,'CP932拡張にもJIS X 0213にも存在し、CP932とShift_JIS-2004で符号位置が異なる文字。歴史的経緯の個別断定ではなく、機械的crosswalk集合。')
    add_coll('cp932-eudc','pc-net','CP932ユーザー定義領域 (EUDC)','encoding-private-use',30,ms_eudc_src,'Windows CP932のEUDC範囲 F040-F9FC。Unicode PUAとの対応を表示。')
    add_coll('unicode-pua-cp932','unicode','Unicode PUA（CP932 EUDC対応範囲）','unicode-private-use',40,ucd_src,'U+E000-U+E757。CP932 EUDCと対応する範囲。')
    add_coll('arib','broadcast','ARIB STD-B24 / 運用','broadcast-standard',10,arib_src,'DRCSは対象外。規格上の符号化能力と、運用上の共通実装コアを分離して表示。')
    add_coll('arib-operational-core','arib','共通実装コア（暫定）','broadcast-operational-core',5,arib_primary_src,'JIS X 0208相当の基本漢字集合と固定ARIB追加文字をまとめた暫定コア。第3・第4水準は含めない。TR-B14/TR-B15の実装レベル規定との全件照合を継続するため「必須」とは断定しない。')
    add_coll('arib-capability','arib','STD-B24で符号化可能','broadcast-capability',10,arib_src,'ARIB STD-B24の8単位符号で表現できる規格上の集合。受信機での実装必須性とは別。')
    add_coll('arib-jis-compatible','arib-capability','JIS互換漢字','broadcast-repertoire',10,arib_src,'ARIB STD-B24のJIS互換漢字。JIS X 0213:2004 Plane 1/2を規格上扱える。')
    add_coll('arib-jis-plane1','arib-jis-compatible','JIS互換漢字 Plane 1','broadcast-repertoire',10,arib_src,'JIS X 0213:2004 Plane 1由来。規格上は符号化可能だが、第3水準部分の受信機実装は運用規定上製品企画事項。')
    add_coll('arib-jis-plane2','arib-jis-compatible','JIS互換漢字 Plane 2','broadcast-repertoire',20,arib_src,'JIS X 0213:2004 Plane 2由来。第4水準相当。受信機実装は運用規定上製品企画事項。')
    add_coll('arib-optional-jis34','arib','第3・第4水準（任意実装）','broadcast-optional',20,arib_primary_src,'TR-B15ではJIS第3・第4水準を受信機に実装するかは製品企画事項とされる。')
    add_coll('arib-optional-jis3','arib-optional-jis34','第3水準（Plane 1のJIS X 0208外）','broadcast-optional',10,arib_primary_src,'JIS X 0213 Plane 1のうちJIS X 0208に含まれない文字を第3水準相当として導出。')
    add_coll('arib-optional-jis4','arib-optional-jis34','第4水準（Plane 2）','broadcast-optional',20,arib_primary_src,'JIS X 0213 Plane 2を第4水準相当として導出。')
    add_coll('arib-additional','arib-capability','ARIB追加文字（DRCS除外）','broadcast-group',30,arib_primary_src,'ARIB STD-B24の固定追加漢字・追加記号。DRCSは対象外。')
    add_coll('arib-additional-kanji','arib-additional','ARIB追加漢字','broadcast-repertoire',10,arib_primary_src,'ARIB STD-B24 Table 7-11等の固定追加漢字。')
    add_coll('arib-fixed','arib-additional','ARIB追加記号（現在は部分収録）','broadcast-repertoire',20,arib_src,'DRCSは対象外。Unicode対応を確認済みの固定追加記号を収録。全表照合は継続中。')
    block_coll={}; block_coll_by_name={}; script_coll={}
    for i,(a,b,name) in enumerate(blocks):
        k='unicode-block-'+re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-'); add_coll(k,'unicode-blocks',name,'unicode-block',i); block_coll[(a,b,name)]=coll[k]; block_coll_by_name[name]=coll[k]
    for i,s in enumerate(script_names):
        k='unicode-script-'+s.lower().replace('_','-'); add_coll(k,'unicode-scripts',s,'unicode-script',i); script_coll[s]=coll[k]
    unicode_revision_specs=[
        ('7.0',2014,['7.0']),('8.0',2015,['8.0']),('9.0',2016,['9.0']),('10.0',2017,['10.0']),
        ('11.0',2018,['11.0']),('12.1',2019,['12.0','12.1']),('13.0',2020,['13.0']),('14.0',2021,['14.0']),
        ('15.1',2023,['15.0','15.1']),('16.0',2024,['16.0']),('17.0',2025,['17.0']),('18.0',2026,['18.0'])]
    for i,(ver,year,ages_for_diff) in enumerate(unicode_revision_specs,1):
        hidden=', '.join(ages_for_diff)
        desc=f'前の表示対象版からUnicode {ver}までに新規割り当てされたコードポイント。Age={hidden} を含む。'
        if ver in ('17.0','18.0') and args.dataset_kind.startswith('bootstrap') and args.unicode_version=='16.0.0':
            desc += ' 現在のbootstrap UCD 16.0ではmembership未収録。公式UCD 18.0ビルド時に自動生成される。'
        add_coll(f'unicode-revision-{ver.replace(".","-")}', 'unicode-revisions', f'Unicode {ver} ({year})', 'unicode-revision', i*10, ucd_src, desc)

    add_coll('cp932-repertoire','pc-net','CP932','encoding-repertoire',10,codec_src)
    add_coll('sjis-bad','issues','SJISダメ文字','issue',10,custom_src,'2バイト目がエスケープ等で問題になり得る文字。まず0x5Cを全件生成。')
    add_coll('sjis-bad-5c','sjis-bad','Shift_JIS 第2バイト 0x5C','issue-derived',10,codec_src)
    add_coll('cp932-bad-5c','sjis-bad','CP932 第2バイト 0x5C','issue-derived',20,codec_src)
    add_coll('wave-dash','issues','波ダッシュ問題','issue',20,custom_src)
    add_coll('jis2004-glyph','issues','JIS90/JIS2004字形差','issue',30,custom_src)

    # code systems
    systems={}
    for key,title,typ in [
      ('cp932','Windows-31J / CP932','encoding'),('shift_jis','Shift_JIS (JIS X 0208)','encoding'),('shift_jis_2004','Shift_JIS-2004 (JIS X 0213:2004)','encoding'),
      ('euc_jp','EUC-JP','encoding'),('euc_jis_2004','EUC-JIS-2004 (JIS X 0213:2004)','encoding'),('iso2022_jp','ISO-2022-JP','encoding'),('iso2022_jp_2004','ISO-2022-JP-2004','encoding'),
      ('jis_x_0201_roman','JIS X 0201 Roman','standard-position'),('jis_x_0201_kana','JIS X 0201 Katakana','standard-position'),('jis_x_0208','JIS X 0208','standard-position'),('jis_x_0212','JIS X 0212:1990','standard-position'),('jis_x_0213_2000','JIS X 0213:2000','standard-position'),('jis_x_0213_2004','JIS X 0213:2004','standard-position'),
      ('jis_c_6226_1978','JIS C 6226:1978 (78JIS)','standard-position'),('jis_c_6226_1983','JIS C 6226:1983 (83JIS)','standard-position'),('jis_x_0208_1990','JIS X 0208:1990 (90JIS)','standard-position')]:
        cur.execute('INSERT INTO code_system(system_key,title,system_type,source_id) VALUES (?,?,?,?)',(key,title,typ,codec_src)); systems[key]=cur.lastrowid

    # Unicode rows
    t=time.time(); assigned=[]
    for n,r in enumerate(unicode_records(u/'UnicodeData.txt'),1):
        cp=r['cp']; age=lookup(ages,cp)
        # bootstrap UCD16 inference: if a code point is assigned in UCD16 but absent from Unicode15 age data.
        if age is None and args.dataset_kind.startswith('bootstrap') and args.unicode_version=='16.0.0': age='16.0'
        script=lookup(scripts,cp); eaw=lookup(eaws,cp); block=lookup(blocks,cp)
        bid=block_id_by_name.get(block) if block else None
        sid=script_ids.get(script)
        numtype='decimal' if r['dec'] else ('digit' if r['digit'] else ('numeric' if r['num'] else None))
        numval=r['dec'] or r['digit'] or r['num']
        cur.execute('''INSERT INTO unicode_codepoint(cp,name,age,general_category,canonical_combining_class,bidi_class,decomposition,numeric_type,numeric_value,mirrored,east_asian_width,block_id,primary_script_id,source_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(cp,r['name'],age,r['gc'],r['ccc'],r['bidi'],r['decomp'],numtype,numval,r['mirrored'],eaw,bid,sid,ucd_src))
        assigned.append(cp)
        if block and block in block_coll_by_name:
            cur.execute('INSERT INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(block_coll_by_name[block],cp))
        if sid: cur.execute('INSERT INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(script_coll[script],cp))
    print('unicode rows',len(assigned),'seconds',round(time.time()-t,2))
    assigned_set=set(assigned)

    # Complete UCD Named Character Sequences. These are normative contributory
    # UCD data and belong in the normal Unicode navigation, unlike structural fixtures.
    named_sequences_count=0
    named_path=u/'NamedSequences.txt'
    if named_path.exists():
        for order,raw in enumerate(named_path.read_text(encoding='utf-8').splitlines(),1):
            line=raw.split('#',1)[0].strip()
            if not line or ';' not in line:
                continue
            name,cptext=[x.strip() for x in line.split(';',1)]
            cps=tuple(int(x,16) for x in cptext.split())
            missing=[cp for cp in cps if cp not in assigned_set]
            if missing:
                raise RuntimeError(f'NamedSequences references missing code point(s): {name}: {missing}')
            skey='ucd-named-'+re.sub(r'[^a-z0-9]+','-',name.lower()).strip('-')
            cur.execute('INSERT INTO unicode_sequence(sequence_key,sequence_type,name,source_id,notes) VALUES (?,?,?,?,?)',
                        (skey,'named-character-sequence',name,ucd_src,'UCD NamedSequences.txt'))
            sid=cur.lastrowid
            for i,cp in enumerate(cps):
                cur.execute('INSERT INTO unicode_sequence_member(sequence_id,seq_index,cp) VALUES (?,?,?)',(sid,i,cp))
            cur.execute('INSERT INTO collection_member_sequence(collection_id,sequence_id,sort_order,notes) VALUES (?,?,?,?)',
                        (coll['unicode-named-sequences'],sid,named_sequences_count+1,'UCD NamedSequences.txt'))
            named_sequences_count += 1
        print('UCD Named Sequences',named_sequences_count)

    # Unicode Emoji 18.0. Store each distinct code point sequence once, then
    # attach it to one or more semantic collections. Single-code-point Basic
    # Emoji entries are kept as Unicode members; multi-code-point entries are
    # first-class unicode_sequence entities.
    if emoji_src:
        emoji_seq_by_cps={}
        emoji_type_counts={}
        def ensure_emoji_sequence(cps, stype, name, notes=None, annotations=None):
            key=tuple(cps)
            if key in emoji_seq_by_cps:
                sid=emoji_seq_by_cps[key]
            else:
                skey='emoji-'+ '-'.join(f'{cp:X}' for cp in cps)
                cur.execute('INSERT INTO unicode_sequence(sequence_key,sequence_type,name,source_id,notes) VALUES (?,?,?,?,?)',
                            (skey,stype,name,emoji_src,notes or 'Unicode Emoji 18.0'))
                sid=cur.lastrowid; emoji_seq_by_cps[key]=sid
                for i,cp in enumerate(cps):
                    if cp not in assigned_set:
                        raise RuntimeError(f'Emoji sequence references missing UCD code point U+{cp:04X}')
                    cur.execute('INSERT INTO unicode_sequence_member(sequence_id,seq_index,cp) VALUES (?,?,?)',(sid,i,cp))
            for k,v in (annotations or {}).items():
                cur.execute('INSERT OR REPLACE INTO unicode_sequence_annotation(sequence_id,key,value) VALUES (?,?,?)',(sid,k,str(v)))
            return sid
        type_to_coll={
          'Basic_Emoji':'emoji18-basic','Emoji_Keycap_Sequence':'emoji18-keycap',
          'RGI_Emoji_Flag_Sequence':'emoji18-flag','RGI_Emoji_Tag_Sequence':'emoji18-tag',
          'RGI_Emoji_Modifier_Sequence':'emoji18-modifier','RGI_Emoji_ZWJ_Sequence':'emoji18-zwj'}
        order_by_coll={k:0 for k in type_to_coll.values()}
        def add_emoji_member(collkey,cps,stype,name,emoji_version=None):
            order_by_coll[collkey]=order_by_coll.get(collkey,0)+1
            order=order_by_coll[collkey]
            if len(cps)==1:
                cp=cps[0]
                if cp not in assigned_set: raise RuntimeError(f'Emoji member missing UCD code point U+{cp:04X}')
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',
                            (coll[collkey],cp,order,stype))
            else:
                sid=ensure_emoji_sequence(cps,stype,name,annotations={'emoji-version':emoji_version} if emoji_version else None)
                cur.execute('INSERT OR IGNORE INTO collection_member_sequence(collection_id,sequence_id,sort_order,notes) VALUES (?,?,?,?)',
                            (coll[collkey],sid,order,stype))
        # emoji-sequences.txt; expand scalar ranges such as 231A..231B.
        for raw in (EMOJI_DIR/'emoji-sequences.txt').read_text(encoding='utf-8').splitlines():
            if not raw.strip() or raw.lstrip().startswith('#'): continue
            body,_,comment=raw.partition('#'); body=body.strip()
            if not body or ';' not in body: continue
            lhs,stype,name=[x.strip() for x in body.split(';',2)]
            m=re.search(r'\b(E\d+(?:\.\d+)?)\b',comment)
            ever=m.group(1) if m else None
            items=[]
            if '..' in lhs and ' ' not in lhs:
                a,b=[int(x,16) for x in lhs.split('..')]; items=[(cp,) for cp in range(a,b+1)]
            else: items=[tuple(int(x,16) for x in lhs.split())]
            ckey=type_to_coll[stype]
            for cps in items:
                add_emoji_member(ckey,cps,stype,name,ever)
                emoji_type_counts[stype]=emoji_type_counts.get(stype,0)+1
        for raw in (EMOJI_DIR/'emoji-zwj-sequences.txt').read_text(encoding='utf-8').splitlines():
            if not raw.strip() or raw.lstrip().startswith('#'): continue
            body,_,comment=raw.partition('#'); body=body.strip()
            if not body or ';' not in body: continue
            lhs,stype,name=[x.strip() for x in body.split(';',2)]
            cps=tuple(int(x,16) for x in lhs.split()); m=re.search(r'\b(E\d+(?:\.\d+)?)\b',comment)
            add_emoji_member('emoji18-zwj',cps,stype,name,m.group(1) if m else None)
            emoji_type_counts[stype]=emoji_type_counts.get(stype,0)+1
        # RGI collection follows emoji-test.txt CLDR order. component + fully-qualified
        # is exactly the RGI set described by UTS #51 data comments.
        rgi_order=0
        for raw in (EMOJI_DIR/'emoji-test.txt').read_text(encoding='utf-8').splitlines():
            line=raw.strip()
            if not line: continue
            if line.startswith('# group:'): current_group=line.split(':',1)[1].strip(); continue
            if line.startswith('# subgroup:'): current_subgroup=line.split(':',1)[1].strip(); continue
            if line.startswith('#'): continue
            body,_,comment=raw.partition('#')
            if ';' not in body: continue
            lhs,status=[x.strip() for x in body.split(';',1)]
            if status not in ('component','fully-qualified'): continue
            cps=tuple(int(x,16) for x in lhs.split()); rgi_order+=1
            # name and Emoji version are present in the comment after the glyph.
            m=re.search(r'\b(E\d+(?:\.\d+)?)\b\s+(.+)$',comment.strip())
            ever=m.group(1) if m else None; name=m.group(2) if m else 'RGI Emoji'
            if len(cps)==1:
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',
                            (coll['emoji18-rgi'],cps[0],rgi_order,status))
            else:
                sid=ensure_emoji_sequence(cps,'RGI_Emoji',name,annotations={'qualification':status,'group':locals().get('current_group',''),'subgroup':locals().get('current_subgroup',''),'emoji-version':ever or ''})
                cur.execute('INSERT OR IGNORE INTO collection_member_sequence(collection_id,sequence_id,sort_order,notes) VALUES (?,?,?,?)',
                            (coll['emoji18-rgi'],sid,rgi_order,status))
        expected={'Basic_Emoji':1409,'Emoji_Keycap_Sequence':12,'RGI_Emoji_Flag_Sequence':259,'RGI_Emoji_Tag_Sequence':3,'RGI_Emoji_Modifier_Sequence':675,'RGI_Emoji_ZWJ_Sequence':1614}
        if emoji_type_counts != expected: raise RuntimeError(f'Emoji 18.0 type counts mismatch: {emoji_type_counts}')
        if rgi_order != 3972: raise RuntimeError(f'Emoji 18.0 RGI count mismatch: {rgi_order}')
        print('Emoji 18.0',emoji_type_counts,'RGI',rgi_order)

    # Unihan is supplementary cross-check data. kJIS0213 is explicitly Provisional
    # in UAX #38, so keep it as a Unicode property rather than using it to define
    # the JIS X 0213 repertoire or code positions.
    unihan_kjis0213_count=0
    if unihan_src and args.unihan_zip and args.unihan_zip.is_file():
        with zipfile.ZipFile(args.unihan_zip) as zf:
            try:
                text=zf.read('Unihan_OtherMappings.txt').decode('utf-8')
            except KeyError:
                raise RuntimeError('Unihan.zip missing Unihan_OtherMappings.txt')
        for raw in text.splitlines():
            if not raw or raw.startswith('#'):
                continue
            parts=raw.split('\t')
            if len(parts) < 3 or parts[1] != 'kJIS0213':
                continue
            cp=int(parts[0][2:],16)
            if cp not in assigned_set:
                raise RuntimeError(f'Unihan kJIS0213 references missing UCD code point U+{cp:04X}')
            cur.execute('INSERT OR IGNORE INTO unicode_property(cp,property,value,source_id) VALUES (?,?,?,?)',
                        (cp,'Unihan_kJIS0213',parts[2],unihan_src))
            unihan_kjis0213_count += cur.rowcount
        print('Unihan kJIS0213 cross-check rows',unihan_kjis0213_count)

    # Unicode revision-difference collections are generated from the UCD Age property.
    # Display versions intentionally skip minor versions 12.0 and 15.0; their additions roll into 12.1 / 15.1.
    revision_age_to_key={
        '7.0':'unicode-revision-7-0','8.0':'unicode-revision-8-0','9.0':'unicode-revision-9-0','10.0':'unicode-revision-10-0',
        '11.0':'unicode-revision-11-0','12.0':'unicode-revision-12-1','12.1':'unicode-revision-12-1','13.0':'unicode-revision-13-0',
        '14.0':'unicode-revision-14-0','15.0':'unicode-revision-15-1','15.1':'unicode-revision-15-1','16.0':'unicode-revision-16-0',
        '17.0':'unicode-revision-17-0','18.0':'unicode-revision-18-0'}
    for cp,age in cur.execute('SELECT cp,age FROM unicode_codepoint WHERE age IS NOT NULL').fetchall():
        ck=revision_age_to_key.get(age)
        if ck:
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',
                        (coll[ck],cp,f'Unicode Age {age}'))


    # Generic Unicode binary properties.  These files use the same range ; property
    # syntax, so new property names do not require schema changes.
    property_files=[u/'PropList.txt',u/'DerivedCoreProperties.txt',u/'emoji'/'emoji-data.txt']
    property_count=0
    for prop_file in property_files:
        if not prop_file.exists():
            continue
        for a,b,prop in parse_ranges(prop_file):
            for cp in range(a,b+1):
                if cp in assigned_set:
                    cur.execute('INSERT OR IGNORE INTO unicode_property(cp,property,value,source_id) VALUES (?,?,?,?)',(cp,prop,'Y',ucd_src))
                    property_count += cur.rowcount
    print('unicode property rows',property_count)

    # Elementary school grade collections (MEXT 2017 curriculum guideline).
    # Membership data is stored once; counts and cross-grade uniqueness are build invariants.
    if edu_data:
        expected={1:80,2:160,3:200,4:202,5:193,6:191}
        seen=set()
        for grade_s, chars in edu_data['grades'].items():
            grade=int(grade_s); cps=[ord(ch) for ch in chars]
            if len(cps)!=expected[grade] or len(set(cps))!=expected[grade]:
                raise RuntimeError(f'elementary grade {grade} count/duplicate mismatch')
            overlap=seen.intersection(cps)
            if overlap: raise RuntimeError(f'elementary cross-grade duplicate: {overlap}')
            seen.update(cps)
            cid=coll[f'education-elementary-g{grade}']
            for order,cp in enumerate(cps,1):
                if cp not in assigned_set:
                    raise RuntimeError(f'elementary kanji U+{cp:04X} missing from UCD')
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',
                            (cid,cp,order,f'MEXT grade {grade}'))
        if len(seen)!=1026: raise RuntimeError('elementary union must be 1026')

    # Joyo and Kanken. Kanken 10-5 are exactly the elementary cumulative grades;
    # 4/3/pre2/2 add the official grade-list characters. Normalize the Joyo/Kanken
    # representative 叱 to U+20B9F 𠮟 so the Unicode collection matches the 2010
    # Joyo Kanji repertoire while retaining U+53F1 independently elsewhere.
    if edu_data and kanken_data:
        elem_by_grade={int(g):[ord(ch) for ch in chars] for g,chars in edu_data['grades'].items()}
        incremental={k:list(v) for k,v in kanken_data['incremental'].items()}
        for k,exp in kanken_data['expected_incremental_counts'].items():
            if len(incremental[k])!=exp or len(set(incremental[k]))!=exp:
                raise RuntimeError(f'Kanken {k} incremental count mismatch')
        normalize=lambda ch: '𠮟' if ch=='叱' else ch
        cumulative=[]
        grade_map=[('10',1),('9',2),('8',3),('7',4),('6',5),('5',6)]
        for key,g in grade_map:
            cumulative.extend(chr(cp) for cp in elem_by_grade[g])
            cps=[ord(normalize(ch)) for ch in cumulative]
            if len(set(cps)) != kanken_data['expected_cumulative_counts'][key]: raise RuntimeError(f'Kanken {key} cumulative mismatch')
            for order,cp in enumerate(dict.fromkeys(cps),1):
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',(coll[f'kanken-{key}'],cp,order,'Kanken cumulative range'))
        for key in ('4','3','pre2','2'):
            cumulative.extend(incremental[key])
            cps=[ord(normalize(ch)) for ch in cumulative]
            uniq=list(dict.fromkeys(cps)); exp=kanken_data['expected_cumulative_counts'][key]
            if len(uniq)!=exp: raise RuntimeError(f'Kanken {key} cumulative mismatch: {len(uniq)} != {exp}')
            for order,cp in enumerate(uniq,1):
                if cp not in assigned_set: raise RuntimeError(f'Kanken {key} U+{cp:04X} missing from UCD')
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',(coll[f'kanken-{key}'],cp,order,'Kanken cumulative range'))
        joyo=list(dict.fromkeys(ord(normalize(ch)) for ch in cumulative))
        if len(joyo)!=2136 or 0x20B9F not in joyo or 0x53F1 in joyo:
            raise RuntimeError(f'Joyo set invariant failed: {len(joyo)}')
        elementary_union=set(cp for vals in elem_by_grade.values() for cp in vals)
        junior=[cp for cp in joyo if cp not in elementary_union]
        if len(junior)!=1110: raise RuntimeError(f'junior-high Joyo remainder mismatch: {len(junior)}')
        for order,cp in enumerate(joyo,1): cur.execute('INSERT INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',(coll['education-joyo'],cp,order,'Joyo Kanji 2010'))
        for order,cp in enumerate(junior,1): cur.execute('INSERT INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',(coll['education-junior-high'],cp,order,'Joyo minus elementary allocation'))
        print('Joyo',len(joyo),'junior-high',len(junior),'Kanken cumulative 2',len(set(ord(normalize(ch)) for ch in cumulative)))

    pos_cache={}
    def addmap(syskey,b,cps,kind='runtime-codec',plane=None,row=None,cell=None,poskey=None,src=codec_src,direction='both',priority=0,notes=None):
        key=poskey or b.hex().upper(); ck=(syskey,key)
        if ck not in pos_cache:
            cur.execute('INSERT INTO code_position(system_id,position_key,plane,row_no,cell_no,byte_value,numeric_value,source_id) VALUES (?,?,?,?,?,?,?,?)',
                        (systems[syskey],key,plane,row,cell,b,int.from_bytes(b,'big') if len(b)<=8 else None,src)); pos_cache[ck]=cur.lastrowid
        posid=pos_cache[ck]
        cur.execute('INSERT INTO mapping(code_position_id,direction,mapping_kind,priority,source_id,notes) VALUES (?,?,?,?,?,?)',(posid,direction,kind,priority,src,notes)); mid=cur.lastrowid
        for i,cp in enumerate(cps): cur.execute('INSERT INTO mapping_unicode(mapping_id,seq_index,cp) VALUES (?,?,?)',(mid,i,cp))
        return posid

    # JIS X 0201 Roman set: ASCII-like 94 graphic characters, with YEN SIGN at 0x5C and OVERLINE at 0x7E.
    for bval in range(0x21,0x7F):
        cp = 0x00A5 if bval==0x5C else (0x203E if bval==0x7E else bval)
        if cp in assigned_set:
            addmap('jis_x_0201_roman',bytes([bval]),[cp],poskey=f'0x{bval:02X}',kind='standard-derived',src=x0213_src)

    # Encoding mappings from runtime tables. Official CP932 importer below overrides provenance when file exists.
    t=time.time(); enc_count=0
    codecs=[('cp932','cp932'),('shift_jis','shift_jis'),('shift_jis_2004','shift_jis_2004'),('euc_jp','euc_jp'),('euc_jis_2004','euc_jis_2004'),('iso2022_jp','iso2022_jp'),('iso2022_jp_2004','iso2022_jp_2004')]
    for cp in assigned:
        ch=chr(cp)
        for sk,codec in codecs:
            try:b=ch.encode(codec)
            except (UnicodeEncodeError,LookupError):continue
            addmap(sk,b,[cp]); enc_count+=1
        try:b=ch.encode('euc_jp')
        except UnicodeEncodeError:b=None
        if b:
            if len(b)==2 and b[0]==0x8e and 0xa1<=b[1]<=0xdf:
                jb=bytes([b[1]-0x80]); addmap('jis_x_0201_kana',jb,[cp],poskey=f'0x{jb[0]:02X}')
            elif len(b)==2 and all(0xa1<=x<=0xfe for x in b):
                row,cell=b[0]-0xa0,b[1]-0xa0; addmap('jis_x_0208',b,[cp],row=row,cell=cell,poskey=f'{row:02d}-{cell:02d}')
        try:ch.encode('cp932'); cur.execute('INSERT INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['cp932-repertoire'],cp))
        except UnicodeEncodeError:pass
    # Canonical JIS X 0212 positions. EUC-JP SS3 decode exposes the full 6067-position repertoire,
    # including positions whose Unicode character has a shorter preferred EUC encoding (e.g. U+007E).
    for row in range(1,95):
        for cell in range(1,95):
            b=bytes([0x8F,row+0xA0,cell+0xA0])
            try:text=b.decode('euc_jp')
            except UnicodeDecodeError: continue
            addmap('jis_x_0212',b,[ord(ch) for ch in text],kind='runtime-codec-canonical-decode',row=row,cell=cell,poskey=f'{row:02d}-{cell:02d}',src=codec_src)

    # Canonical JIS X 0213:2004 positions. CPython's euc_jis_2004 deliberately accepts JIS X 0212
    # in otherwise unused SS3 rows, so enumerating that decoder would overstate the standard repertoire.
    # Shift_JIS-2004 has exactly the JIS X 0213 repertoire; decode its valid double-byte positions,
    # then use EUC-JIS-2004 only to recover plane/row/cell for the already-validated character.
    for lead in list(range(0x81,0xA0))+list(range(0xE0,0xFD)):
        for trail in list(range(0x40,0x7F))+list(range(0x80,0xFD)):
            sj=bytes([lead,trail])
            try:text=sj.decode('shift_jis_2004')
            except UnicodeDecodeError: continue
            try:
                if text.encode('shift_jis_2004') != sj: continue
                eb=text.encode('euc_jis_2004')
            except UnicodeEncodeError: continue
            if len(eb)==2 and all(0xA1<=x<=0xFE for x in eb):
                plane,row,cell=1,eb[0]-0xA0,eb[1]-0xA0
            elif len(eb)==3 and eb[0]==0x8F and all(0xA1<=x<=0xFE for x in eb[1:]):
                plane,row,cell=2,eb[1]-0xA0,eb[2]-0xA0
            else:
                # Two plane-1 positions decode to characters whose encoder prefers JIS X 0201 single-byte forms:
                # 0x815F REVERSE SOLIDUS and 0x81B0 TILDE. Recover their plane/row/cell from the standard Shift_JIS formula.
                if lead <= 0xEF and sj in (b'\x81\x5F', b'\x81\xB0'):
                    leadbase = 0x81 if lead < 0xA0 else 0xC1
                    row = (lead-leadbase)*2 + 1
                    if trail >= 0x9F:
                        row += 1; cell = trail-0x9E
                    else:
                        cell = trail-(0x3F if trail < 0x7F else 0x40)
                    plane=1; eb=bytes([row+0xA0,cell+0xA0])
                else:
                    continue
            addmap('jis_x_0213_2004',eb,[ord(ch) for ch in text],kind='runtime-codec-canonical-decode',plane=plane,row=row,cell=cell,poskey=f'{plane}-{row:02d}-{cell:02d}',src=codec_src)

    # JIS collection memberships and JIS X 0213:2000 derived position set.
    # Amendment 1 (2004) added exactly these 10 plane-1 characters.
    jis2004_added10={0x4FF1,0x525D,0x541E,0x5653,0x59F8,0x5C5B,0x5E77,0x7626,0x7E6B,0x20B9F}
    for cp in sorted(jis2004_added10):
        if cp in assigned_set:
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll['jis-x0213-2004-added10'],cp,'JIS X 0213:2004 Amendment 1 added character'))

    # X 0201 memberships.
    for pid,cp in cur.execute("""SELECT DISTINCT p.id,mu.cp FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id
        JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id WHERE cs.system_key='jis_x_0201_roman'""").fetchall():
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0201-roman'],cp))
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0201'],cp))
        for ck in ('jis-x0201-roman','jis-x0201'):
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll[ck],pid))
    for pid,cp in cur.execute("""SELECT DISTINCT p.id,mu.cp FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id
        JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id WHERE cs.system_key='jis_x_0201_kana'""").fetchall():
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0201-kana'],cp))
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0201'],cp))
        for ck in ('jis-x0201-kana','jis-x0201'):
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll[ck],pid))

    # X 0208 memberships: non-kanji plus level 1/2 by row.
    jis0208_rows=cur.execute("""SELECT DISTINCT p.id,p.row_no,mu.cp FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id
        JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id
        WHERE cs.system_key='jis_x_0208' AND mu.seq_index=0""").fetchall()
    jis0208_cps=set()
    jis0208_level1={cp for pid,row,cp in jis0208_rows if row is not None and 16 <= row <= 47}
    jis0208_level2={cp for pid,row,cp in jis0208_rows if row is not None and 48 <= row <= 84}
    for pid,row,cp in jis0208_rows:
        jis0208_cps.add(cp)
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0208-all'],cp))
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0208'],cp))
        for ck in ('jis-x0208-all','jis-x0208'):
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll[ck],pid))
        if cp in jis0208_level1:
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll['jis-x0208-level1'],pid))
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0208-level1'],cp))
        elif cp in jis0208_level2:
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0208-level2'],cp))
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll['jis-x0208-level2'],pid))
        else:
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0208-nonkanji'],cp))
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll['jis-x0208-nonkanji'],pid))

    # X 0212 memberships, split by Unicode Script=Han for navigation purposes.
    for pid,cp in cur.execute("""SELECT DISTINCT p.id,mu.cp FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id
        JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id WHERE cs.system_key='jis_x_0212' AND mu.seq_index=0""").fetchall():
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0212-all'],cp))
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0212'],cp))
        for ck in ('jis-x0212-all','jis-x0212'):
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll[ck],pid))
        script=cur.execute("SELECT us.name FROM unicode_codepoint u LEFT JOIN unicode_script us ON us.id=u.primary_script_id WHERE u.cp=?",(cp,)).fetchone()
        target='jis-x0212-kanji' if script and script[0]=='Han' else 'jis-x0212-nonkanji'
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll[target],cp))
        cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll[target],pid))

    # X 0213:2004 memberships and a derived X 0213:2000 code-position set (same positions minus the 10 amendment characters).
    x0213rows=cur.execute("""SELECT DISTINCT p.id,p.position_key,p.plane,p.row_no,p.cell_no,p.byte_value,mu.cp FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id
        JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id
        WHERE cs.system_key='jis_x_0213_2004' AND mu.seq_index=0""").fetchall()
    for pid,poskey,plane,row,cell,bval,cp in x0213rows:
        for ck in ('jis-x0213-2004-all','jis-x0213-2004-plane1' if plane==1 else 'jis-x0213-2004-plane2'):
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll[ck],cp))
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll[ck],pid))
        if cp in jis0208_level1:
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0213-2004-level1'],cp))
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll['jis-x0213-2004-level1'],pid))
        elif cp in jis0208_level2:
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0213-2004-level2'],cp))
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll['jis-x0213-2004-level2'],pid))
        else:
            script=cur.execute("SELECT us.name FROM unicode_codepoint u LEFT JOIN unicode_script us ON us.id=u.primary_script_id WHERE u.cp=?",(cp,)).fetchone()
            if script and script[0]=='Han' and cp != 0x303B and (plane==2 or cp not in jis0208_cps):
                levelkey='jis-x0213-2004-level3' if plane==1 else 'jis-x0213-2004-level4'
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll[levelkey],cp))
                cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll[levelkey],pid))
        if cp in jis2004_added10:
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll['jis-x0213-2004-added10'],pid))
        if cp not in jis2004_added10:
            p2000=addmap('jis_x_0213_2000',bval,[cp],kind='derived-from-2004-minus-amendment1',plane=plane,row=row,cell=cell,poskey=poskey,src=x0213_src,
                   notes='Derived JIS X 0213:2000 position: JIS X 0213:2004 position excluding the 10 Amendment 1 additions.')
            for ck in ('jis-x0213-2000-all','jis-x0213-2000-plane1' if plane==1 else 'jis-x0213-2000-plane2'):
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll[ck],cp))
                cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll[ck],p2000))
            if cp in jis0208_level1:
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0213-2000-level1'],cp))
                cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll['jis-x0213-2000-level1'],p2000))
            elif cp in jis0208_level2:
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll['jis-x0213-2000-level2'],cp))
                cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll['jis-x0213-2000-level2'],p2000))
            else:
                script=cur.execute("SELECT us.name FROM unicode_codepoint u LEFT JOIN unicode_script us ON us.id=u.primary_script_id WHERE u.cp=?",(cp,)).fetchone()
                if script and script[0]=='Han' and cp != 0x303B and (plane==2 or cp not in jis0208_cps):
                    levelkey='jis-x0213-2000-level3' if plane==1 else 'jis-x0213-2000-level4'
                    cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp) VALUES (?,?)',(coll[levelkey],cp))
                    cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id) VALUES (?,?)',(coll[levelkey],p2000))

    # Historical JIS editions and revision-difference collections.
    # Code-position crosswalks are derived from Adobe-Japan1 CMaps; revision/glyph metadata is kept separate.
    if jis_history:
        edition_map={
            'jis_c_6226_1978':('jis_c_6226_1978','jis-c6226-1978'),
            'jis_c_6226_1983':('jis_c_6226_1983','jis-c6226-1983'),
            'jis_x_0208_1990':('jis_x_0208_1990','jis-x0208-1990'),
        }
        historical_posids={}
        for data_key,(syskey,ckey) in edition_map.items():
            ed=jis_history['editions'][data_key]
            for order,r in enumerate(ed['positions'],1):
                row,cell,cp=r['row'],r['cell'],r.get('cp')
                raw=bytes([row+0x20,cell+0x20])
                poskey=f'{row:02d}-{cell:02d}'
                if cp is not None and cp in assigned_set:
                    pid=addmap(syskey,raw,[cp],kind='historical-cmap-crosswalk',row=row,cell=cell,poskey=poskey,src=jis_history_adobe_src,
                               notes='Historical JIS crosswalk derived from Adobe-Japan1 CMap; use JIS standard text as normative source.')
                    cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order) VALUES (?,?,?)',(coll[ckey],cp,order))
                else:
                    key=(syskey,poskey)
                    if key not in pos_cache:
                        cur.execute('INSERT INTO code_position(system_id,position_key,row_no,cell_no,byte_value,numeric_value,source_id,notes) VALUES (?,?,?,?,?,?,?,?)',
                                    (systems[syskey],poskey,row,cell,raw,int.from_bytes(raw,'big'),jis_history_adobe_src,'Historical JIS code position; Unicode mapping unavailable in Adobe cidToUnicode crosswalk.'))
                        pos_cache[key]=cur.lastrowid
                    pid=pos_cache[key]
                historical_posids[(syskey,poskey)]=pid
                cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id,sort_order) VALUES (?,?,?)',(coll[ckey],pid,order))
                suffix='level1' if 16 <= row <= 47 else ('level2' if 48 <= row <= 84 else 'nonkanji')
                child=f'{ckey}-{suffix}'
                cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id,sort_order) VALUES (?,?,?)',(coll[child],pid,order))
                if cp is not None and cp in assigned_set:
                    cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order) VALUES (?,?,?)',(coll[child],cp,order))

        d78=jis_history['diffs']['78_to_83']
        # 71 genuinely new positions in 83JIS (excluding the four separately encoded old forms).
        for order,poskey in enumerate(d78['added_71_positions'],1):
            pid=historical_posids[('jis_c_6226_1983',poskey)]
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id,sort_order,notes) VALUES (?,?,?,?)',(coll['jis-rev-78-83-added71'],pid,order,'83JIS new position'))
            for (cp,) in cur.execute('SELECT mu.cp FROM mapping m JOIN mapping_unicode mu ON mu.mapping_id=m.id WHERE m.code_position_id=? ORDER BY mu.seq_index',(pid,)).fetchall():
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order) VALUES (?,?,?)',(coll['jis-rev-78-83-added71'],cp,order))
        for order,poskey in enumerate(d78['old_form_added_4_positions'],1):
            pid=historical_posids[('jis_c_6226_1983',poskey)]
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id,sort_order,notes) VALUES (?,?,?,?)',(coll['jis-rev-78-83-old4'],pid,order,'83JIS separately encoded old-form position'))
            for (cp,) in cur.execute('SELECT mu.cp FROM mapping m JOIN mapping_unicode mu ON mu.mapping_id=m.id WHERE m.code_position_id=? ORDER BY mu.seq_index',(pid,)).fetchall():
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order) VALUES (?,?,?)',(coll['jis-rev-78-83-old4'],cp,order))
        # 22 swap pairs = 44 affected positions. Pair members are adjacent by sort_order and notes identify the pair.
        for pair_index,pair in enumerate(d78['swap_pairs_22'],1):
            for side,poskey in enumerate((pair['a'],pair['b'])):
                pid=historical_posids[('jis_c_6226_1983',poskey)]
                note=f'78JIS↔83JIS code-position swap pair {pair_index}: {pair["a"]} ⇄ {pair["b"]}'
                cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id,sort_order,notes) VALUES (?,?,?,?)',(coll['jis-rev-78-83-swaps22'],pid,pair_index*2+side,note))
                for (cp,) in cur.execute('SELECT mu.cp FROM mapping m JOIN mapping_unicode mu ON mu.mapping_id=m.id WHERE m.code_position_id=? ORDER BY mu.seq_index',(pid,)).fetchall():
                    cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',(coll['jis-rev-78-83-swaps22'],cp,pair_index*2+side,note))
        for order,ch in enumerate(d78['non_unified_29_chars'],1):
            cp=ord(ch)
            if cp in assigned_set:
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',(coll['jis-rev-78-83-nonunified29'],cp,order,'JIS97: not unified with the changed form'))

        d90=jis_history['diffs']['83_to_90']
        for order,poskey in enumerate(d90['added_2_positions'],1):
            pid=historical_posids[('jis_x_0208_1990',poskey)]
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id,sort_order) VALUES (?,?,?)',(coll['jis-rev-83-90-added2'],pid,order))
            for (cp,) in cur.execute('SELECT mu.cp FROM mapping m JOIN mapping_unicode mu ON mu.mapping_id=m.id WHERE m.code_position_id=? ORDER BY mu.seq_index',(pid,)).fetchall():
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order) VALUES (?,?,?)',(coll['jis-rev-83-90-added2'],cp,order))
        for order,ch in enumerate(d90['representative_glyph_change_chars'],1):
            cp=ord(ch)
            if cp in assigned_set:
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',(coll['jis-rev-83-90-glyph225'],cp,order,'JIS83→JIS90 representative glyph change'))

        d2004=jis_history['diffs']['2000_to_2004']
        for order,ch in enumerate(d2004['representative_glyph_change_chars'],1):
            cp=ord(ch)
            if cp in assigned_set:
                cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',(coll['jis-rev-2000-2004-glyph168'],cp,order,'JIS2000→JIS2004 representative glyph change'))

    # CP932 is not one-to-one: some byte positions decode to the same Unicode character,
    # while Unicode->CP932 encoding chooses one canonical position. Preserve decode aliases
    # instead of collapsing them. Example: U+7864 decodes from EE5E and FB7A, but encodes to EE5E.
    cp932_decode_aliases=0
    for lead in list(range(0x81,0xA0))+list(range(0xE0,0xFD)):
        for trail in list(range(0x40,0x7F))+list(range(0x80,0xFD)):
            b=bytes((lead,trail))
            try: text=b.decode('cp932')
            except UnicodeDecodeError: continue
            if len(text)!=1: continue
            cp=ord(text)
            if cp not in assigned_set: continue
            key=('cp932',b.hex().upper())
            pid=pos_cache.get(key)
            exists=False
            if pid is not None:
                exists=cur.execute('''SELECT 1 FROM mapping m JOIN mapping_unicode mu ON mu.mapping_id=m.id
                    WHERE m.code_position_id=? AND mu.seq_index=0 AND mu.cp=?''',(pid,cp)).fetchone() is not None
            if not exists:
                addmap('cp932',b,[cp],kind='runtime-codec-decode-alias',direction='decode',priority=10,
                       notes='CP932 decode alias/duplicate code position; Unicode encoding may choose another CP932 position.')
                cp932_decode_aliases += 1
    print('codec mappings',enc_count,'cp932 decode aliases',cp932_decode_aliases,'seconds',round(time.time()-t,2))

    # Windows-31J vendor-extension provenance by byte ranges.  These ranges are
    # structural/code-position classifications, independent of Unicode mapping aliases.
    cp932_vendor_ranges=[
        ('cp932-nec-special',0x8740,0x879C,'NEC special characters / Row 13'),
        ('cp932-nec-selected-ibm',0xED40,0xEEFC,'NEC selection of IBM extensions / Rows 89-92'),
        ('cp932-ibm-extension',0xFA40,0xFC4B,'IBM extensions / Rows 115-119'),
    ]
    vendor_counts={}
    for ck,lo,hi,note in cp932_vendor_ranges:
        cps=set(); positions=0
        for value in range(lo,hi+1):
            b=value.to_bytes(2,'big')
            if b[1]==0x7F: continue
            try:text=b.decode('cp932')
            except UnicodeDecodeError: continue
            if len(text)!=1: continue
            cp=ord(text)
            if cp not in assigned_set: continue
            positions += 1; cps.add(cp)
            pid=pos_cache.get(('cp932',b.hex().upper()))
            if pid:
                cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id,notes) VALUES (?,?,?)',(coll[ck],pid,note))
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll[ck],cp,note))
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll['cp932-vendor'],cp,note))
        vendor_counts[ck]=(positions,len(cps))
    print('cp932 vendor classifications',vendor_counts)

    # Full SJIS/CP932 trailing-0x5C issue collections.
    for sk,ck in [('shift_jis','sjis-bad-5c'),('cp932','cp932-bad-5c')]:
        rows=cur.execute('''SELECT DISTINCT mu.cp FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id
            JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id
            WHERE cs.system_key=? AND m.direction IN ('encode','both') AND length(p.byte_value)=2 AND substr(hex(p.byte_value),3,2)='5C' ''',(sk,)).fetchall()
        for (cp,) in rows:
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll[ck],cp,f'{sk} trailing byte 0x5C'))
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll['sjis-bad'],cp,f'{sk} trailing byte 0x5C'))

    # ARIB capability vs operational implementation.
    # STD-B24 can carry JIS X 0213 Plane 1/2, while TR-B15 states that receiver implementation
    # of JIS levels 3 and 4 is a product-planning matter.  Keep both dimensions explicit.
    arib_rows=cur.execute('''SELECT DISTINCT p.plane,mu.cp FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id
        JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id
        WHERE cs.system_key='jis_x_0213_2004' AND mu.seq_index=0 AND p.plane IN (1,2)''').fetchall()
    jis0208_cps={r[0] for r in cur.execute('''SELECT DISTINCT mu.cp FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id
        JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id
        WHERE cs.system_key='jis_x_0208' AND mu.seq_index=0''').fetchall()}
    for plane,cp in arib_rows:
        cid=coll['arib-jis-plane1'] if plane==1 else coll['arib-jis-plane2']
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(cid,cp,'STD-B24 capability derived from JIS X 0213:2004'))
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll['arib-jis-compatible'],cp,'STD-B24 JIS-compatible repertoire'))
        if plane==2:
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll['arib-optional-jis4'],cp,'TR-B15: level 4 receiver support is product-planning matter'))
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll['arib-optional-jis34'],cp,'optional receiver implementation'))
        elif cp not in jis0208_cps:
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll['arib-optional-jis3'],cp,'TR-B15: level 3 receiver support is product-planning matter'))
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll['arib-optional-jis34'],cp,'optional receiver implementation'))

    # Provisional common operational core: JIS X 0208 repertoire. Fixed ARIB additions are appended below.
    for cp in jis0208_cps:
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll['arib-operational-core'],cp,'provisional common core: JIS X 0208 repertoire'))

    # v1.0 derived collections: width compatibility, CP932 extensions/EUDC, ARIB fixed symbols.
    # Width compatibility comes directly from Unicode decomposition tags <wide>/<narrow>.
    for cp,decomp in cur.execute("SELECT cp,decomposition FROM unicode_codepoint WHERE decomposition LIKE '<wide>%' OR decomposition LIKE '<narrow>%'").fetchall():
        tag='full' if decomp.startswith('<wide>') else 'half'
        cid=coll['width-full'] if tag=='full' else coll['width-half']
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(cid,cp,'derived from Unicode compatibility decomposition'))
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll['width-compat'],cp,'derived from Unicode compatibility decomposition'))
        parts=decomp.split()[1:]
        if len(parts)==1:
            tocp=int(parts[0],16)
            if cur.execute('SELECT 1 FROM unicode_codepoint WHERE cp=?',(tocp,)).fetchone():
                cur.execute('INSERT OR IGNORE INTO relation(from_cp,to_cp,relation_type,source_id,notes) VALUES (?,?,?,?,?)',(cp,tocp,'width-compatibility',width_src,tag+'width compatibility decomposition'))
                cur.execute('INSERT OR IGNORE INTO relation(from_cp,to_cp,relation_type,source_id,notes) VALUES (?,?,?,?,?)',(tocp,cp,'width-compatibility-reverse',width_src,tag+'width compatibility variant'))

    # CP932 repertoire minus JIS X 0201/0208 positions. This is intentionally named a candidate set:
    # JIS X 0213 and historical/vendor classifications are separate dimensions.
    q="""SELECT DISTINCT mu.cp FROM mapping_unicode mu
         JOIN mapping m ON m.id=mu.mapping_id JOIN code_position p ON p.id=m.code_position_id
         JOIN code_system cs ON cs.id=p.system_id
         WHERE cs.system_key='cp932' AND m.direction IN ('encode','both')
           AND p.byte_value NOT BETWEEN X'F040' AND X'F9FC'
           AND length(p.byte_value)=2
           AND NOT EXISTS (SELECT 1 FROM mapping_unicode jmu JOIN mapping jm ON jm.id=jmu.mapping_id
             JOIN code_position jp ON jp.id=jm.code_position_id JOIN code_system jcs ON jcs.id=jp.system_id
             WHERE jmu.cp=mu.cp AND jmu.seq_index=0 AND jcs.system_key IN ('jis_x_0201_kana','jis_x_0208'))"""
    for (cp,) in cur.execute(q).fetchall():
        cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll['cp932-extensions'],cp,'derived CP932 minus JIS X 0201/0208'))

    # Crosswalk: characters in the CP932 extension candidate set that are also in JIS X 0213,
    # but use a different canonical byte position in CP932 vs Shift_JIS-2004. This describes
    # an observable mapping relationship; it does not by itself assert the historical source
    # of each individual JIS character.
    ext_cid=coll['cp932-extensions']
    for (cp,) in cur.execute('SELECT cp FROM collection_member_unicode WHERE collection_id=?',(ext_cid,)).fetchall():
        cp932_row=cur.execute('''SELECT p.byte_value FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id
            JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id
            WHERE mu.cp=? AND mu.seq_index=0 AND cs.system_key='cp932' AND m.direction IN ('encode','both')
            ORDER BY m.priority,p.id LIMIT 1''',(cp,)).fetchone()
        sj04_row=cur.execute('''SELECT p.byte_value FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id
            JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id
            WHERE mu.cp=? AND mu.seq_index=0 AND cs.system_key='shift_jis_2004' AND m.direction IN ('encode','both')
            ORDER BY m.priority,p.id LIMIT 1''',(cp,)).fetchone()
        jis_row=cur.execute('''SELECT 1 FROM mapping_unicode mu JOIN mapping m ON m.id=mu.mapping_id
            JOIN code_position p ON p.id=m.code_position_id JOIN code_system cs ON cs.id=p.system_id
            WHERE mu.cp=? AND cs.system_key='jis_x_0213_2004' LIMIT 1''',(cp,)).fetchone()
        if cp932_row and sj04_row and jis_row and cp932_row[0]!=sj04_row[0]:
            note=f"CP932 {cp932_row[0].hex().upper()} / Shift_JIS-2004 {sj04_row[0].hex().upper()}"
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',
                        (coll['cp932-jis0213-reassigned'],cp,note))

    # Windows CP932 EUDC range. Runtime cp932 maps F040-F9FC sequentially to U+E000-U+E757.
    # Keep byte positions as the primary entity and annotate via the generic mapping model.
    eudc_positions=[]
    for lead in range(0xF0,0xFA):
        for trail in list(range(0x40,0x7F))+list(range(0x80,0xFD)):
            b=bytes([lead,trail])
            try: text=b.decode('cp932')
            except UnicodeDecodeError: continue
            if len(text)!=1: continue
            cp=ord(text)
            if not (0xE000<=cp<=0xE757): continue
            pid=pos_cache.get(('cp932',b.hex().upper()))
            if pid is None:
                addmap('cp932',b,[cp],kind='windows-eudc',src=ms_eudc_src); pid=pos_cache[('cp932',b.hex().upper())]
            cur.execute('INSERT OR IGNORE INTO collection_member_position(collection_id,code_position_id,notes) VALUES (?,?,?)',(coll['cp932-eudc'],pid,'CP932 EUDC'))
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll['unicode-pua-cp932'],cp,'corresponding CP932 EUDC'))
            eudc_positions.append(pid)

    # ARIB fixed additional Kanji (Table 7-11 / rows 85-86).  DRCS is explicitly out of scope.
    # The list is kept as Unicode scalar values; compatibility ideographs remain distinct where ARIB maps them distinctly.
    arib_additional_kanji = [int(x[2:],16) for x in arib_data.get('additional_kanji',[])]
    arib_seen=set()
    for order,cp in enumerate(arib_additional_kanji,1):
        if cp in arib_seen: continue
        arib_seen.add(cp)
        if cur.execute('SELECT 1 FROM unicode_codepoint WHERE cp=?',(cp,)).fetchone():
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',(coll['arib-additional-kanji'],cp,order,'ARIB STD-B24 additional Kanji; fixed character, not DRCS'))
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',(coll['arib-operational-core'],cp,order,'provisional common core: fixed ARIB additional Kanji'))

    # ARIB fixed additional symbols.  This remains a partial Unicode-mapped subset while
    # the complete Tables 7-10/7-19 transcription is audited; DRCS is not included.
    for order,cp in enumerate([int(x[2:],16) for x in arib_data.get('additional_symbols_partial',[])],1):
        if cur.execute('SELECT 1 FROM unicode_codepoint WHERE cp=?',(cp,)).fetchone():
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',(coll['arib-fixed'],cp,order,'ARIB fixed additional symbol; DRCS excluded; partial audited subset'))
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',(coll['arib-operational-core'],cp,order,'provisional common core: fixed ARIB additional symbol'))

    assigned_set=set(assigned)
    # Curated regression issues / relations only if their cps exist.
    issue_ids={}
    for it in json.loads(ISSUES.read_text(encoding='utf-8'))['issues']:
        cur.execute('INSERT INTO issue(issue_key,title,category,severity,description,source_id) VALUES (?,?,?,?,?,?)',(it['key'],it['title'],it['category'],it.get('severity'),it.get('description'),custom_src)); issue_ids[it['key']]=cur.lastrowid
    # Crosswalk issue is attached from the derived collection rather than hand-maintained
    # per-character vectors. This keeps the issue synchronized when official tables replace
    # provisional runtime codec mappings.
    cross_issue=issue_ids.get('cp932-jis0213-reassignment')
    if cross_issue:
        for (cp,) in cur.execute('SELECT cp FROM collection_member_unicode WHERE collection_id=?',(coll['cp932-jis0213-reassigned'],)).fetchall():
            cur.execute('INSERT OR IGNORE INTO unicode_issue(cp,issue_id,notes) VALUES (?,?,?)',
                        (cp,cross_issue,'derived CP932/JIS X 0213 crosswalk'))

    for v in json.loads(VECTORS.read_text(encoding='utf-8'))['vectors']:
        cps=[int(x[2:],16) for x in v['expect']['codepoints']]
        for ikey in v['expect'].get('issues',[]):
            for cp in cps:
                if cp not in assigned_set: continue
                cur.execute('INSERT OR IGNORE INTO unicode_issue(cp,issue_id,notes) VALUES (?,?,?)',(cp,issue_ids[ikey],v['id']))
                ck={'sjis-trailing-5c':'sjis-bad','wave-dash-mapping':'wave-dash','jis90-jis2004-glyph-change':'jis2004-glyph'}.get(ikey)
                if ck:cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,notes) VALUES (?,?,?)',(coll[ck],cp,v['id']))
    for a,b,tpe in [(0x9AD8,0x9AD9,'variant'),(0x5D0E,0xFA11,'variant'),(0x585A,0xFA10,'compatibility-variant')]:
        if a in assigned_set and b in assigned_set:
            cur.execute('INSERT OR IGNORE INTO relation(from_cp,to_cp,relation_type,source_id) VALUES (?,?,?,?)',(a,b,tpe,custom_src));cur.execute('INSERT OR IGNORE INTO relation(from_cp,to_cp,relation_type,source_id) VALUES (?,?,?,?)',(b,a,tpe,custom_src))
    # Tsuji prototype IVS until IVD importer is added.
    for cp in (0xE0100,0xE0101):
        if cp not in assigned_set:
            cur.execute('INSERT OR IGNORE INTO unicode_codepoint(cp,name,age,general_category,source_id) VALUES (?,?,?,?,?)',(cp,f'VARIATION SELECTOR-{cp-0xE0100+17}', '4.0','Mn',ucd_src))
    cur.execute("INSERT INTO variation_collection(collection_key,title,source_id) VALUES ('adobe-japan1','Adobe-Japan1',?)",(custom_src,)); vcid=cur.lastrowid
    for base,vs,label in [(0x8FBB,0xE0100,'JIS90'),(0x8FBB,0xE0101,'JIS2004')]:
        cur.execute('INSERT INTO variation_sequence(base_cp,variation_cp,collection_id,source_id) VALUES (?,?,?,?)',(base,vs,vcid,custom_src)); vid=cur.lastrowid
        cur.execute("INSERT INTO variation_annotation(variation_id,key,value) VALUES (?, 'glyph-standard', ?)",(vid,label))
    # ---- Structural regression fixtures (temporary; deliberately small) ----
    # These exercise sequence mappings, directional mappings, IVS handling and
    # code positions that intentionally have no Unicode mapping. They are kept
    # separate from standards data and can be removed once authoritative imports
    # cover the same edge cases.
    cur.execute("INSERT OR IGNORE INTO meta(key,value) VALUES ('structural_fixtures','1')")

    # Exact multi-code-point mappings. Do not infer these by concatenating scalar mappings.
    structural_sequences=[
        ('halfwidth-kana-ga',[0xFF76,0xFF9E]),
        ('jis0213-combining-kana',[0x304B,0x309A]),
    ]
    for seq_order,(label,cps) in enumerate(structural_sequences,1):
        text=''.join(chr(cp) for cp in cps)
        for sk,codec in codecs:
            try:b=text.encode(codec)
            except (UnicodeEncodeError,LookupError):continue
            addmap(sk,b,cps,kind='structural-sequence',src=custom_src)
        cur.execute('INSERT INTO unicode_sequence(sequence_key,sequence_type,name,source_id,notes) VALUES (?,?,?,?,?)',
                    ('debug-'+label,'structural-mapping-sequence',label,custom_src,'test-only exact mapping fixture'))
        sid=cur.lastrowid
        for i,cp in enumerate(cps):
            cur.execute('INSERT INTO unicode_sequence_member(sequence_id,seq_index,cp) VALUES (?,?,?)',(sid,i,cp))
        cur.execute('INSERT INTO collection_member_sequence(collection_id,sequence_id,sort_order,notes) VALUES (?,?,?,?)',
                    (coll['debug-structural'],sid,seq_order,'test-only exact mapping fixture'))

    # Directionality fixture: same conceptual Unicode side can have decode-only / encode-only rows.
    cur.execute("INSERT OR IGNORE INTO code_system(system_key,title,system_type,source_id,notes) VALUES ('test_directional','構造試験: direction','test',?, 'test-only')",(custom_src,))
    test_dir_id=cur.execute("SELECT id FROM code_system WHERE system_key='test_directional'").fetchone()[0]
    for key,cp,direction in [('D1',0x301C,'decode'),('E1',0xFF5E,'encode')]:
        cur.execute('INSERT INTO code_position(system_id,position_key,byte_value,source_id,notes) VALUES (?,?,?,?,?)',(test_dir_id,key,bytes.fromhex(key),custom_src,'test-only'))
        pid=cur.lastrowid
        cur.execute('INSERT INTO mapping(code_position_id,direction,mapping_kind,source_id,notes) VALUES (?,?,?,?,?)',(pid,direction,'structural-test',custom_src,'test-only'))
        mid=cur.lastrowid; cur.execute('INSERT INTO mapping_unicode(mapping_id,seq_index,cp) VALUES (?,?,?)',(mid,0,cp))
        cur.execute('INSERT INTO collection_member_position(collection_id,code_position_id,sort_order,notes) VALUES (?,?,?,?)',
                    (coll['debug-structural'],pid,5 if direction=='decode' else 6,'test-only directional mapping'))

    # A JIS-like code-position collection with one mapped and one deliberately unmapped entry.
    cur.execute("INSERT OR IGNORE INTO code_system(system_key,title,system_type,source_id,notes) VALUES ('test_jis_position','構造試験JIS位置','standard-position',?, 'test-only')",(custom_src,))
    test_jis_id=cur.execute("SELECT id FROM code_system WHERE system_key='test_jis_position'").fetchone()[0]
    # mapped sample
    cur.execute('INSERT INTO code_position(system_id,position_key,plane,row_no,cell_no,source_id,notes) VALUES (?,?,?,?,?,?,?)',(test_jis_id,'1-01-01',1,1,1,custom_src,'test-only mapped sample'))
    p1=cur.lastrowid
    cur.execute('INSERT INTO mapping(code_position_id,direction,mapping_kind,source_id,notes) VALUES (?,?,?,?,?)',(p1,'both','structural-test',custom_src,'test-only')); m1=cur.lastrowid
    cur.execute('INSERT INTO mapping_unicode(mapping_id,seq_index,cp) VALUES (?,?,?)',(m1,0,0x4E00))
    # unmapped sample
    cur.execute('INSERT INTO code_position(system_id,position_key,plane,row_no,cell_no,source_id,notes) VALUES (?,?,?,?,?,?,?)',(test_jis_id,'1-01-02',1,1,2,custom_src,'test-only; intentionally no Unicode mapping'))
    p2=cur.lastrowid
    cur.execute('INSERT INTO collection_member_position(collection_id,code_position_id,sort_order,notes) VALUES (?,?,?,?)',(coll['debug-structural'],p1,10,'mapped test row'))
    cur.execute('INSERT INTO collection_member_position(collection_id,code_position_id,sort_order,notes) VALUES (?,?,?,?)',(coll['debug-structural'],p2,20,'unmapped test row'))

    # v0.6 structural fixtures: normalization-adjacent, ambiguous mappings,
    # non-roundtrip mappings, aliases, and multiple variation collections.
    # These deliberately exercise the existing generic mapping model rather than
    # introducing special-case schema that would later conflict with standards data.

    # Same byte/code position decodes and encodes to different Unicode values.
    cur.execute("INSERT OR IGNORE INTO code_system(system_key,title,system_type,source_id,notes) VALUES ('test_roundtrip','構造試験: non-roundtrip','encoding',?, 'test-only')",(custom_src,))
    rt_sid=cur.execute("SELECT id FROM code_system WHERE system_key='test_roundtrip'").fetchone()[0]
    cur.execute('INSERT INTO code_position(system_id,position_key,byte_value,source_id,notes) VALUES (?,?,?,?,?)',(rt_sid,'81 60',bytes.fromhex('8160'),custom_src,'test-only; encode/decode intentionally differ'))
    rt_pid=cur.lastrowid
    for cp,direction,kind,priority in [(0x301C,'decode','standard',0),(0xFF5E,'encode','vendor',0)]:
        cur.execute('INSERT INTO mapping(code_position_id,direction,mapping_kind,priority,source_id,notes) VALUES (?,?,?,?,?,?)',(rt_pid,direction,kind,priority,custom_src,'test-only non-roundtrip'))
        mid=cur.lastrowid;cur.execute('INSERT INTO mapping_unicode(mapping_id,seq_index,cp) VALUES (?,?,?)',(mid,0,cp))

    # One byte position with multiple decode candidates. Neither candidate may be dropped.
    cur.execute("INSERT OR IGNORE INTO code_system(system_key,title,system_type,source_id,notes) VALUES ('test_ambiguous','構造試験: ambiguous decode','encoding',?, 'test-only')",(custom_src,))
    amb_sid=cur.execute("SELECT id FROM code_system WHERE system_key='test_ambiguous'").fetchone()[0]
    cur.execute('INSERT INTO code_position(system_id,position_key,byte_value,source_id,notes) VALUES (?,?,?,?,?)',(amb_sid,'A1',bytes.fromhex('A1'),custom_src,'test-only; two decode candidates'))
    amb_pid=cur.lastrowid
    for cp,kind,priority in [(0x301C,'standard',0),(0xFF5E,'vendor',10)]:
        cur.execute('INSERT INTO mapping(code_position_id,direction,mapping_kind,priority,source_id,notes) VALUES (?,?,?,?,?,?)',(amb_pid,'decode',kind,priority,custom_src,'test-only ambiguous decode'))
        mid=cur.lastrowid;cur.execute('INSERT INTO mapping_unicode(mapping_id,seq_index,cp) VALUES (?,?,?)',(mid,0,cp))

    # Multiple code positions for the same Unicode scalar (aliases / vendor duplicates).
    cur.execute("INSERT OR IGNORE INTO code_system(system_key,title,system_type,source_id,notes) VALUES ('test_alias','構造試験: Unicode alias positions','encoding',?, 'test-only')",(custom_src,))
    alias_sid=cur.execute("SELECT id FROM code_system WHERE system_key='test_alias'").fetchone()[0]
    for key,hxv,priority,kind in [('A1','A1',0,'standard'),('A2','A2',10,'vendor')]:
        cur.execute('INSERT INTO code_position(system_id,position_key,byte_value,source_id,notes) VALUES (?,?,?,?,?)',(alias_sid,key,bytes.fromhex(hxv),custom_src,'test-only alias'))
        pid=cur.lastrowid
        cur.execute('INSERT INTO mapping(code_position_id,direction,mapping_kind,priority,source_id,notes) VALUES (?,?,?,?,?,?)',(pid,'both',kind,priority,custom_src,'test-only alias'))
        mid=cur.lastrowid;cur.execute('INSERT INTO mapping_unicode(mapping_id,seq_index,cp) VALUES (?,?,?)',(mid,0,0x00A5))

    # Make mapping edge cases inspectable only through the consolidated debug Collection.
    edge_positions=[rt_pid,amb_pid]
    edge_positions += [r[0] for r in cur.execute("SELECT p.id FROM code_position p JOIN code_system cs ON cs.id=p.system_id WHERE cs.system_key='test_alias' ORDER BY p.position_key")]
    for i,pid in enumerate(edge_positions,1):
        cur.execute('INSERT INTO collection_member_position(collection_id,code_position_id,sort_order,notes) VALUES (?,?,?,?)',(coll['debug-structural'],pid,30+i,'test-only mapping edge case'))

    # A second variation collection on the same base character, using a different VS.
    # This tests that collection identity remains first-class and annotations do not collapse.
    if 0xE0102 not in assigned_set:
        cur.execute('INSERT OR IGNORE INTO unicode_codepoint(cp,name,age,general_category,source_id) VALUES (?,?,?,?,?)',(0xE0102,'VARIATION SELECTOR-19','4.0','Mn',ucd_src))
    cur.execute("INSERT INTO variation_collection(collection_key,title,source_id) VALUES ('test-ivd-alt','構造試験 Variation Collection',?)",(custom_src,)); alt_vcid=cur.lastrowid
    cur.execute('INSERT INTO variation_sequence(base_cp,variation_cp,collection_id,source_id) VALUES (?,?,?,?)',(0x8FBB,0xE0102,alt_vcid,custom_src)); alt_vid=cur.lastrowid
    cur.execute("INSERT INTO variation_annotation(variation_id,key,value) VALUES (?, 'glyph-standard', 'ALT-COLLECTION')",(alt_vid,))

    # v0.7: revision-specific standard positions. Separate code_system rows model
    # standards/revisions; the Unicode side stays shared and no position is overwritten.
    for sk,title,pos in [
        ('test_jis_revision_old','構造試験: JIS旧版','1-10-10'),
        ('test_jis_revision_new','構造試験: JIS新版','1-20-20'),
    ]:
        cur.execute('INSERT INTO code_system(system_key,title,system_type,source_id,notes) VALUES (?,?,?,?,?)',(sk,title,'standard-position',custom_src,'test-only revision fixture'))
        sid=cur.lastrowid
        pl,row,cell=[int(x) for x in pos.split('-')]
        cur.execute('INSERT INTO code_position(system_id,position_key,plane,row_no,cell_no,source_id,notes) VALUES (?,?,?,?,?,?,?)',(sid,pos,pl,row,cell,custom_src,'test-only revision-specific position'))
        pid=cur.lastrowid
        cur.execute('INSERT INTO mapping(code_position_id,direction,mapping_kind,source_id,notes) VALUES (?,?,?,?,?)',(pid,'both','structural-revision',custom_src,'same Unicode, different standard revision position'))
        mid=cur.lastrowid;cur.execute('INSERT INTO mapping_unicode(mapping_id,seq_index,cp) VALUES (?,?,?)',(mid,0,0x8FBB))
        cur.execute('INSERT INTO collection_member_position(collection_id,code_position_id,sort_order,notes) VALUES (?,?,?,?)',
                    (coll['debug-structural'],pid,50 if sk.endswith('old') else 51,'test-only revision-specific position'))

    # One Unicode sequence mapped to more than one standard position. This ensures
    # sequence mappings remain many-to-many instead of being reduced to a single key.
    cur.execute("INSERT INTO code_system(system_key,title,system_type,source_id,notes) VALUES ('test_seq_positions','構造試験: sequence複数規格位置','standard-position',?, 'test-only')",(custom_src,))
    seq_sid=cur.lastrowid
    for pos in ('1-30-30','2-40-40'):
        pl,row,cell=[int(x) for x in pos.split('-')]
        cur.execute('INSERT INTO code_position(system_id,position_key,plane,row_no,cell_no,source_id,notes) VALUES (?,?,?,?,?,?,?)',(seq_sid,pos,pl,row,cell,custom_src,'test-only sequence alias position'))
        pid=cur.lastrowid
        cur.execute('INSERT INTO mapping(code_position_id,direction,mapping_kind,source_id,notes) VALUES (?,?,?,?,?)',(pid,'both','structural-sequence-position',custom_src,'same Unicode sequence at multiple positions'))
        mid=cur.lastrowid
        for i,cp in enumerate((0x304B,0x309A)):cur.execute('INSERT INTO mapping_unicode(mapping_id,seq_index,cp) VALUES (?,?,?)',(mid,i,cp))
        cur.execute('INSERT INTO collection_member_position(collection_id,code_position_id,sort_order,notes) VALUES (?,?,?,?)',
                    (coll['debug-structural'],pid,60 if pos.startswith('1-') else 61,'test-only sequence alias position'))

    # v0.8 structural fixtures: first-class Unicode sequences that are neither
    # encoding mappings nor IVS. This is the model used later for Emoji ZWJ,
    # Regional Indicator flags, emoji modifier/keycap/tag sequences, named sequences, etc.
    seq_coll_id=coll['debug-structural']
    structural_unicode_sequences=[
      ('family-man-woman-girl-boy','emoji-zwj','FAMILY: MAN, WOMAN, GIRL, BOY',(0x1F468,0x200D,0x1F469,0x200D,0x1F467,0x200D,0x1F466),{'rendering-risk':'font-dependent'}),
      ('flag-japan','regional-indicator','FLAG: JAPAN',(0x1F1EF,0x1F1F5),{'region':'JP'}),
      ('waving-hand-light-skin-tone','emoji-modifier','WAVING HAND: LIGHT SKIN TONE',(0x1F44B,0x1F3FB),{'modifier':'light-skin-tone'}),
      ('keycap-1','emoji-keycap','KEYCAP: 1',(0x0031,0xFE0F,0x20E3),{'presentation':'emoji'}),
      ('flag-england','emoji-tag','FLAG: ENGLAND',(0x1F3F4,0xE0067,0xE0062,0xE0065,0xE006E,0xE0067,0xE007F),{'tag':'gbeng'}),
    ]
    for order,(skey,stype,name,cps,anns) in enumerate(structural_unicode_sequences,1):
        cur.execute('INSERT INTO unicode_sequence(sequence_key,sequence_type,name,source_id,notes) VALUES (?,?,?,?,?)',(skey,stype,name,custom_src,'test-only structural fixture'))
        sid=cur.lastrowid
        for i,cp in enumerate(cps):
            cur.execute('INSERT INTO unicode_sequence_member(sequence_id,seq_index,cp) VALUES (?,?,?)',(sid,i,cp))
        for k,v in anns.items():
            cur.execute('INSERT INTO unicode_sequence_annotation(sequence_id,key,value) VALUES (?,?,?)',(sid,k,v))
        # The five representative Emoji fixtures remain as regression entities,
        # but are no longer members of the UI debug Collection because Emoji 18.0
        # now provides the complete corresponding standard collections.

    # Representative scalar entries for test-only variation/revision/search fixtures.
    for order,cp in enumerate((0x8FBB,0x301C,0xFF5E,0x00A5,0x8140),1):
        if cp in assigned_set:
            cur.execute('INSERT OR IGNORE INTO collection_member_unicode(collection_id,cp,sort_order,notes) VALUES (?,?,?,?)',
                        (coll['debug-structural'],cp,100+order,'test-only structural fixture'))

    # v0.9 structural fixtures for Unicode binary properties.  Real builds load these
    # from PropList.txt / DerivedCoreProperties.txt / emoji/emoji-data.txt; these rows
    # guarantee the UI/export model remains exercised in bootstrap builds too.
    structural_properties={
      0x0020:['White_Space'],
      0x0149:['Deprecated'],
      0x200D:['Default_Ignorable_Code_Point','Join_Control'],
      0x4E00:['Ideographic','Unified_Ideograph'],
      0xFE0F:['Variation_Selector','Default_Ignorable_Code_Point'],
      0x1F600:['Emoji','Emoji_Presentation','Extended_Pictographic'],
    }
    for cp,props in structural_properties.items():
        if cur.execute('SELECT 1 FROM unicode_codepoint WHERE cp=?',(cp,)).fetchone():
            for prop in props:
                cur.execute('INSERT OR IGNORE INTO unicode_property(cp,property,value,source_id) VALUES (?,?,?,?)',(cp,prop,'Y',custom_src))

    # Rendering is deliberately not asserted by pixels. Record that an IVS requires
    # font support so UI can warn without pretending that glyph support is detectable.
    tsuji90=cur.execute('''SELECT vs.id FROM variation_sequence vs JOIN variation_collection vc ON vc.id=vs.collection_id
                          WHERE vs.base_cp=? AND vs.variation_cp=? AND vc.collection_key='adobe-japan1' ''',(0x8FBB,0xE0100)).fetchone()
    if tsuji90:
        cur.execute("INSERT OR REPLACE INTO variation_annotation(variation_id,key,value) VALUES (?, 'rendering-risk', 'font-dependent')",(tsuji90[0],))

    con.commit(); con.execute('ANALYZE'); con.commit(); con.close()
    print(DB,DB.stat().st_size)
if __name__=='__main__': main()

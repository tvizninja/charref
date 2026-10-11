(async()=>{
 const b64=document.querySelector('#dataset').textContent.trim();
 const bin=Uint8Array.from(atob(b64),c=>c.charCodeAt(0));
 const ds=new DecompressionStream('gzip');
 const text=await new Response(new Blob([bin]).stream().pipeThrough(ds)).text();
 const db=JSON.parse(text);
 const $=s=>document.querySelector(s), q=$('#q'), result=$('#result'), detail=$('#detailSection');
 const viewport=$('#listViewport'), canvas=$('#listCanvas');
 const initialParams=new URLSearchParams(location.search);
 const stateParamNames=new Set(['cp','seq','pos','set','view']);
 const preservedQueryParts=(location.search.startsWith('?')?location.search.slice(1):location.search).split('&').filter(Boolean).filter(part=>{
   const rawKey=part.split('=',1)[0];
   let key=rawKey;try{key=decodeURIComponent(rawKey.replace(/\+/g,' '))}catch{}
   return !stateParamNames.has(key);
 });
 const webFontAllowlist=new Map([
   ['Noto Sans JP',{family:'Noto Sans JP',css:'\"Noto Sans JP\",sans-serif',google:'Noto+Sans+JP'}],
   ['Noto Serif JP',{family:'Noto Serif JP',css:'\"Noto Serif JP\",serif',google:'Noto+Serif+JP'}]
 ]);
 const requestedWebFont=initialParams.get('webfont');
 let activeWebFont=null;
 if(requestedWebFont&&webFontAllowlist.has(requestedWebFont)){
   activeWebFont=webFontAllowlist.get(requestedWebFont);
   const link=document.createElement('link');link.rel='stylesheet';
   link.href=`https://fonts.googleapis.com/css2?family=${activeWebFont.google}:wght@400;700&display=swap`;
   link.dataset.charrefWebfont='1';document.head.appendChild(link);
 }
 const cpHex=cp=>'U+'+cp.toString(16).toUpperCase().padStart(4,'0');
 const hexBytes=a=>a.map(x=>x.toString(16).padStart(2,'0').toUpperCase()).join(' ');
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let selectedCp=null, selectedPositionId=null, selectedSequenceKey=null, viewMode='grid', selectedCollection=null, currentMembers=[];
 const collectionById=new Map(db.collections.map(c=>[c.id,c]));
 const collectionByKey=new Map(db.collections.map(c=>[c.collection_key,c]));
 const collectionByTypeTitle=new Map(db.collections.map(c=>[`${c.collection_type}\u0000${c.title}`,c]));
 const children=new Map();
 for(const c of db.collections){const k=c.parent_id??0;if(!children.has(k))children.set(k,[]);children.get(k).push(c)}
 for(const a of children.values())a.sort((x,y)=>(x.sort_order-y.sort_order)||x.title.localeCompare(y.title));
 const allCps=Object.values(db.characters).map(x=>x.cp).sort((a,b)=>a-b);
 const memberCache=new Map();
 const specialLabels=new Map([[0x200C,'ZWNJ'],[0x200D,'ZWJ'],[0xFE0E,'VS15'],[0xFE0F,'VS16'],[0xE007F,'CANCEL TAG']]);
 function isSurrogate(cp){return cp>=0xD800&&cp<=0xDFFF}
 function isNoncharacter(cp){return (cp>=0xFDD0&&cp<=0xFDEF)||((cp&0xFFFF)===0xFFFE)||((cp&0xFFFF)===0xFFFF)}
 function blockFor(cp){return (db.blocks||[]).find(b=>cp>=b.first_cp&&cp<=b.last_cp)?.name||'No_Block'}
 function cpRecord(cp){return db.characters[cp.toString(16).toUpperCase()]||null}
 function visibleCp(cp,d=cpRecord(cp)){
   const ch=String.fromCodePoint(cp),cat=d?.category||null;
   if(specialLabels.has(cp))return `<span class="visible-token" title="${cpHex(cp)}">${specialLabels.get(cp)}</span>`;
   if(cp>=0xE0020&&cp<=0xE007E)return `<span class="visible-token" title="${cpHex(cp)} tag character">TAG ${String.fromCharCode(cp-0xE0000)}</span>`;
   if(isSurrogate(cp))return `<span class="visible-token danger-token">SURROGATE</span>`;
   if(cat==='Cc')return `<span class="visible-token" title="control character">${cpHex(cp)}</span>`;
   if(cat==='Cf')return `<span class="visible-token" title="format/invisible character">${cpHex(cp)}</span>`;
   if(cat&&cat[0]==='M')return `◌${esc(ch)}`;
   return esc(ch);
 }
 function virtualInfo(cp){
   if(cp<0||cp>0x10FFFF)return null;
   if(isSurrogate(cp))return {status:'surrogate',name:'<surrogate>',category:'Cs',block:blockFor(cp),script:'Unknown',age:null,eaw:null,decomposition:null};
   if(isNoncharacter(cp))return {status:'noncharacter',name:'<noncharacter>',category:'Cn',block:blockFor(cp),script:'Unknown',age:null,eaw:null,decomposition:null};
   return {status:'unassigned',name:'<unassigned>',category:'Cn',block:blockFor(cp),script:'Unknown',age:null,eaw:null,decomposition:null};
 }
 function utf16(str,le){let out=[];for(const ch of str){let cp=ch.codePointAt(0),us=cp<=0xffff?[cp]:[0xd800+((cp-0x10000)>>10),0xdc00+((cp-0x10000)&1023)];for(const u of us){const hi=u>>8,lo=u&255;out.push(le?lo:hi,le?hi:lo)}}return hexBytes(out)}
 function utf32(str){return [...str].map(ch=>ch.codePointAt(0).toString(16).toUpperCase().padStart(8,'0')).join(' ')}
 function unicodeUtilUrl(cp){return `https://util.unicode.org/UnicodeJsps/character.jsp?a=${cp.toString(16).toUpperCase()}`}
 function utf32Linked(cps){return cps.map(cp=>`<a href="${unicodeUtilUrl(cp)}" target="_blank" rel="noopener noreferrer" title="Unicode Utilitiesで${cpHex(cp)}を開く">${cp.toString(16).toUpperCase().padStart(8,'0')}</a>`).join(' ')}
 function parseInput(s){
   s=s.trim();if(!s)return null;
   if(/^U\+[0-9A-Fa-f]{1,6}$/.test(s))return {kind:'codepoint',cp:parseInt(s.slice(2),16)};
   const cps=[...s].map(ch=>ch.codePointAt(0));
   return cps.length===1?{kind:'codepoint',cp:cps[0]}:{kind:'sequence',text:s,cps};
 }
 function rawHex(s){
   const x=s.trim().replace(/^0x/i,'').replace(/[ _-]/g,'');
   return /^[0-9A-Fa-f]{2,12}$/.test(x)&&x.length%2===0?x.toUpperCase():null;
 }
 function hexPositionCandidates(h){
   const spaced=h.match(/../g).join(' ');
   return Object.values(db.positions).filter(p=>p.bytes===spaced).map(p=>({kind:'position',id:p.id,label:`${p.title} ${p.position_key}`,sub:`bytes ${spaced}`}));
 }
 function searchCandidates(s){
   s=s.trim();if(!s)return [];
   if(/^U\+[0-9A-Fa-f]{1,6}$/.test(s)){const cp=parseInt(s.slice(2),16);if(cp>0x10FFFF)return [];const d=cpRecord(cp),v=d||virtualInfo(cp);return [{kind:'codepoint',cp,label:`${cpHex(cp)} ${d?.name||v?.name||''}`,sub:d?'Unicode assigned code point':v?.status}]}
   const h=rawHex(s),out=[];
   if(h&&h.length>=4&&h.length<=6){const cp=parseInt(h,16),d=cpRecord(cp),v=cp<=0x10FFFF?(d||virtualInfo(cp)):null;if(v)out.push({kind:'codepoint',cp,label:`Unicode ${cpHex(cp)} ${d?.name||v.name||''}`,sub:`16進Code Pointとして解釈${d?'':` (${v.status})`}`})}
   if(h)out.push(...hexPositionCandidates(h));
   if(out.length)return out;
   const x=parseInput(s);return x?[x]:[];
 }
 function showSearchCandidates(s,cands){
   selectedCp=null;selectedPositionId=null;detail.hidden=false;
   const rows=cands.map((c,i)=>`<button class="search-candidate" data-i="${i}"><b>${esc(c.label||'候補')}</b>${c.sub?`<span>${esc(c.sub)}</span>`:''}</button>`).join('');
   result.innerHTML=`<h2>検索候補 <span class="muted">${esc(s)}</span></h2><div class="warn compact">入力を複数の方法で解釈できます。候補を選択してください。</div><div class="search-candidates">${rows}</div>`;
   result.querySelectorAll('.search-candidate').forEach(e=>e.onclick=()=>{const c=cands[+e.dataset.i];if(c.kind==='position')showPosition(c.id);else if(c.kind==='codepoint'){q.value=String.fromCodePoint(c.cp);show(c.cp)}else if(c.kind==='sequence')showSequence(c.text,c.cps)});
 }

 function sequenceKey(cps){return cps.map(cp=>cp.toString(16).toUpperCase()).join('-')}
 function normInfo(text,form){const v=text.normalize(form),cps=[...v].map(ch=>cpHex(ch.codePointAt(0))).join(' ');return {value:v,cps}}
 function exactSequenceEncoding(cps,key){
   const seq=db.sequences?.[sequenceKey(cps)];if(!seq)return null;
   const vals=(seq.mappings||[]).filter(m=>m.system_key===key&&(m.direction==='encode'||m.direction==='both')).map(m=>m.bytes);
   return vals.length?{value:[...new Set(vals)].join(' / '),exact:true}:null;
 }
 function concatEncoding(cps,key){
   const exact=exactSequenceEncoding(cps,key);if(exact)return exact;
   const parts=[];
   for(const cp of cps){const d=db.characters[cp.toString(16).toUpperCase()],vals=d?.encodings?.[key]||[];if(vals.length!==1)return {value:'表現不可 / 複数対応',exact:false};parts.push(vals[0])}
   return {value:parts.join(' '),exact:false};
 }
 const fontComparePresets=[
   ...(activeWebFont?[[`Web: ${activeWebFont.family}`,activeWebFont.css]]:[]),
   ['System UI','system-ui'],
   ['Sans-serif','sans-serif'],
   ['Serif','serif'],
   ['Monospace','monospace'],
   ['Yu Gothic','"Yu Gothic","YuGothic",sans-serif'],
   ['Yu Mincho','"Yu Mincho","YuMincho",serif'],
   ['Meiryo','Meiryo,sans-serif'],
   ['MS Gothic','"MS Gothic",monospace'],
   ['MS Mincho','"MS Mincho",serif'],
   ['Hiragino Kaku Gothic','"Hiragino Kaku Gothic ProN","Hiragino Sans",sans-serif'],
   ['Hiragino Mincho','"Hiragino Mincho ProN",serif'],
   ['Noto Sans CJK JP','"Noto Sans CJK JP","Noto Sans JP",sans-serif'],
   ['Noto Serif CJK JP','"Noto Serif CJK JP","Noto Serif JP",serif'],
   ['IPAex Gothic','"IPAexGothic","IPAex Gothic",sans-serif'],
   ['IPAex Mincho','"IPAexMincho","IPAex Mincho",serif']
 ];
 function fontCompareHtml(text,label='フォントによって表示が異なる場合があります'){
   const samples=fontComparePresets.map(([name,family])=>`<div class="font-sample"><div class="font-name">${esc(name)}</div><div class="font-glyph" style="font-family:${esc(family)}">${esc(text)}</div></div>`).join('');
   return `<details class="font-compare"><summary>${esc(label)} <span class="summary-meta">代表フォントで比較</span></summary><div class="font-compare-body"><p class="muted small">同じ文字列を代表的なCSSフォント指定で描画します。フォントが端末にない場合はブラウザがフォールバックするため、表示名のフォントが実際に使用された保証はありません。ここでは見え方の比較のみを行い、未表示・字形差の原因解析は行いません。</p><div class="font-sample-grid">${samples}</div></div></details>`;
 }
 function showSequence(text,cps,update=true){
   selectedCp=null;selectedPositionId=null;selectedSequenceKey=sequenceKey(cps);detail.hidden=false;
   const seq=db.sequences?.[sequenceKey(cps)];
   const rows=cps.map((cp,i)=>{const d=cpRecord(cp),v=d||virtualInfo(cp);return `<tr><td>${i+1}</td><td class="glyph mini member" data-cp="${cp}">${visibleCp(cp,d)}</td><td class="cp">${cpHex(cp)}</td><td>${esc(d?.name||v?.name||'未登録')}</td><td>${esc(d?.age||'—')}</td><td class="cp">${esc(d?firstEncoding(d,'cp932'):'—')}</td></tr>`}).join('');
   const norms={NFC:normInfo(text,'NFC'),NFD:normInfo(text,'NFD'),NFKC:normInfo(text,'NFKC'),NFKD:normInfo(text,'NFKD')};
   const keys=[['CP932','cp932'],['Shift_JIS','shift_jis'],['Shift_JIS-2004','shift_jis_2004'],['EUC-JP','euc_jp'],['EUC-JIS-2004','euc_jis_2004'],['ISO-2022-JP','iso2022_jp'],['ISO-2022-JP-2004','iso2022_jp_2004']];
   const results=keys.map(([label,key])=>[label,concatEncoding(cps,key)]);
   const unicodeRows=`<tr><th>UTF-32</th><td class="cp">${utf32Linked(cps)}</td></tr><tr><th>UTF-16BE</th><td class="cp">${esc(utf16(text,false))}</td></tr><tr><th>UTF-16LE</th><td class="cp">${esc(utf16(text,true))}</td></tr><tr><th>UTF-8</th><td class="cp">${esc(hexBytes([...new TextEncoder().encode(text)]))}</td></tr>`;
   const encRows=unicodeRows+results.map(([a,b])=>`<tr><th>${a}</th><td class="cp">${esc(b.value)}${b.exact?' <span class="exact-badge">DB exact</span>':''}</td></tr>`).join('');
   const ivs=(seq?.variations||[]).map(v=>`<div class="warn compact"><b>IVS</b> ${esc(v.collection_title||v.collection_key)} ${esc(v.label||'')}<br><span class="cp">${cps.map(cpHex).join(' ')}</span><div class="ivs-compare"><span><small>Base</small><b>${esc(String.fromCodePoint(cps[0]))}</b></span><span><small>IVS</small><b>${esc(text)}</b></span></div>${fontCompareHtml(text,'表示字形はフォントに依存します')}</div>`).join('');
   const exactCount=results.filter(x=>x[1].exact).length;
   const entities=(seq?.entities||[]).map(e=>`<div class="sequence-meta"><b>${esc(e.name||e.sequence_key)}</b> <span class="sequence-type">${esc(e.sequence_type)}</span>${Object.entries(e.annotations||{}).map(([k,v])=>`<div><span class="muted small">${esc(k)}:</span> ${esc(v)}</div>`).join('')}</div>`).join('');
   const entityCard=entities?`<div class="card"><h3>Unicode Sequence</h3>${entities}<p class="muted small">複数Code Pointからなるシーケンスを、Encoding mappingやIVSとは独立したエンティティとして保持しています。</p></div>`:'';
   const stdPositions=(seq?.mappings||[]).filter(m=>m.system_type==='standard-position').map(m=>`<div><span class="jis-pos">${esc(m.title)} ${esc(m.position_key)}</span> <span class="muted small">${esc(m.kind||'')}</span></div>`).join('');
   const stdCard=stdPositions?`<div class="card"><h3>規格上の位置</h3>${stdPositions}<p class="muted small">同一Unicode sequenceが複数の規格位置に対応する場合も、すべて表示します。</p></div>`:'';
   result.innerHTML=`<div class="glyph">${esc(text)}</div><h2>文字列解析 <span class="muted">${cps.length} Code Points</span></h2>${ivs}<div class="cards">${entityCard}<div class="card"><h3>Code Points</h3><table><tr><th>#</th><th>文字</th><th>Unicode</th><th>Name</th><th>Age</th><th>CP932</th></tr>${rows}</table></div><div class="card"><h3>文字列Encoding</h3><table>${encRows}</table><p class="muted small">DBにsequence mappingがある場合はそれを優先します（${exactCount}件）。ない場合のみ単一Code Point mappingを連結した参考値です。</p></div>${stdCard}<div class="card"><h3>Normalization</h3>${Object.entries(norms).map(([form,n])=>`<div><b>${form}:</b> <span class="cp">${esc(n.value)}</span> <span class="muted small">${esc(n.cps)}</span></div>`).join('')}${norms.NFKC.value!==text?`<div class="warn compact">NFKCでは「${esc(text)}」→「${esc(norms.NFKC.value)}」になります。</div>`:''}</div></div>`;
   result.querySelectorAll('[data-cp]').forEach(e=>e.onclick=()=>{const cp=+e.dataset.cp;q.value=String.fromCodePoint(cp);show(cp)});
   renderList();if(update)updateUrl();
 }
 function valueList(d,key){return (d.encodings[key]||[]).join(' / ')||'表現不可'}
 function jisLabel(p){if(p.system_key==='jis_x_0201_kana')return `${p.title} ${p.position_key}`;if(p.plane)return `${p.title} ${p.plane}面-${p.row}区-${p.cell}点`;if(p.row)return `${p.title} ${p.row}区-${p.cell}点`;return `${p.title} ${p.position_key}`}
 function compactJis(d){return (d.jis_positions||[]).slice(0,2).map(jisLabel).join(' / ')||'—'}
 function firstEncoding(d,key){return (d.encodings[key]||[])[0]||'—'}
 function updateUrl(){
   const state=new URLSearchParams();
   if(selectedCp!==null)state.set('cp',selectedCp.toString(16).toUpperCase());
   if(selectedSequenceKey)state.set('seq',selectedSequenceKey);
   if(selectedPositionId!==null)state.set('pos',String(selectedPositionId));
   if(selectedCollection)state.set('set',selectedCollection.collection_key);
   if(viewMode!=='grid')state.set('view',viewMode);
   const stateQs=state.toString(),parts=[...preservedQueryParts];if(stateQs)parts.push(stateQs);
   const qs=parts.join('&');history.replaceState(null,'',location.pathname+(qs?'?'+qs:'')+location.hash)
 }
 function showVirtualCodepoint(cp,update=true){
   const v=virtualInfo(cp);if(!v)return;selectedCp=cp;selectedPositionId=null;selectedSequenceKey=null;detail.hidden=false;
   let warn='',utf8='—',u16le='—',u16be='—',u32=cp.toString(16).toUpperCase().padStart(8,'0');
   if(v.status==='surrogate'){warn='<div class="warn"><b>Surrogate code point</b>：Unicode scalar valueではありません。UTF-8へ単独では符号化できず、UTF-16ではサロゲートコード単位としてのみ意味を持ちます。</div>';const u=cp,hi=(u>>8)&255,lo=u&255;u16le=hexBytes([lo,hi]);u16be=hexBytes([hi,lo]);}
   else {const ch=String.fromCodePoint(cp);utf8=hexBytes([...new TextEncoder().encode(ch)]);u16le=utf16(ch,true);u16be=utf16(ch,false);warn=v.status==='noncharacter'?'<div class="warn"><b>Unicode noncharacter</b>：Unicode scalar valueですが、公開交換用の抽象文字として割り当てられることはありません。</div>':'<div class="warn compact"><b>未割当Code Point</b>：現在のUnicodeデータセットでは文字が割り当てられていません。</div>'}
   result.innerHTML=`<div class="glyph">${visibleCp(cp,null)}</div><h2>${cpHex(cp)} ${esc(v.name)}</h2>${warn}<div class="cards"><div class="card"><h3>Unicode</h3><div><b>Status:</b> ${esc(v.status)}</div><div>General Category: ${esc(v.category)}</div><div>Block: ${esc(v.block)}</div><div>Script: ${esc(v.script)}</div><div>Introduced: —</div></div><div class="card"><h3>Encoding</h3><table><tr><th>UTF-32</th><td class="cp"><a href="${unicodeUtilUrl(cp)}" target="_blank" rel="noopener noreferrer" title="Unicode Utilitiesで${cpHex(cp)}を開く">${esc(u32)}</a></td></tr><tr><th>UTF-16BE</th><td class="cp">${esc(u16be)}</td></tr><tr><th>UTF-16LE</th><td class="cp">${esc(u16le)}</td></tr><tr><th>UTF-8</th><td class="cp">${esc(utf8)}</td></tr><tr><th>Legacy encodings</th><td>表現対象外 / mappingなし</td></tr></table></div></div>`;
   renderList();if(update)updateUrl();
 }
 function show(cp,update=true){
   const d=cpRecord(cp);
   if(!d){showVirtualCodepoint(cp,update);return}
   selectedCp=cp;selectedPositionId=null;selectedSequenceKey=null;detail.hidden=false;const ch=String.fromCodePoint(cp);
   const issue=d.issues.map(i=>`<div class="warn"><b>${esc(i.title)}</b><br>${esc(i.description)}</div>`).join('');
   const renderWarn=d.category==='Co'?'<div class="warn compact"><b>Private Use</b>：意味・字形は環境や合意に依存します。</div>':(d.category==='Cc'||d.category==='Cf'?'<div class="warn compact"><b>非表示/制御系文字</b>：実際の文字は不可視または表示制御として働くため、UIでは可視トークンを併記します。</div>':(d.category?.startsWith('M')?'<div class="warn compact"><b>結合文字</b>：単独表示は不安定なため、一覧では点線の丸 ◌ と組み合わせて可視化します。</div>':''));
   const sameEncoding=(a,b)=>JSON.stringify(d.encodings[a]||[])===JSON.stringify(d.encodings[b]||[]);
   const legacyEncRows=[['CP932',valueList(d,'cp932')],['Shift_JIS (JIS X 0208系)',valueList(d,'shift_jis')],...(!sameEncoding('shift_jis','shift_jis_2004')?[['Shift_JIS-2004',valueList(d,'shift_jis_2004')]]:[]),['EUC-JP',valueList(d,'euc_jp')],...(!sameEncoding('euc_jp','euc_jis_2004')?[['EUC-JIS-2004',valueList(d,'euc_jis_2004')]]:[]),['ISO-2022-JP',valueList(d,'iso2022_jp')],...(!sameEncoding('iso2022_jp','iso2022_jp_2004')?[['ISO-2022-JP-2004',valueList(d,'iso2022_jp_2004')]]:[])].map(([a,b])=>`<tr><th>${a}</th><td class="cp">${esc(b)}</td></tr>`).join('');
   const encRows=`<tr><th>UTF-32</th><td class="cp"><a href="${unicodeUtilUrl(cp)}" target="_blank" rel="noopener noreferrer" title="Unicode Utilitiesで${cpHex(cp)}を開く">${esc(utf32(ch))}</a></td></tr><tr><th>UTF-16BE</th><td class="cp">${esc(utf16(ch,false))}</td></tr><tr><th>UTF-16LE</th><td class="cp">${esc(utf16(ch,true))}</td></tr><tr><th>UTF-8</th><td class="cp">${esc(hexBytes([...new TextEncoder().encode(ch)]))}</td></tr>`+legacyEncRows;
   const jisPositions=d.jis_positions||[], jis=jisPositions.map(p=>`<span class="jis-pos">${esc(jisLabel(p))}</span>`).join('')||'<span class="muted">該当なし</span>';
   const jis0213Only=jisPositions.some(p=>p.system_key==='jis_x_0213_2004')&&!(d.encodings.shift_jis||[]).length;
   const jisNote=jis0213Only?'<div class="warn compact">JIS X 0213:2004には収録されていますが、従来Shift_JISとは別です。Shift_JIS-2004等の欄を確認してください。</div>':'';
   const rel=d.relations.map(r=>`<span class="member" data-cp="${r.cp}">${String.fromCodePoint(r.cp)} ${cpHex(r.cp)} (${esc(r.type)})</span>`).join('')||'—';
   const debugMode=selectedCollection?.collection_key==='debug-structural';
   const visibleVariations=(d.variations||[]).filter(v=>debugMode||!v.collection_key.startsWith('test-'));
   const vs=visibleVariations.map(v=>`<div><span class="glyph mini">${ch}${String.fromCodePoint(v.variation_cp)}</span> <span class="cp">${cpHex(cp)} ${cpHex(v.variation_cp)}</span> ${esc(v.label||'')} <span class="muted">${esc(v.collection_key)}</span></div>`).join('')||'—';
   const exceptional=(d.mapping_details||[]).filter(m=>(debugMode||!m.system_key.startsWith('test_'))&&(m.direction!=='both'||m.kind!=='standard'||(debugMode&&m.system_key.startsWith('test_'))));
   const hasNonRoundtrip=exceptional.some(m=>m.kind==='non-roundtrip'||m.kind==='roundtrip-mismatch'||m.direction==='encode'||m.direction==='decode');
   const mappingDetail=exceptional.length?`<div class="card mapping-card"><details><summary><span>Mapping詳細</span><span class="summary-meta">${exceptional.length}件${hasNonRoundtrip?' · 要確認':''}</span></summary><div class="mapping-body"><table><tr><th>System</th><th>Position/Bytes</th><th>Direction</th><th>Kind</th><th>Priority</th></tr>${exceptional.map(m=>`<tr><td>${esc(m.title||m.system_key)}</td><td class="cp">${esc(m.bytes||m.position_key)}</td><td>${esc(m.direction)}</td><td>${esc(m.kind)}</td><td>${m.priority}</td></tr>`).join('')}</table><p class="muted small">複数候補・片方向mapping等は潰さず個別に保持します。</p></div></details></div>`:'';
   const propertyEntries=Object.entries(d.properties||{}).sort((a,b)=>a[0].localeCompare(b[0]));
   const memberships=(d.memberships||[]).filter(m=>debugMode||m.key!=='debug-structural');
   const membershipCard=memberships.length?`<div class="card"><h3>所属Collection</h3><div class="property-badges">${memberships.map(m=>{const c=collectionByKey.get(m.key);return c?`<button class="property-link" data-collection-id="${c.id}">${esc(m.title)}</button>`:`<span class="property-badge">${esc(m.title)}</span>`}).join('')}</div></div>`:'';
   const propertyCard=propertyEntries.length?`<div class="card"><h3>Unicode Properties</h3><div class="property-badges">${propertyEntries.map(([k,v])=>`<span class="property-badge" title="${esc(v.join(', '))}">${esc(k)}${v.some(x=>x!=='Y')?`: ${esc(v.join(' / '))}`:''}</span>`).join('')}</div><p class="muted small">PropList / DerivedCoreProperties / emoji-data 等の汎用Property。詳細UIは後で整理予定です。</p></div>`:'';
   const blockCollection=collectionByTypeTitle.get(`unicode-block\u0000${d.block}`);
   const scriptCollection=collectionByTypeTitle.get(`unicode-script\u0000${d.script}`);
   const blockValue=blockCollection?`<button class="property-link" data-collection-id="${blockCollection.id}" title="このBlockの文字一覧を表示">${esc(d.block)}</button>`:esc(d.block||'—');
   const scriptValue=scriptCollection?`<button class="property-link" data-collection-id="${scriptCollection.id}" title="このScriptの文字一覧を表示">${esc(d.script)}</button>`:esc(d.script||'—');
   result.innerHTML=`<div class="glyph">${visibleCp(cp,d)}</div><h2>${cpHex(cp)} ${esc(d.name||'')}</h2>${issue}${renderWarn}<div class="cards"><div class="card"><h3>Unicode</h3><div><b>Introduced:</b> Unicode ${esc(d.age||'—')}</div><div>General Category: ${esc(d.category||'—')}</div><div>East Asian Width: ${esc(d.eaw||'—')}</div><div>Block: ${blockValue}</div><div>Script: ${scriptValue}</div><div>Decomposition: <span class="cp">${esc(d.decomposition||'—')}</span></div><div class="muted small">データ基準: Unicode ${esc(db.meta.unicode_target||'—')} / ${esc(db.meta.dataset_kind||'—')}</div></div><div class="card"><h3>Encoding</h3><table>${encRows}</table><div class="jis-line"><b>JIS位置</b>${jis}</div>${jisNote}</div><div class="card"><h3>関連文字</h3>${rel}</div><div class="card"><h3>Variation Sequences</h3>${vs}${fontCompareHtml(ch,'フォントによって表示が異なる場合があります')}</div>${membershipCard}${propertyCard}${mappingDetail}</div>`;
   result.querySelectorAll('[data-cp]').forEach(e=>e.onclick=()=>show(+e.dataset.cp));
   result.querySelectorAll('[data-collection-id]').forEach(e=>e.onclick=()=>selectCollection(collectionById.get(+e.dataset.collectionId),true,true));
   renderList();if(update)updateUrl();
 }
 function positionGlyph(p){
   const maps=(p.mappings||[]).filter(m=>m.unicode?.length);
   if(!maps.length)return '<span class="fallback-glyph" title="Unicode対応なし">□</span>';
   const cps=maps[0].unicode;return cps.map(cp=>String.fromCodePoint(cp)).join('');
 }
 function showPosition(id,update=true){
   const p=db.positions?.[String(id)];if(!p)return;
   selectedCp=null;selectedPositionId=id;selectedSequenceKey=null;detail.hidden=false;
   const maps=(p.mappings||[]).map(m=>`<tr><td>${esc(m.direction)}</td><td>${esc(m.kind)}</td><td>${m.priority}</td><td class="cp">${(m.unicode||[]).map(cpHex).join(' ')||'—'}</td><td>${(m.unicode||[]).map(cp=>`<button class="property-link" data-cp="${cp}">${esc(String.fromCodePoint(cp))}</button>`).join(' ')||'<span class="warn-inline">Unicode対応なし</span>'}</td></tr>`).join('');
   const dec=new Set((p.mappings||[]).filter(m=>m.direction==='decode'||m.direction==='both').map(m=>(m.unicode||[]).join('-'))),enc=new Set((p.mappings||[]).filter(m=>m.direction==='encode'||m.direction==='both').map(m=>(m.unicode||[]).join('-')));
   const roundtripWarn=dec.size&&enc.size&&![...dec].some(x=>enc.has(x))?'<div class="warn compact"><b>Non-roundtrip mapping</b>：decode と encode のUnicode対応が一致しません。</div>':'';
   const loc=p.plane?`${p.plane}面-${p.row}区-${p.cell}点`:(p.row?`${p.row}区-${p.cell}点`:p.position_key);
   result.innerHTML=`<div class="glyph">${positionGlyph(p)}</div><h2>${esc(p.title)} ${esc(loc)}</h2>${!(p.mappings||[]).length?'<div class="warn">このコード位置にはUnicode mappingがありません。黄色背景の□はアプリによる代替表示です。</div>':''}<div class="cards"><div class="card"><h3>Code position</h3><div>System: ${esc(p.title)}</div><div>Position: <span class="cp">${esc(p.position_key)}</span></div><div>Bytes: <span class="cp">${esc(p.bytes||'—')}</span></div><div class="muted small">${esc(p.notes||'')}</div></div><div class="card mapping-card"><h3>Mappings</h3>${roundtripWarn}<details><summary><span>Mapping詳細</span><span class="summary-meta">${(p.mappings||[]).length}件${roundtripWarn?' · Non-roundtrip':''}</span></summary><div class="mapping-body"><table><tr><th>Direction</th><th>Kind</th><th>Priority</th><th>Unicode</th><th>表示</th></tr>${maps||'<tr><td colspan="5">なし</td></tr>'}</table></div></details></div></div>`;
   result.querySelectorAll('[data-cp]').forEach(e=>e.onclick=()=>{const cp=+e.dataset.cp;q.value=String.fromCodePoint(cp);show(cp)});
   renderList();if(update)updateUrl();
 }
 function descendants(c){const out=[];const walk=id=>{for(const ch of children.get(id)||[]){out.push(ch);walk(ch.id)}};walk(c.id);return out}
 function membersFor(c){
   if(memberCache.has(c.id))return memberCache.get(c.id);
   let arr;
   const isJis=(()=>{let x=c;while(x){if(x.collection_key==='jis')return true;x=x.parent_id?collectionById.get(x.parent_id):null}return false})();
   if(c.collection_key==='unicode')arr=allCps;
   else if(isJis){
     const pos=new Set((c.positions||[]).map(id=>'p:'+id));for(const d of descendants(c))for(const id of d.positions||[])pos.add('p:'+id);
     if(pos.size)arr=[...pos];else if(c.sequences?.length)arr=(c.sequences||[]).map(k=>'s:'+k);else arr=(c.members||[]).slice();
   }
   else if(c.positions?.length||c.sequences?.length){arr=[...(c.members||[]),...(c.positions||[]).map(id=>'p:'+id),...(c.sequences||[]).map(k=>'s:'+k)]}
   else if(c.members?.length)arr=c.members.slice();
   else{const set=new Set();for(const d of descendants(c)){for(const cp of d.members||[])set.add(cp);for(const id of d.positions||[])set.add('p:'+id);for(const k of d.sequences||[])set.add('s:'+k)}arr=[...set];arr.sort((a,b)=>typeof a===typeof b?(a<b?-1:a>b?1:0):(typeof a==='number'?-1:1))}
   memberCache.set(c.id,arr);return arr;
 }
 function treeRows(filter=''){
   const needle=filter.trim().toLocaleLowerCase();const rows=[];
   function hasMatch(c){if(!needle)return true;if(c.title.toLocaleLowerCase().includes(needle)||c.collection_key.toLocaleLowerCase().includes(needle))return true;return (children.get(c.id)||[]).some(hasMatch)}
   function walk(pid,depth){for(const c of children.get(pid)||[]){if(!hasMatch(c))continue;rows.push({c,depth});walk(c.id,depth+1)}}walk(0,0);return rows;
 }
 function renderCollectionOptions(filter=''){
   const box=$('#collectionOptions');const rows=treeRows(filter);box.innerHTML=rows.map(({c,depth})=>{const count=membersFor(c).length;return `<button class="collection-option${selectedCollection?.id===c.id?' selected':''}" data-id="${c.id}" style="padding-left:${.5+depth*1.05}rem" role="option"><span>${esc(c.title)}</span><span class="count">${count.toLocaleString()}</span></button>`}).join('')||'<div class="empty-list">該当する集合がありません</div>';
   box.querySelectorAll('[data-id]').forEach(e=>e.onclick=()=>{selectCollection(collectionById.get(+e.dataset.id));closePicker()});
 }
 function openPicker(){const p=$('#collectionPanel');p.hidden=false;$('#collectionButton').setAttribute('aria-expanded','true');renderCollectionOptions($('#collectionFilter').value);setTimeout(()=>$('#collectionFilter').focus(),0)}
 function closePicker(){$('#collectionPanel').hidden=true;$('#collectionButton').setAttribute('aria-expanded','false')}
 function revealSelectedInList(){
   const target=selectedPositionId!==null?'p:'+selectedPositionId:(selectedSequenceKey?'s:'+selectedSequenceKey:selectedCp);if(target===null)return;const idx=currentMembers.indexOf(target);if(idx<0)return;
   if(viewMode==='grid'){const w=viewport.clientWidth||800,cols=Math.max(1,Math.floor(w/86)),row=Math.floor(idx/cols);viewport.scrollTop=Math.max(0,row*64-viewport.clientHeight*.35)}
   else viewport.scrollTop=Math.max(0,38+idx*42-viewport.clientHeight*.35);
 }
 function selectCollection(c,update=true,reveal=false){selectedCollection=c;currentMembers=membersFor(c);$('#collectionButton').textContent=breadcrumb(c);$('#collectionTitle').textContent=c.title;$('#collectionCount').textContent=`${currentMembers.length.toLocaleString()}項目`;viewport.scrollTop=0;if(reveal)revealSelectedInList();renderList();renderCollectionOptions($('#collectionFilter').value);if(update)updateUrl()}
 function breadcrumb(c){const a=[c.title];let p=c.parent_id?collectionById.get(c.parent_id):null;while(p){a.unshift(p.title);p=p.parent_id?collectionById.get(p.parent_id):null}return a.join(' › ')}
 function renderList(){
   if(!selectedCollection)return;const n=currentMembers.length,w=viewport.clientWidth||800,top=viewport.scrollTop;
   if(viewMode==='grid'){
     const cellW=86,rowH=64,cols=Math.max(1,Math.floor(w/cellW)),rows=Math.ceil(n/cols),startRow=Math.max(0,Math.floor(top/rowH)-3),endRow=Math.min(rows,Math.ceil((top+viewport.clientHeight)/rowH)+3),start=startRow*cols,end=Math.min(n,endRow*cols),actualW=w/cols;
     canvas.className='list-canvas';canvas.style.height=(rows*rowH)+'px';let html='';for(let i=start;i<end;i++){const item=currentMembers[i],col=i%cols,row=Math.floor(i/cols);if(typeof item==='string'&&item.startsWith('p:')){const id=+item.slice(2),p=db.positions[String(id)];if(!p)continue;html+=`<div class="grid-cell position-cell${selectedPositionId===id?' selected':''}" data-pos="${id}" style="left:${col*actualW}px;top:${row*rowH}px;width:${actualW}px"><div class="grid-char">${positionGlyph(p)}</div><div class="grid-cp">${esc(p.position_key)}</div></div>`}else if(typeof item==='string'&&item.startsWith('s:')){const key=item.slice(2),seq=db.sequences[key];if(!seq)continue;const text=String.fromCodePoint(...seq.cps),ent=seq.entities?.[0];html+=`<div class="grid-cell sequence-cell${selectedSequenceKey===key?' selected':''}" data-seq="${esc(key)}" style="left:${col*actualW}px;top:${row*rowH}px;width:${actualW}px"><div class="grid-char">${esc(text)}</div><div class="grid-cp">${esc(ent?.sequence_type||'sequence')}</div></div>`}else{const cp=item,d=cpRecord(cp);if(!d)continue;html+=`<div class="grid-cell${selectedCp===cp?' selected':''}" data-cp="${cp}" style="left:${col*actualW}px;top:${row*rowH}px;width:${actualW}px"><div class="grid-char">${visibleCp(cp,d)}</div><div class="grid-cp">${cpHex(cp)}</div></div>`}}canvas.innerHTML=html;
   }else{
     const headH=38,rowH=42,start=Math.max(0,Math.floor(Math.max(0,top-headH)/rowH)-5),end=Math.min(n,Math.ceil((top+viewport.clientHeight-headH)/rowH)+5);canvas.className='list-canvas';canvas.style.height=(headH+n*rowH)+'px';let rows='';for(let i=start;i<end;i++){const item=currentMembers[i];if(typeof item==='string'&&item.startsWith('p:')){const id=+item.slice(2),p=db.positions[String(id)];if(!p)continue;const unicode=(p.mappings||[]).flatMap(m=>m.unicode||[]).map(cpHex).join(' / ')||'Unicode対応なし';rows+=`<div class="table-row${selectedPositionId===id?' selected':''}" data-pos="${id}" style="top:${i*rowH}px"><div class="table-char">${positionGlyph(p)}</div><div class="cp">${esc(p.position_key)}</div><div title="${esc(p.title)}">${esc(p.title)}</div><div>—</div><div class="table-jis" title="${esc(unicode)}">${esc(unicode)}</div><div class="table-cp932 cp">${esc(p.bytes||'—')}</div></div>`}else if(typeof item==='string'&&item.startsWith('s:')){const key=item.slice(2),seq=db.sequences[key];if(!seq)continue;const ent=seq.entities?.[0],text=String.fromCodePoint(...seq.cps),cps=seq.cps.map(cpHex).join(' ');rows+=`<div class="table-row${selectedSequenceKey===key?' selected':''}" data-seq="${esc(key)}" style="top:${i*rowH}px"><div class="table-char">${esc(text)}</div><div class="cp">${esc(cps)}</div><div title="${esc(ent?.name||'')}">${esc(ent?.name||'Unicode sequence')}</div><div>—</div><div class="table-jis">${esc(ent?.sequence_type||'sequence')}</div><div class="table-cp932 cp">${esc(exactSequenceEncoding(seq.cps,'cp932')?.value||'—')}</div></div>`}else{const cp=item,d=cpRecord(cp);if(!d)continue;rows+=`<div class="table-row${selectedCp===cp?' selected':''}" data-cp="${cp}" style="top:${i*rowH}px"><div class="table-char">${visibleCp(cp,d)}</div><div class="cp">${cpHex(cp)}</div><div title="${esc(d.name||'')}">${esc(d.name||'')}</div><div>${esc(d.age||'—')}</div><div class="table-jis" title="${esc(compactJis(d))}">${esc(compactJis(d))}</div><div class="table-cp932 cp">${esc(firstEncoding(d,'cp932'))}</div></div>`}}canvas.innerHTML=`<div class="table-head"><div>文字</div><div>Unicode</div><div>Name</div><div>Age</div><div class="table-jis">JIS</div><div class="table-cp932">CP932</div></div><div class="table-body">${rows}</div>`;
   }
   canvas.querySelectorAll('[data-cp]').forEach(e=>e.onclick=()=>{const cp=+e.dataset.cp;q.value=String.fromCodePoint(cp);show(cp)});canvas.querySelectorAll('[data-pos]').forEach(e=>e.onclick=()=>showPosition(+e.dataset.pos));canvas.querySelectorAll('[data-seq]').forEach(e=>e.onclick=()=>{const key=e.dataset.seq,seq=db.sequences[key];if(seq){const t=String.fromCodePoint(...seq.cps);q.value=t;showSequence(t,seq.cps)}});
 }
 function listAnchor(){
   const n=currentMembers.length;if(!n)return {index:0,offset:0};
   const top=viewport.scrollTop,w=viewport.clientWidth||800;
   if(viewMode==='grid'){const cellW=86,rowH=64,cols=Math.max(1,Math.floor(w/cellW)),row=Math.max(0,Math.floor(top/rowH));return {index:Math.min(n-1,row*cols),offset:top-row*rowH}}
   const headH=38,rowH=42,row=Math.max(0,Math.floor(Math.max(0,top-headH)/rowH));return {index:Math.min(n-1,row),offset:Math.max(0,top-headH-row*rowH)}
 }
 function restoreListAnchor(anchor){
   const n=currentMembers.length;if(!n){viewport.scrollTop=0;return}
   const idx=Math.max(0,Math.min(n-1,anchor.index)),w=viewport.clientWidth||800;
   if(viewMode==='grid'){const cellW=86,rowH=64,cols=Math.max(1,Math.floor(w/cellW)),row=Math.floor(idx/cols);viewport.scrollTop=row*rowH+Math.min(anchor.offset,rowH-1)}
   else {const headH=38,rowH=42;viewport.scrollTop=headH+idx*rowH+Math.min(anchor.offset,rowH-1)}
 }
 function setView(mode,update=true){
   if(mode===viewMode){$('#gridMode').classList.toggle('active',mode==='grid');$('#tableMode').classList.toggle('active',mode==='table');renderList();if(update)updateUrl();return}
   const anchor=listAnchor();viewMode=mode;$('#gridMode').classList.toggle('active',mode==='grid');$('#tableMode').classList.toggle('active',mode==='table');renderList();restoreListAnchor(anchor);renderList();if(update)updateUrl()
 }
 function go(){const cs=searchCandidates(q.value);if(!cs.length){detail.hidden=false;result.innerHTML='<div class="warn">該当する候補がありません。</div>';return}if(cs.length>1){showSearchCandidates(q.value,cs);return}const x=cs[0];if(x.kind==='position')showPosition(x.id);else if(x.kind==='sequence')showSequence(x.text,x.cps);else show(x.cp)}
 $('#go').onclick=go;q.onkeydown=e=>{if(e.key==='Enter')go()};
 $('#collectionButton').onclick=e=>{e.stopPropagation();$('#collectionPanel').hidden?openPicker():closePicker()};
 $('#collectionFilter').oninput=e=>renderCollectionOptions(e.target.value);
 $('#collectionPanel').onclick=e=>e.stopPropagation();document.addEventListener('click',closePicker);document.addEventListener('keydown',e=>{if(e.key==='Escape')closePicker()});
 $('#gridMode').onclick=()=>setView('grid');$('#tableMode').onclick=()=>setView('table');viewport.addEventListener('scroll',renderList,{passive:true});new ResizeObserver(renderList).observe(viewport);
 const notices=[];
 const boot=(db.meta.dataset_kind||'').startsWith('bootstrap');if(boot)notices.push(`<div class="warn compact"><b>検証用データセット</b>：このHTMLはビルドパイプライン検証用のUnicode ${esc(db.meta.unicode_target||'')}データです。releaseビルドではUnicode 18.0公式取得データへ置換します。</div>`);
 if(requestedWebFont){
   if(activeWebFont)notices.push(`<div class="warn compact"><b>External WebFont</b>：Google Fontsから ${esc(activeWebFont.family)} を読み込み、フォント比較欄へ追加します。ネットワークが使えない場合はフォールバックします。</div>`);
   else notices.push(`<div class="warn compact"><b>Unknown webfont</b>：${esc(requestedWebFont)} は許可リスト外です。現在は Noto Sans JP / Noto Serif JP のみ指定できます。</div>`);
 }
 if(notices.length)$('#datasetNotice').innerHTML=notices.join('');
 const params=initialParams,key=params.get('set')||'unicode',initial=collectionByKey.get(key)||collectionByKey.get('unicode')||db.collections[0];selectCollection(initial,false);setView(params.get('view')==='table'?'table':'grid',false);const seqp=params.get('seq'),posp=params.get('pos'),p=params.get('cp');if(seqp&&db.sequences[seqp]){const seq=db.sequences[seqp],t=String.fromCodePoint(...seq.cps);q.value=t;showSequence(t,seq.cps,false)}else if(posp&&db.positions[posp]){showPosition(+posp,false)}else if(p){const cp=parseInt(p,16);if(cp<=0x10FFFF){q.value=isSurrogate(cp)?cpHex(cp):String.fromCodePoint(cp);show(cp,false)}}updateUrl();
})();

#!/usr/bin/env python3
"""Fetch authoritative upstream data for a CharRef build.

This script is intended to run in the normal connected build environment.
The distributed HTML never performs network access.
"""
from pathlib import Path
from urllib.request import urlopen, Request
import hashlib, json, time

ROOT=Path(__file__).resolve().parents[1]
UVER='18.0.0'
MANIFEST={
 'unicode/UnicodeData.txt': f'https://www.unicode.org/Public/{UVER}/ucd/UnicodeData.txt',
 'unicode/DerivedAge.txt': f'https://www.unicode.org/Public/{UVER}/ucd/DerivedAge.txt',
 'unicode/Blocks.txt': f'https://www.unicode.org/Public/{UVER}/ucd/Blocks.txt',
 'unicode/Scripts.txt': f'https://www.unicode.org/Public/{UVER}/ucd/Scripts.txt',
 'unicode/EastAsianWidth.txt': f'https://www.unicode.org/Public/{UVER}/ucd/EastAsianWidth.txt',
 'unicode/DerivedName.txt': f'https://www.unicode.org/Public/{UVER}/ucd/extracted/DerivedName.txt',
 'unicode/NamedSequences.txt': f'https://www.unicode.org/Public/{UVER}/ucd/NamedSequences.txt',
 'unicode/PropList.txt': f'https://www.unicode.org/Public/{UVER}/ucd/PropList.txt',
 'unicode/DerivedCoreProperties.txt': f'https://www.unicode.org/Public/{UVER}/ucd/DerivedCoreProperties.txt',
 'unicode/emoji/emoji-data.txt': f'https://www.unicode.org/Public/{UVER}/ucd/emoji/emoji-data.txt',
 'unicode/Unihan.zip': f'https://www.unicode.org/Public/{UVER}/ucd/Unihan.zip',
 'emoji/emoji-sequences.txt': 'https://www.unicode.org/Public/emoji/18.0/emoji-sequences.txt',
 'emoji/emoji-zwj-sequences.txt': 'https://www.unicode.org/Public/emoji/18.0/emoji-zwj-sequences.txt',
 'emoji/emoji-test.txt': 'https://www.unicode.org/Public/emoji/18.0/emoji-test.txt',
 'microsoft/CP932.TXT': 'https://www.unicode.org/Public/MAPPINGS/VENDORS/MICSFT/WINDOWS/CP932.TXT',
}

def main():
    raw=ROOT/'data'/'raw'; raw.mkdir(parents=True,exist_ok=True)
    records=[]
    for rel,url in MANIFEST.items():
        dst=raw/rel; dst.parent.mkdir(parents=True,exist_ok=True)
        req=Request(url,headers={'User-Agent':'CharRef-build/0.3'})
        print('GET',url)
        with urlopen(req,timeout=60) as r:
            data=r.read()
        dst.write_bytes(data)
        records.append({'path':rel,'url':url,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    (raw/'manifest.json').write_text(json.dumps({'unicode_version':UVER,'files':records},indent=2),encoding='utf-8')
    print('wrote',raw/'manifest.json')
if __name__=='__main__': main()

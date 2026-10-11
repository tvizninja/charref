#!/usr/bin/env python3
"""Create an offline bootstrap UCD from data preinstalled in this build image.

The current image ships Unicode 16.0 UnicodeData/Scripts/EAW, while Perl ships
Unicode 15.0 Age/Blocks. Assigned characters that exist in 16.0 but have no
15.0 Age entry are therefore correctly classified as Age 16.0.
This is only for build-pipeline validation, not the release dataset.
"""
from pathlib import Path
import re, shutil
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'data'/'bootstrap'/'unicode-16.0.0'; out.mkdir(parents=True,exist_ok=True)
tex=Path('/usr/share/texlive/texmf-dist/tex/generic/unicode-data')
for n in ['UnicodeData.txt','Scripts.txt','EastAsianWidth.txt']:
    shutil.copy2(tex/n,out/n)
# Perl blocks are Unicode 15; sufficient for most bootstrap chars and clearly marked.
shutil.copy2('/usr/share/perl/5.40.1/unicore/Blocks.txt',out/'Blocks.txt')
# Convert Perl To/Age.pl ranges to DerivedAge-style text.
p=Path('/usr/share/perl/5.40.1/unicore/To/Age.pl').read_text(encoding='utf-8')
body=p.split("return <<'END';",1)[1].split('\nEND',1)[0]
lines=['# Bootstrap DerivedAge generated from Perl Unicode 15.0; Unicode 16 additions are inferred by importer.']
for line in body.splitlines():
    if not line.strip(): continue
    parts=line.split('\t')
    if len(parts)<3: continue
    a,b,age=parts[0],parts[1],parts[2]
    rng=f'{a}..{b}' if b else a
    lines.append(f'{rng} ; {age}')
(out/'DerivedAge.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(out)

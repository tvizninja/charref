#!/usr/bin/env python3
import pathlib, gzip, base64
ROOT=pathlib.Path(__file__).resolve().parents[1]
html=(ROOT/'web'/'index.html').read_text(encoding='utf-8')
css=(ROOT/'web'/'app.css').read_text(encoding='utf-8')
js=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
data=(ROOT/'dist'/'webdata.json').read_bytes()
b64=base64.b64encode(gzip.compress(data,compresslevel=9)).decode('ascii')
out=html.replace('/*__CSS__*/',css).replace('/*__JS__*/',js).replace('__DATA__',b64)
path=ROOT/'dist'/'charref.html';path.write_text(out,encoding='utf-8');print(path, path.stat().st_size)

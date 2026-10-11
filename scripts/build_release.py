#!/usr/bin/env python3
"""Build a CharRef release from official Unicode 18.0.0 sources."""
from pathlib import Path
import argparse, shutil, subprocess, sys, zipfile

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

def run(*args):
    print("+", " ".join(map(str,args)), flush=True)
    subprocess.run(list(map(str,args)), cwd=ROOT, check=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="fetch authoritative sources first")
    ap.add_argument("--version", default="v2.5")
    args=ap.parse_args()
    raw=ROOT/"data"/"raw"
    ucd=raw/"unicode"
    if args.fetch:
        run(PY, ROOT/"scripts"/"fetch_sources.py")
    run(PY, ROOT/"scripts"/"verify_ucd18.py", "--ucd-dir", ucd, "--manifest", raw/"manifest.json", "--unihan-zip", ucd/"Unihan.zip")
    run(PY, ROOT/"scripts"/"build_ucd_db.py", "--ucd-dir", ucd, "--unicode-version", "18.0.0", "--dataset-kind", "official", "--unihan-zip", ucd/"Unihan.zip")
    run(PY, ROOT/"scripts"/"validate_db.py")
    run(PY, ROOT/"scripts"/"export_web.py")
    run(PY, ROOT/"scripts"/"validate_web.py")
    run(PY, ROOT/"scripts"/"build_html.py")
    out=ROOT/"dist"
    release=ROOT.parent/f"charref-{args.version}"
    release.mkdir(exist_ok=True)
    shutil.copy2(ROOT/"db"/"charref.sqlite", release/f"charref-{args.version}.sqlite")
    shutil.copy2(out/"charref.html", release/f"charref-{args.version}.html")
    zpath=release/f"charref-{args.version}.zip"
    with zipfile.ZipFile(zpath,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in ROOT.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, p.relative_to(ROOT))
    print("release:", release)

if __name__=="__main__": main()

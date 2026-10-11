#!/usr/bin/env python3
"""Strict verification of the Unicode 18.0.0 inputs used by CharRef.

This intentionally fails closed: a release build must not silently fall back to the
older bootstrap files or to the host runtime's Unicode tables.
"""
from __future__ import annotations
from pathlib import Path
import argparse, json, re, sys, zipfile

EXPECTED_VERSION = "18.0.0"
EXPECTED_AGE_COUNTS = {"17.0": 4803, "18.0": 13007}
REQUIRED = [
    "UnicodeData.txt", "DerivedAge.txt", "Blocks.txt", "Scripts.txt",
    "EastAsianWidth.txt", "PropList.txt", "DerivedCoreProperties.txt",
    "emoji/emoji-data.txt", "NamedSequences.txt",
]

def parse_age_counts(path: Path):
    counts = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ";" not in line:
            continue
        lhs, age = [x.strip() for x in line.split(";", 1)]
        if ".." in lhs:
            a, b = [int(x, 16) for x in lhs.split("..")]
        else:
            a = b = int(lhs, 16)
        counts[age] = counts.get(age, 0) + b - a + 1
    return counts

def require_version_marker(path: Path, marker: str):
    head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:12])
    if marker not in head:
        raise SystemExit(f"FAIL {path.name}: expected version marker {marker!r}")
    if "Bootstrap" in head or "bootstrap" in head:
        raise SystemExit(f"FAIL {path.name}: bootstrap data is not allowed in release builds")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ucd-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path)
    ap.add_argument("--unihan-zip", type=Path)
    args = ap.parse_args()
    u = args.ucd_dir
    missing = [p for p in REQUIRED if not (u / p).is_file()]
    if missing:
        raise SystemExit("FAIL missing Unicode 18.0.0 input(s): " + ", ".join(missing))

    require_version_marker(u / "DerivedAge.txt", "DerivedAge-18.0.0.txt")
    require_version_marker(u / "Scripts.txt", "Scripts-18.0.0.txt")
    require_version_marker(u / "EastAsianWidth.txt", "EastAsianWidth-18.0.0.txt")
    require_version_marker(u / "Blocks.txt", "Blocks-18.0.0.txt")

    ages = parse_age_counts(u / "DerivedAge.txt")
    for ver, expected in EXPECTED_AGE_COUNTS.items():
        got = ages.get(ver, 0)
        if got != expected:
            raise SystemExit(f"FAIL DerivedAge {ver}: {got} != {expected}")

    # Spot-check UnicodeData for characters introduced in 17.0 and 18.0,
    # including the large 18.0 Small Seal range.
    ud = (u / "UnicodeData.txt").read_text(encoding="utf-8")
    required_fragments = [
        "088F;ARABIC LETTER NOON WITH RING ABOVE;",
        "0558;MODIFIER LETTER ARMENIAN SMALL EH;",
        "<Seal Character, First>",
        "<Seal Character, Last>",
    ]
    for frag in required_fragments:
        if frag not in ud:
            raise SystemExit(f"FAIL UnicodeData.txt missing 17/18.0 spot check: {frag}")

    if args.unihan_zip:
        if not args.unihan_zip.is_file():
            raise SystemExit(f"FAIL Unihan archive missing: {args.unihan_zip}")
        with zipfile.ZipFile(args.unihan_zip) as zf:
            try:
                uh=zf.read('Unihan_OtherMappings.txt').decode('utf-8')
            except KeyError:
                raise SystemExit('FAIL Unihan.zip missing Unihan_OtherMappings.txt')
        head='\n'.join(uh.splitlines()[:12])
        if 'Unicode Version 18.0.0' not in head:
            raise SystemExit('FAIL Unihan.zip is not Unicode 18.0.0')
        if '\tkJIS0213\t' not in uh:
            raise SystemExit('FAIL Unihan 18.0 missing kJIS0213 data')

    if args.manifest:
        if not args.manifest.is_file():
            raise SystemExit(f"FAIL manifest missing: {args.manifest}")
        m = json.loads(args.manifest.read_text(encoding="utf-8"))
        if m.get("unicode_version") != EXPECTED_VERSION:
            raise SystemExit(f"FAIL manifest unicode_version={m.get('unicode_version')!r}")

    print("PASS official UCD 18.0.0 input verification")
    print(" - Unicode 17.0 newly assigned:", ages["17.0"])
    print(" - Unicode 18.0 newly assigned:", ages["18.0"])

if __name__ == "__main__":
    main()

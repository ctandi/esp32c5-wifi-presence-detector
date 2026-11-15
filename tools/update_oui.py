#!/usr/bin/env python3
"""Rebuild the bundled MAC vendor table from the IEEE registry.

  tools/update_oui.py                    # download from standards-oui.ieee.org
  tools/update_oui.py --from-dir DIR     # use ma-l.csv, ma-m.csv, ma-s.csv already in DIR

Writes custom_components/wifi_presence/oui.tsv.gz: one "prefix<TAB>vendor" per line, where
the prefix is 6 (MA-L), 7 (MA-M) or 9 (MA-S) hex digits. Entries that say nothing about a
vendor are left out: registrants that chose to be "Private", and the "IEEE Registration
Authority" placeholder that stands for the sub-assigned MA-M / MA-S blocks.

The data is the IEEE Registration Authority's public OUI registry. Only registry data is
downloaded; no MAC address of yours is involved.
"""

import argparse
import csv
import gzip
import io
from pathlib import Path
import sys
import urllib.request

SOURCES = {
    "ma-l.csv": "https://standards-oui.ieee.org/oui/oui.csv",
    "ma-m.csv": "https://standards-oui.ieee.org/oui28/mam.csv",
    "ma-s.csv": "https://standards-oui.ieee.org/oui36/oui36.csv",
}
PREFIX_LEN = {"MA-L": 6, "MA-M": 7, "MA-S": 9}
NO_VENDOR = {"", "private", "ieee registration authority"}
OUT = Path(__file__).resolve().parent.parent / "custom_components/wifi_presence/oui.tsv.gz"


def fetch(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "wifi-presence-oui-updater"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8-sig")


def parse(text: str) -> dict[str, str]:
    table: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(text)):
        prefix = row["Assignment"].strip().upper()
        vendor = " ".join(row["Organization Name"].split())
        if len(prefix) != PREFIX_LEN.get(row["Registry"], -1) or vendor.lower() in NO_VENDOR:
            continue
        table[prefix] = vendor
    return table


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-dir", type=Path, help="folder with ma-l.csv, ma-m.csv and ma-s.csv")
    args = ap.parse_args()

    table: dict[str, str] = {}
    for name, url in SOURCES.items():
        text = (args.from_dir / name).read_text(encoding="utf-8-sig") if args.from_dir else fetch(url)
        part = parse(text)
        print(f"{name}: {len(part)} vendors")
        table.update(part)
    if len(table) < 30000:
        sys.exit(f"only {len(table)} entries: the download looks incomplete, not writing anything")

    body = "".join(f"{prefix}\t{vendor}\n" for prefix, vendor in sorted(table.items()))
    # mtime=0 keeps the file byte-identical when the data did not change
    with OUT.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(body.encode("utf-8"))
    print(f"{len(table)} entries -> {OUT} ({OUT.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()

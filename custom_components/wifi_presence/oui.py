"""Find the vendor behind a MAC address, offline.

The first bytes of a MAC address identify the company that registered the block
(IEEE "OUI"). The registry ships with the integration as `oui.tsv.gz` (rebuild it with
tools/update_oui.py), so no address ever leaves Home Assistant. Pure Python, no Home
Assistant imports.

Nothing is returned for addresses that cannot have a vendor: randomized ("private")
addresses, which phones use per network, and group addresses.
"""

from __future__ import annotations

import gzip
from pathlib import Path
import re

_FILE = Path(__file__).with_name("oui.tsv.gz")
_NOT_HEX = re.compile(r"[^0-9A-Fa-f]")
_LOCALLY_ADMINISTERED = 0x02
_GROUP = 0x01

_table: dict[str, str] | None = None


def load() -> None:
    """Read the table (about 54,000 entries, a few tens of milliseconds). Blocking: call it
    from an executor in Home Assistant. Calling it again is free."""
    global _table
    if _table is not None:
        return
    table: dict[str, str] = {}
    with gzip.open(_FILE, "rt", encoding="utf-8") as handle:
        for line in handle:
            prefix, _, vendor = line.rstrip("\n").partition("\t")
            if prefix and vendor:
                table[prefix] = vendor
    _table = table


def is_loaded() -> bool:
    """True once load() has run."""
    return _table is not None


def lookup(mac: str) -> str | None:
    """The vendor of a MAC address in any common notation, or None.

    None as well while the table is not loaded: this never blocks.
    """
    if _table is None:
        return None
    digits = _NOT_HEX.sub("", mac).upper()
    if len(digits) < 6:
        return None
    first_octet = int(digits[:2], 16)
    if first_octet & (_LOCALLY_ADMINISTERED | _GROUP):
        return None  # randomized or a group address: no vendor registered
    # the most specific block wins: 36-bit, then 28-bit, then 24-bit assignments
    for length in (9, 7, 6):
        if len(digits) >= length and (vendor := _table.get(digits[:length])):
            return vendor
    return None

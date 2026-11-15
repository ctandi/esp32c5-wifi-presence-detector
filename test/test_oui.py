"""Tests for the MAC vendor lookup and the bundled table."""

import gzip
import importlib
from pathlib import Path
import sys
import types
import unittest

_PKG = Path(__file__).resolve().parent.parent / "custom_components/wifi_presence"
_pkg = types.ModuleType("wpkg_oui")
_pkg.__path__ = [str(_PKG)]
sys.modules["wpkg_oui"] = _pkg
oui = importlib.import_module("wpkg_oui.oui")


class Lookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        oui.load()

    def test_known_vendor_in_every_notation(self):
        for mac in ("ac:67:b2:2b:c3:96", "AC-67-B2-2B-C3-96", "AC67.B22B.C396", "ac67b22bc396", "AC:67:B2"):
            self.assertEqual(oui.lookup(mac), "Espressif Inc.", mac)

    def test_nothing_for_randomized_addresses(self):
        # bit 1 of the first byte set: a locally administered ("private") address
        for mac in ("aa:bb:cc:dd:ee:ff", "02:67:b2:2b:c3:96", "be:ee:ee:00:00:01", "da:a1:19:0b:2c:3d"):
            self.assertIsNone(oui.lookup(mac), mac)

    def test_the_randomized_address_rule_does_not_depend_on_the_registry_content(self):
        # even if a block with the "locally administered" or "group" bit were in the table, an
        # address like that must not get a vendor: it is randomized, not registered
        saved = oui._table
        oui._table = {"02AABB": "Fake Corp", "01AABB": "Fake Group", "00AABB": "Real Corp"}
        try:
            self.assertIsNone(oui.lookup("02:aa:bb:00:00:01"))
            self.assertIsNone(oui.lookup("01:aa:bb:00:00:01"))
            self.assertEqual(oui.lookup("00:aa:bb:00:00:01"), "Real Corp")
        finally:
            oui._table = saved

    def test_nothing_for_group_addresses_and_garbage(self):
        for mac in ("ff:ff:ff:ff:ff:ff", "01:00:5e:00:00:01", "", "zz", "ac:67", "not a mac"):
            self.assertIsNone(oui.lookup(mac), repr(mac))

    def test_unregistered_block_gives_nothing(self):
        # a globally administered unicast block that nobody registered: no vendor at all
        prefixes = {k[:6] for k in oui._table}
        free = next(f"{p:06X}" for p in range(0x000000, 0xFFFFFF, 4) if f"{p:06X}" not in prefixes)
        mac = ":".join(free[i:i + 2] for i in (0, 2, 4)) + ":12:34:56"
        self.assertIsNone(oui.lookup(mac))

    def test_table_has_no_placeholder_vendors(self):
        for vendor in set(oui._table.values()):
            self.assertNotIn(vendor.lower(), {"private", "ieee registration authority", ""})

    def test_table_is_plausible(self):
        self.assertGreater(len(oui._table), 40000)
        lengths = {len(k) for k in oui._table}
        self.assertEqual(lengths, {6, 7, 9})
        self.assertTrue(all(k == k.upper() and all(c in "0123456789ABCDEF" for c in k) for k in oui._table))

    def test_28_and_36_bit_assignments_are_found(self):
        for length in (7, 9):
            prefix = next(k for k in oui._table if len(k) == length)
            digits = prefix + "0" * (12 - length)  # any device inside that block
            mac = ":".join(digits[i:i + 2] for i in range(0, 12, 2))
            self.assertEqual(oui.lookup(mac), oui._table[prefix], (length, mac))

    def test_a_sub_assigned_block_does_not_read_as_the_registry_itself(self):
        # MA-L blocks that were split into MA-M / MA-S pieces must not resolve to a placeholder
        self.assertNotIn("ieee registration authority", {v.lower() for v in oui._table.values()})


class NotLoaded(unittest.TestCase):
    def test_lookup_never_blocks_or_guesses_before_loading(self):
        saved, oui._table = oui._table, None
        try:
            self.assertFalse(oui.is_loaded())
            self.assertIsNone(oui.lookup("ac:67:b2:2b:c3:96"))
        finally:
            oui._table = saved


class Bundle(unittest.TestCase):
    def test_file_is_well_formed(self):
        with gzip.open(_PKG / "oui.tsv.gz", "rt", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertTrue(all(line.count("\t") == 1 for line in lines))
        self.assertEqual(lines, sorted(lines, key=lambda line: line.split("\t")[0]))


if __name__ == "__main__":
    unittest.main()

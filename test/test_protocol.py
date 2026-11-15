"""Tests for the Python side of the protocol, including a known-answer vector
that was produced by the real firmware on an ESP32-C5 (CONFIG_WP_SELFTEST_KAT).

Run:  python3 -m unittest discover -s test -v   (from the project folder)
"""

import asyncio
import importlib
from pathlib import Path
import struct
import sys
import types
import unittest

# Load the integration's protocol and session modules without importing Home
# Assistant (the package's __init__ does): register a bare package for the folder.
_PKG = Path(__file__).resolve().parent.parent / "custom_components/wifi_presence"
_pkg = types.ModuleType("wpkg")
_pkg.__path__ = [str(_PKG)]
sys.modules["wpkg"] = _pkg
wp = importlib.import_module("wpkg.protocol")
session = importlib.import_module("wpkg.session")

# Inputs the firmware self-test uses.
PSK = bytes(range(32))
CLIENT_NONCE = bytes(0x10 + i for i in range(16))
DEV_NONCE = bytes(0x20 + i for i in range(16))
# Printed by the C5 at boot (KAT_PLAIN / KAT_MSG).
FW_PLAIN = bytes.fromhex("0200000004d205cafef00d02010203040506d80003aabbccddeeffb9007d")
FW_MSG = bytes.fromhex(
    "01202122232425262728292a2b2c2d2e2f"
    "2ea8ae4d3b439ad95fd282eb52912c3a6bfcbf7a47c049a66bee3e79b1b32c3110331501e7f86c62cab1e12bf8b7"
)
EXPECTED = wp.Report(
    uptime_s=1234,
    ap_count=5,
    truncated=False,
    config_crc=0xCAFEF00D,
    clients=(
        wp.Client("01:02:03:04:05:06", -40, 3),
        wp.Client("aa:bb:cc:dd:ee:ff", -71, 125),
    ),
)


class FirmwareKnownAnswer(unittest.TestCase):
    def test_python_builds_the_same_plaintext_as_the_c5(self):
        self.assertEqual(wp.build_report(EXPECTED), FW_PLAIN)

    def test_python_builds_the_same_message_as_the_c5(self):
        self.assertEqual(wp.seal(PSK, CLIENT_NONCE, DEV_NONCE, FW_PLAIN), FW_MSG)

    def test_python_opens_the_c5_message(self):
        plain = wp.open_message(PSK, CLIENT_NONCE, FW_MSG)
        self.assertEqual(wp.parse_report(plain), EXPECTED)


class Security(unittest.TestCase):
    def test_wrong_key_is_rejected(self):
        with self.assertRaises(wp.AuthError):
            wp.open_message(bytes(32), CLIENT_NONCE, FW_MSG)

    def test_replay_against_another_challenge_is_rejected(self):
        other = bytes(16)
        with self.assertRaises(wp.AuthError):
            wp.open_message(PSK, other, FW_MSG)

    def test_any_flipped_bit_is_rejected(self):
        for i in range(len(FW_MSG)):
            bad = bytearray(FW_MSG)
            bad[i] ^= 0x01
            with self.assertRaises(wp.ProtocolError, msg=f"byte {i}"):
                wp.open_message(PSK, CLIENT_NONCE, bytes(bad))

    def test_macs_are_not_visible_in_the_message(self):
        for mac in (bytes.fromhex("010203040506"), bytes.fromhex("aabbccddeeff")):
            self.assertNotIn(mac, FW_MSG)

    def test_session_keys_differ_per_nonce(self):
        a = wp.derive_key(PSK, CLIENT_NONCE, DEV_NONCE)
        b = wp.derive_key(PSK, CLIENT_NONCE, bytes(16))
        c = wp.derive_key(PSK, bytes(16), DEV_NONCE)
        self.assertEqual(len({a, b, c}), 3)


class Framing(unittest.TestCase):
    def test_fragments_roundtrip_for_many_sizes(self):
        for per_chunk in (7, 19, 244):
            for size in (0, 1, 18, 19, 20, 59, 617):
                msg = bytes((i * 7) & 0xFF for i in range(size))
                r = wp.Reassembler()
                out = None
                for frag in wp.fragment(msg, per_chunk):
                    out = r.feed(frag)
                self.assertEqual(out, msg, (per_chunk, size))

    def test_more_than_128_fragments_is_refused(self):
        wp.fragment(bytes(128), 1)  # exactly 128 fits
        with self.assertRaises(ValueError):
            wp.fragment(bytes(129), 1)

    def test_out_of_order_fragment_is_rejected(self):
        frags = wp.fragment(bytes(50), 19)
        r = wp.Reassembler()
        r.feed(frags[0])
        with self.assertRaises(wp.ProtocolError):
            r.feed(frags[2])

    def test_reassembler_can_be_reused(self):
        r = wp.Reassembler()
        for _ in range(2):
            for frag in wp.fragment(b"hello world", 4):
                out = r.feed(frag)
            self.assertEqual(out, b"hello world")

    def test_bad_report_lengths(self):
        with self.assertRaises(wp.ProtocolError):
            wp.parse_report(FW_PLAIN[:-1])
        with self.assertRaises(wp.ProtocolError):
            wp.parse_report(b"\x01" + FW_PLAIN[1:])  # an old report version


class Keys(unittest.TestCase):
    def test_parse_key(self):
        self.assertEqual(wp.parse_key(" " + "ab" * 32 + "\n"), bytes.fromhex("ab" * 32))
        # copied from a console or typed in groups: spaces, dashes and colons are ignored
        grouped = "-".join(["abcdef01"] * 8)
        self.assertEqual(wp.parse_key(grouped), bytes.fromhex("abcdef01" * 8))
        for bad in ("", "ab" * 31, "zz" * 32):
            with self.assertRaises(ValueError):
                wp.parse_key(bad)


class Settings(unittest.TestCase):
    SAMPLE = wp.Config(
        ssids=("MyNet", "Gäste"), country="AT", band=wp.BAND_5G, scan_dwell_ms=300,
        hop_ms=1500, rescan_s=900, min_frames=4, hold_s=600, min_rssi=-85,
    )
    # The same bytes main/wp_config.c produces (pinned in test/host_test.c).
    SAMPLE_BLOB = bytes.fromhex("01024154012c05dc0384040258ab02054d794e65740647c3a4737465")

    def test_encoding_matches_the_firmware_layout(self):
        self.assertEqual(wp.encode_config(self.SAMPLE), self.SAMPLE_BLOB)

    def test_crc_is_standard_crc32(self):
        self.assertEqual(wp.config_crc(b"123456789"), 0xCBF43926)
        self.assertEqual(wp.config_crc(self.SAMPLE_BLOB), 0xE146F581)

    def test_roundtrip(self):
        self.assertEqual(wp.decode_config(wp.encode_config(self.SAMPLE)), self.SAMPLE)
        self.assertEqual(wp.decode_config(wp.encode_config(wp.Config())), wp.Config())

    def test_every_limit_is_enforced(self):
        bad = [
            {"band": 3}, {"country": "de"}, {"country": "D"}, {"scan_dwell_ms": 119},
            {"scan_dwell_ms": 1501}, {"hop_ms": 199}, {"hop_ms": 30001}, {"rescan_s": 29},
            {"rescan_s": 3601}, {"min_frames": 0}, {"min_frames": 101}, {"hold_s": 9},
            {"hold_s": 43201}, {"min_rssi": -101}, {"min_rssi": -19},
            {"ssids": ("x",) * 9}, {"ssids": ("",)}, {"ssids": ("x" * 33,)},
            {"ssids": ("é" * 17,)},  # 34 bytes
            {"ssids": ("a\0b",)},
        ]
        for kw in bad:
            with self.assertRaises(ValueError, msg=str(kw)):
                wp.encode_config(wp.Config(**{"ssids": ("a",), **kw}))
        # the edges themselves are fine
        wp.encode_config(wp.Config(ssids=("x" * 32,) * 8, scan_dwell_ms=120, hop_ms=30000,
                                   rescan_s=30, min_frames=100, hold_s=43200, min_rssi=-20))

    def test_largest_config_fits_the_firmware_buffer(self):
        blob = wp.encode_config(wp.Config(ssids=("x" * 32,) * 8))
        self.assertEqual(len(blob), 15 + 8 * 33)

    def test_hostile_blobs_are_refused(self):
        blob = self.SAMPLE_BLOB
        for cut in range(len(blob)):
            with self.assertRaises(wp.ProtocolError, msg=f"cut {cut}"):
                wp.decode_config(blob[:cut])
        with self.assertRaises(wp.ProtocolError):
            wp.decode_config(blob + b"\0")
        with self.assertRaises(wp.ProtocolError):
            wp.decode_config(b"\x02" + blob[1:])


class Commands(unittest.TestCase):
    KEY = bytes(range(32))

    def test_command_roundtrip(self):
        msg = wp.seal_command(self.KEY, 7, wp.CMD_SET_CONFIG, b"payload")
        self.assertEqual(wp.open_command(self.KEY, msg), (7, wp.CMD_SET_CONFIG, b"payload"))

    def test_command_is_bound_to_key_counter_and_direction(self):
        msg = wp.seal_command(self.KEY, 1, wp.CMD_SET_CONFIG, b"x")
        with self.assertRaises(wp.AuthError):
            wp.open_command(bytes(32), msg)
        forged = bytearray(msg)
        forged[4] = 2  # claim another counter
        with self.assertRaises(wp.AuthError):
            wp.open_command(self.KEY, bytes(forged))
        for i in range(len(msg)):
            bad = bytearray(msg)
            bad[i] ^= 1
            with self.assertRaises(wp.ProtocolError, msg=f"byte {i}"):
                wp.open_command(self.KEY, bytes(bad))
        # a command can not be passed off as an acknowledgement
        with self.assertRaises(wp.ProtocolError):
            wp.open_ack(self.KEY, 1, msg)

    def test_ack_roundtrip_and_binding(self):
        ack = wp.seal_ack(self.KEY, 3, wp.STATUS_OK, 0x11223344)
        self.assertEqual(wp.open_ack(self.KEY, 3, ack), wp.Ack(wp.STATUS_OK, 0x11223344))
        with self.assertRaises(wp.ProtocolError):
            wp.open_ack(self.KEY, 4, ack)  # belongs to another command
        with self.assertRaises(wp.AuthError):
            wp.open_ack(bytes(32), 3, ack)

    def test_counter_zero_is_not_allowed(self):
        with self.assertRaises(ValueError):
            wp.seal_command(self.KEY, 0, wp.CMD_SET_CONFIG)

    def test_iv_layout(self):
        self.assertEqual(wp.make_iv(0, 0), bytes(12))
        self.assertEqual(wp.make_iv(1, 0x01020304), bytes([1]) + bytes(7) + bytes([1, 2, 3, 4]))


class FakeDevice:
    """Behaves like the firmware's GATT server, on the BleakClient interface."""

    def __init__(self, psk, *, stored_blob=b"", mtu=23, accept=True, wrong_ack_crc=False, silent=False):
        self.psk, self.blob, self.mtu_size = psk, stored_blob, mtu
        self.accept, self.wrong_ack_crc, self.silent = accept, wrong_ack_crc, silent
        self.cb = None
        self.key = None
        self.last_ctr = 0
        self.reasm = wp.Reassembler()
        self.writes = 0
        self.notifying = False

    @property
    def crc(self):
        return wp.config_crc(self.blob) if self.blob else 0

    async def start_notify(self, uuid, cb):
        assert uuid == wp.DATA_UUID and not self.notifying, "notifications were left on"
        self.cb, self.notifying = cb, True

    async def stop_notify(self, uuid):
        self.notifying = False

    def _notify(self, message):
        for frag in wp.fragment(message, self.mtu_size - 3 - 1):
            self.cb(None, bytearray(frag))

    async def write_gatt_char(self, uuid, data, response=True):
        if self.silent:
            return
        self.writes += 1
        if uuid == wp.CTRL_UUID:
            client_nonce, dev_nonce = bytes(data[1:17]), bytes(range(100, 116))
            report = wp.Report(uptime_s=5, ap_count=2, truncated=False, config_crc=self.crc,
                               clients=(wp.Client("01:02:03:04:05:06", -50, 1),))
            self.key = wp.derive_key(self.psk, client_nonce, dev_nonce)
            self._notify(wp.seal(self.psk, client_nonce, dev_nonce, wp.build_report(report)))
        elif uuid == wp.CMD_UUID:
            message = self.reasm.feed(bytes(data))
            if message is None:
                return
            ctr, command, payload = wp.open_command(self.key, message)
            assert ctr > self.last_ctr
            self.last_ctr = ctr
            status = wp.STATUS_OK
            if not self.accept:
                status = wp.STATUS_INVALID
            else:
                self.blob = payload
            crc = self.crc ^ (1 if self.wrong_ack_crc else 0)
            self._notify(wp.seal_ack(self.key, ctr, status, crc))


def run(coro):
    return asyncio.run(coro)


class Session(unittest.TestCase):
    PSK = bytes(range(32))
    CONFIG = wp.Config(ssids=("MyNet", "Gäste"), hold_s=600)

    def poll(self, device, config=None, **kw):
        return run(session.run_session(device, self.PSK, config, timeout=1.0, **kw))

    def test_plain_poll_reads_the_report_and_sends_nothing(self):
        device = FakeDevice(self.PSK)
        result = self.poll(device)
        self.assertEqual(result.report.clients[0].mac, "01:02:03:04:05:06")
        self.assertFalse(result.config_applied)
        self.assertEqual(device.writes, 1)  # only the request

    def test_settings_are_sent_when_the_sensor_has_none(self):
        device = FakeDevice(self.PSK)
        result = self.poll(device, self.CONFIG)
        self.assertTrue(result.config_applied)
        self.assertEqual(wp.decode_config(device.blob), self.CONFIG)

    def test_settings_are_not_resent_when_they_already_match(self):
        blob = wp.encode_config(self.CONFIG)
        device = FakeDevice(self.PSK, stored_blob=blob)
        result = self.poll(device, self.CONFIG)
        self.assertFalse(result.config_applied)
        self.assertEqual(device.writes, 1)

    def test_force_sends_them_anyway(self):
        device = FakeDevice(self.PSK, stored_blob=wp.encode_config(self.CONFIG))
        self.assertTrue(self.poll(device, self.CONFIG, force=True).config_applied)

    def test_changed_settings_replace_the_old_ones(self):
        device = FakeDevice(self.PSK, stored_blob=wp.encode_config(self.CONFIG))
        newer = wp.Config(ssids=("Other",), hold_s=900)
        self.assertTrue(self.poll(device, newer).config_applied)
        self.assertEqual(wp.decode_config(device.blob), newer)

    def test_a_long_command_is_fragmented_to_the_mtu(self):
        big = wp.Config(ssids=("x" * 32,) * 8)
        for mtu in (23, 100, 247):
            device = FakeDevice(self.PSK, mtu=mtu)
            self.assertTrue(self.poll(device, big).config_applied, mtu)
            self.assertEqual(wp.decode_config(device.blob), big)
        # at MTU 23 one write carries 19 data bytes: 5+1+279+16 = 301 bytes -> 16 writes + request
        device = FakeDevice(self.PSK, mtu=23)
        self.poll(device, big)
        self.assertEqual(device.writes, 1 + 16)

    def test_refused_settings_raise(self):
        with self.assertRaises(session.ConfigRejected):
            self.poll(FakeDevice(self.PSK, accept=False), self.CONFIG)

    def test_a_refusal_is_caught_even_when_the_crc_happens_to_match(self):
        # the sensor already holds these settings, yet answers "invalid": the status counts
        device = FakeDevice(self.PSK, stored_blob=wp.encode_config(self.CONFIG), accept=False)
        with self.assertRaises(session.ConfigRejected):
            self.poll(device, self.CONFIG, force=True)

    def test_an_ack_for_other_settings_raises(self):
        with self.assertRaises(session.ConfigRejected):
            self.poll(FakeDevice(self.PSK, wrong_ack_crc=True), self.CONFIG)

    def test_wrong_key_raises_auth_error(self):
        with self.assertRaises(wp.AuthError):
            run(session.run_session(FakeDevice(bytes(32)), self.PSK, timeout=1.0))

    def test_silent_sensor_times_out(self):
        with self.assertRaises(TimeoutError):
            self.poll(FakeDevice(self.PSK, silent=True))

    def test_invalid_settings_never_leave_the_computer(self):
        device = FakeDevice(self.PSK)
        with self.assertRaises(ValueError):
            self.poll(device, wp.Config(ssids=("a",), hold_s=1))
        self.assertEqual(device.blob, b"")

    def test_notifications_are_switched_off_so_the_connection_can_be_reused(self):
        device = FakeDevice(self.PSK)
        self.poll(device)
        self.poll(device)  # a second start_notify would trip the fake's assertion
        self.assertFalse(device.notifying)


if __name__ == "__main__":
    unittest.main()

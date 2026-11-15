"""Hostile-client tests for a REAL sensor: can anyone without the key read or change anything?

Needs a Bluetooth adapter, `pip install bleak cryptography`, and a sensor in range that
is already configured (the test sends its own settings first and checks they survive).
It leaves the sensor with default settings for --ssid; Home Assistant sends yours again on its next poll.

  python3 test/hardware/command_security.py --key <64 hex digits> --ssid <your Wi-Fi name>
"""
import argparse, asyncio, importlib, os, struct, sys, types
from pathlib import Path
from bleak import BleakClient, BleakScanner, BleakError

PKG = Path(__file__).resolve().parents[2] / "custom_components/wifi_presence"
pkg = types.ModuleType("wp"); pkg.__path__ = [str(PKG)]; sys.modules["wp"] = pkg
wp = importlib.import_module("wp.protocol"); session = importlib.import_module("wp.session")
_ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
_ap.add_argument("--key", default=os.environ.get("WP_KEY"), help="64 hex digits (or WP_KEY)")
_ap.add_argument("--ssid", required=True, help="your Wi-Fi name: the sensor is left watching it")
_args = _ap.parse_args()
if not _args.key:
    sys.exit("no key: pass --key or set WP_KEY")
PSK = wp.parse_key(_args.key)
results = []

def check(name, ok, detail=""):
    results.append(ok); print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

async def bye(c):
    try: await c.disconnect()
    except (EOFError, OSError): pass
    await asyncio.sleep(1)

async def connect():
    dev = await BleakScanner.find_device_by_filter(lambda d, a: wp.SERVICE_UUID in [u.lower() for u in a.service_uuids], timeout=15)
    c = BleakClient(dev, timeout=15); await c.connect(); return c

class Link:
    """Raw access: subscribe, request a report, send raw command fragments, collect answers."""
    def __init__(self, client, psk): self.c, self.psk = client, psk; self.re = wp.Reassembler(); self.q = asyncio.Queue()
    def _on(self, _ch, data):
        try:
            m = self.re.feed(bytes(data))
            if m is not None: self.q.put_nowait(m)
        except wp.ProtocolError as e: self.q.put_nowait(e)
    async def start(self):
        await self.c.start_notify(wp.DATA_UUID, self._on)
    async def request(self, psk=None):
        self.nonce, req = wp.new_request(); await self.c.write_gatt_char(wp.CTRL_UUID, req, response=True)
        msg = await asyncio.wait_for(self.q.get(), 8)
        self.dev_nonce = msg[1:17]
        try:
            self.key, plain = wp.open_report_message(psk or self.psk, self.nonce, msg); return wp.parse_report(plain)
        except wp.AuthError:
            self.key = wp.derive_key(psk or self.psk, self.nonce, self.dev_nonce); return None
    async def send(self, message):
        for f in wp.fragment(message, 19): await self.c.write_gatt_char(wp.CMD_UUID, f, response=True)
    async def answer(self, timeout=4):
        try: return await asyncio.wait_for(self.q.get(), timeout)
        except asyncio.TimeoutError: return None

def blob(**kw):
    return wp.encode_config(wp.Config(ssids=(_args.ssid,), **kw))

async def current_crc():
    c = await connect()
    try:
        l = Link(c, PSK); await l.start(); r = await l.request(); return r.config_crc
    finally:
        try: await c.disconnect()
        except Exception: pass

async def main():
    # Use the sensor's own current settings as the baseline: read them via the CRC only,
    # then push a known test configuration so every later step has something to compare with.
    good = blob()
    c = await connect()
    try:
        l = Link(c, PSK); await l.start(); await l.request()
        await l.send(wp.seal_command(l.key, 1, wp.CMD_SET_CONFIG, good))
        wp.open_ack(l.key, 1, await l.answer(8))
    finally:
        await bye(c)
    crc0 = await current_crc()
    check("start state: the sensor holds the test settings", crc0 == wp.config_crc(good), f"{crc0:08x}")
    evil = wp.encode_config(wp.Config(ssids=("EvilNet",)))

    # 1. holder of a WRONG key: cannot open the report, command sealed with its own derived key is dropped
    c = await connect(); l = Link(c, PSK); await l.start()
    rep = await l.request(psk=bytes(32))
    check("wrong key: report does not open", rep is None)
    await l.send(wp.seal_command(l.key, 1, wp.CMD_SET_CONFIG, evil))
    a = await l.answer()
    check("wrong key: command gets no answer", a is None)
    await bye(c)
    check("wrong key: settings unchanged", await current_crc() == crc0)

    # 2. command with a flipped bit
    c = await connect(); l = Link(c, PSK); await l.start(); await l.request()
    m = bytearray(wp.seal_command(l.key, 1, wp.CMD_SET_CONFIG, good)); m[-3] ^= 1
    await l.send(bytes(m)); check("flipped bit: no answer", await l.answer() is None)
    # 3. legit command works, then the same bytes again in the same session (counter not fresh)
    legit = wp.seal_command(l.key, 1, wp.CMD_SET_CONFIG, good)
    await l.send(legit); ack = wp.open_ack(l.key, 1, await l.answer(8))
    check("legit command: ack OK with right CRC", ack.status == 0 and ack.config_crc == crc0)
    await l.send(legit); check("replay in same session: no answer", await l.answer() is None)
    old_session_msg = legit
    # 4. counter going backwards / counter 0
    await l.send(wp.seal_command(l.key, 1, wp.CMD_SET_CONFIG, good)); check("counter reuse: no answer", await l.answer() is None)
    # 5. authenticated but invalid settings -> status INVALID, nothing stored
    bad = bytearray(good); struct.pack_into(">H", bad, 11, 5)  # hold_s = 5, below the minimum
    await l.send(wp.seal_command(l.key, 2, wp.CMD_SET_CONFIG, bytes(bad)))
    ack = wp.open_ack(l.key, 2, await l.answer(8))
    check("invalid settings: status INVALID, CRC unchanged", ack.status == wp.STATUS_INVALID and ack.config_crc == crc0, f"status {ack.status}")
    # 6. unknown command byte
    await l.send(wp.seal_command(l.key, 3, 0x7f, b"x"))
    ack = wp.open_ack(l.key, 3, await l.answer(8)); check("unknown command: refused", ack.status == wp.STATUS_INVALID)
    # 7. garbled fragmentation: out-of-order sequence number -> ATT error
    try:
        await c.write_gatt_char(wp.CMD_UUID, bytes([0x05, 1, 2, 3]), response=True); err = False
    except BleakError: err = True
    check("out-of-order fragment: rejected by the device", err)
    # 8. oversized write
    try:
        await c.write_gatt_char(wp.CMD_UUID, bytes(250), response=True); err = False
    except BleakError: err = True
    check("oversized write: rejected", err)
    await bye(c)

    # 9. cross-session replay: bytes sealed in an earlier session
    c = await connect(); l = Link(c, PSK); await l.start(); await l.request()
    await l.send(old_session_msg); check("replay from an earlier session: no answer", await l.answer() is None)
    await bye(c)

    # 10. command with no session at all (no report requested)
    c = await connect(); l = Link(c, PSK); await l.start()
    try:
        await l.send(wp.seal_command(bytes(32), 1, wp.CMD_SET_CONFIG, evil)); err = False
    except BleakError: err = True
    check("command without a session: rejected", err)
    await bye(c)

    # 11. command without subscribing to the answers
    c = await connect()
    try:
        await c.write_gatt_char(wp.CMD_UUID, bytes([0x80, 1]), response=True); err = False
    except BleakError: err = True
    check("command without subscription: rejected", err)
    await bye(c)

    # 12. a stranger with no key reading the DATA stream sees no MACs: ciphertext only
    c = await connect(); l = Link(c, PSK); await l.start(); raw = None
    l.nonce, req = wp.new_request(); await c.write_gatt_char(wp.CTRL_UUID, req, response=True)
    raw = await l.answer(8); await bye(c)
    c2 = await connect(); l2 = Link(c2, PSK); await l2.start(); r = await l2.request()
    macs = [bytes.fromhex(x.mac.replace(":", "")) for x in r.clients]
    check("ciphertext contains none of the client MACs", raw is not None and not any(m in raw for m in macs))
    await bye(c2)

    final = await current_crc()
    check("after all attacks the settings are still the original ones", final == crc0, f"{final:08x}")
    print(f"\n{sum(results)}/{len(results)} passed")
    print("NOTE: the sensor now holds the test settings (your SSID, default tuning); Home Assistant re-sends yours on its next poll.")
    sys.exit(0 if all(results) else 1)

asyncio.run(main())

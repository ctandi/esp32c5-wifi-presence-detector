#!/usr/bin/env python3
"""Talk to a C5 Wi-Fi presence sensor over Bluetooth, like Home Assistant does.

Needs a Bluetooth adapter and `pip install bleak cryptography`.

  tools/wp_client.py --key <64 hex digits>                  # print the clients
  tools/wp_client.py --key ... --repeat 5                   # five polls on one connection
  tools/wp_client.py --key ... --ssid MyWiFi --ssid Guest   # push settings
  tools/wp_client.py --key ... --ssid MyWiFi --hold 600 --band 5g

The key is printed by the sensor on its serial console (also: WP_KEY environment
variable). Settings not given on the command line take their defaults.
"""

import argparse
import asyncio
import importlib
import os
from pathlib import Path
import sys
import time
import types

from bleak import BleakClient, BleakScanner

# Load the integration's protocol and session modules without importing Home
# Assistant (the package's __init__ does): register a bare package for the folder.
_PKG = Path(__file__).resolve().parent.parent / "custom_components/wifi_presence"
_pkg = types.ModuleType("wp")
_pkg.__path__ = [str(_PKG)]
sys.modules["wp"] = _pkg
wp = importlib.import_module("wp.protocol")
session = importlib.import_module("wp.session")


async def find_device(address: str | None, timeout: float):
    def match(device, adv):
        if address:
            return device.address.lower() == address.lower()
        return wp.SERVICE_UUID in [u.lower() for u in adv.service_uuids]

    device = await BleakScanner.find_device_by_filter(match, timeout=timeout)
    if device is None:
        sys.exit("sensor not found (is it powered, in range, and is the adapter working?)")
    return device


def config_from_args(args) -> "wp.Config | None":
    if args.ssid is None:
        return None
    config = wp.Config(
        ssids=tuple(args.ssid),
        country=args.country,
        band={"both": wp.BAND_BOTH, "2g": wp.BAND_2G, "5g": wp.BAND_5G}[args.band],
        scan_dwell_ms=args.dwell,
        hop_ms=args.hop,
        rescan_s=args.rescan,
        min_frames=args.min_frames,
        hold_s=args.hold,
        min_rssi=args.min_rssi,
    )
    try:
        config.validate()
    except ValueError as err:
        sys.exit(f"invalid setting: {err}")
    return config


async def main() -> None:
    d = wp.Config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default=os.environ.get("WP_KEY"), help="64 hex digits, as printed by the sensor")
    ap.add_argument("--address", help="Bluetooth address (default: find by service UUID)")
    ap.add_argument("--repeat", type=int, default=1, help="polls on one connection")
    ap.add_argument("--timeout", type=float, default=15.0)
    g = ap.add_argument_group("settings (giving --ssid pushes them to the sensor)")
    g.add_argument("--ssid", action="append", help="network to watch, repeatable")
    g.add_argument("--country", default=d.country)
    g.add_argument("--band", choices=["both", "2g", "5g"], default="both")
    g.add_argument("--dwell", type=int, default=d.scan_dwell_ms, help="search ms per channel")
    g.add_argument("--hop", type=int, default=d.hop_ms, help="listen ms per channel")
    g.add_argument("--rescan", type=int, default=d.rescan_s, help="seconds between searches")
    g.add_argument("--hold", type=int, default=d.hold_s, help="seconds a device stays present")
    g.add_argument("--min-frames", type=int, default=d.min_frames)
    g.add_argument("--min-rssi", type=int, default=d.min_rssi, help="dBm")
    args = ap.parse_args()

    if not args.key:
        sys.exit("no key: pass --key or set WP_KEY (the sensor prints it on its serial console)")
    try:
        psk = wp.parse_key(args.key)
    except ValueError as err:
        sys.exit(str(err))
    config = config_from_args(args)

    device = await find_device(args.address, args.timeout)
    print(f"found {device.address} ({device.name})")

    started = time.monotonic()
    client = BleakClient(device, timeout=args.timeout)
    await client.connect()
    try:
        print(f"connected in {time.monotonic() - started:.1f} s, mtu {client.mtu_size}")
        for i in range(args.repeat):
            t0 = time.monotonic()
            try:
                result = await session.run_session(
                    client, psk, config if i == 0 else None, force=config is not None, timeout=args.timeout
                )
            except wp.AuthError:
                sys.exit("the sensor rejected the key")
            report = result.report
            print(f"poll {i + 1}: {time.monotonic() - t0:.2f} s, uptime {report.uptime_s} s, "
                  f"{report.ap_count} AP(s), settings crc {report.config_crc:08x}, "
                  f"{len(report.clients)} client(s){' (truncated)' if report.truncated else ''}")
            if result.config_applied:
                print("  settings sent and confirmed by the sensor")
            for c in sorted(report.clients, key=lambda c: c.age_s):
                print(f"    {c.mac}  rssi {c.rssi:4d}  last heard {c.age_s:4d} s ago")
    finally:
        try:
            await client.disconnect()
        except (EOFError, OSError):
            pass  # bleak's D-Bus link sometimes drops while closing; the device times out anyway


if __name__ == "__main__":
    asyncio.run(main())

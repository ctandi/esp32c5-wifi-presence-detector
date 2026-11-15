# Wi-Fi Presence Sensor for Home Assistant

An **ESP32-C5** that listens to your Wi-Fi and tells Home Assistant which devices are
connected: **no router access, no pinging, no allow-list.** The sensor never joins your
network, so it can listen continuously, on 2.4 GHz and 5 GHz. It reports over Bluetooth,
through an adapter or ESPHome Bluetooth proxy you already have, and the list of devices
only ever travels **encrypted**.

```
your Wi-Fi ──► ESP32-C5 (listens only) ──► encrypted Bluetooth ──► Home Assistant
                                                   │                 sensors + one tracker
                                                   └── key and settings flow back the same way
```

## Quick start

1. **Flash it from your browser:** open **https://ctandi.github.io/esp32c5-wifi-presence-detector/**,
   plug in the ESP32-C5, click *Install firmware*, then *Logs & Console*. The sensor prints
   its **pairing key**: copy it.
2. **Install the integration** (HACS custom repository, or copy `custom_components/wifi_presence`
   to your Home Assistant) and restart.
3. **Add it:** the sensor appears under *Settings → Devices & services → Discovered*. Paste
   the key, enter the name of your Wi-Fi. Done.

You never touch the sensor again: the Wi-Fi names, scan times and everything else are
settings in Home Assistant.

**→ Step by step: [docs/MANUAL.md](docs/MANUAL.md)**

## What you get

- Clients currently on your Wi-Fi, as a count (with the list as an attribute).
- A `device_tracker` per device ever heard, **disabled by default** (a home network is
  full of TVs and plugs); enable your phone's and put it on a Person.
- Settings in Home Assistant: the Wi-Fi names to watch (several allowed), country, bands,
  scan time per channel, how long a sleeping phone stays "home", minimum signal strength and
  more. They are pushed to the sensor over Bluetooth, authenticated, and stored on it.
- No secrets in the firmware: every sensor makes its own key on first start.

## How it works, briefly

The C5 finds the channels of your access points with a passive scan, then listens there
for **data frames** and notes which devices are talking to your access points (the headers
are readable even when the content is encrypted, so WPA2/WPA3 do not matter). A device is
present after a few frames and stays present for a while after its last one, because
sleeping phones talk rarely. Home Assistant connects over Bluetooth every 30 seconds,
sends a random challenge, and gets the list back as one AES-256-GCM message under a key
derived from the pairing key and both sides' nonces. Details and the wire format:
[PROTOCOL.md](PROTOCOL.md).

## Limits

- It sees *Wi-Fi clients*, not people. Phones that **rotate** their Wi-Fi address look like a
  new device each time; the usual per-network fixed private address works fine.
- Hidden networks are not found by the scan.
- At most 8 network names, 16 access points and 64 devices (table size is a build option).
- "Away" is slow by design (5 minutes by default) because a sleeping phone is quiet; it is
  a setting.

## Project status

What has been verified, and how:

- **On real hardware** (ESP32-C5, ESP-IDF 5.5.1, a Linux Bluetooth adapter): sniffing five
  access points on both bands, 10 to 18 devices heard, the encrypted exchange, pushing settings
  (including every band and timing option), settings surviving reboots and updates, and 17
  attack cases against the command channel (wrong key, flipped bits, replays, bad
  fragments, ...): none got through (`test/hardware/command_security.py`).
- **In Home Assistant's own test framework:** config flow, settings and options flow,
  re-authentication, entities, home/away, availability (35 tests, with mutation checks).
- **CI and web flasher:** the GitHub Actions workflow runs green (tests, firmware build with
  ESP-IDF v5.5.6, GitHub Pages deploy). The three firmware parts the page serves were
  downloaded from the live site, flashed to a real board with esptool, and passed the same
  checks as the local build (pairing, scanning, the 17 attack cases).
- **Not yet verified:** the integration running in a live Home Assistant through an
  ESPHome Bluetooth proxy, and the flashing click-through in a browser (ESP Web Tools was not
  driven from a browser here). Please report what you find.
- **Known:** with an ESP-IDF v5.5.1 build the chip got stuck after a forced reset twice in
  ~30 tries and needed a USB unplug; with the published v5.5.6 build, 10 of 10 resets were
  fine, which is encouraging but too few to call it fixed. See
  [troubleshooting](docs/MANUAL.md#troubleshooting).

## License

[MIT](LICENSE). The firmware builds on ESP-IDF, NimBLE and mbedTLS (Apache-2.0); the web
flasher loads [ESP Web Tools](https://esphome.github.io/esp-web-tools/) (Apache-2.0) from a CDN.

## Repository

| Path | What |
|------|------|
| `main/` | ESP32-C5 firmware (ESP-IDF, NimBLE, Wi-Fi sniffer) |
| `custom_components/wifi_presence/` | Home Assistant integration |
| `web/` | The web flasher page ([ESP Web Tools](https://esphome.github.io/esp-web-tools/)) |
| `docs/MANUAL.md` | User manual |
| `PROTOCOL.md` | Bluetooth protocol |
| `tools/wp_client.py` | Command-line client (read the list, push settings) |
| `test/` | Host tests (C), protocol tests, Home Assistant tests, a hostile-client hardware test |
| `.github/workflows/build.yml` | Tests, firmware build, web flasher publishing |

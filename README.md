# Wi-Fi Presence Sensor for Home Assistant

[![Build](https://github.com/ctandi/esp32c5-wifi-presence-detector/actions/workflows/build.yml/badge.svg)](https://github.com/ctandi/esp32c5-wifi-presence-detector/actions/workflows/build.yml) [![Validate](https://github.com/ctandi/esp32c5-wifi-presence-detector/actions/workflows/validate.yml/badge.svg)](https://github.com/ctandi/esp32c5-wifi-presence-detector/actions/workflows/validate.yml)

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
2. **Install the integration** from the Home Assistant Marketplace (one click, see
   [below](#install-the-home-assistant-integration)).
3. **Add it:** the sensor appears under *Settings → Devices & services → Discovered*. Paste
   the key, enter the name of your Wi-Fi. Done.

You never touch the sensor again: the Wi-Fi names, scan times and everything else are
settings in Home Assistant.

**→ Step by step: [docs/MANUAL.md](docs/MANUAL.md)**

## Install the Home Assistant integration

The integration is a community repository, so it is installed through the Marketplace
(*Settings → Marketplace*, built into Home Assistant 2026.11 and newer) by adding this
repository once. Nothing is copied by hand, and the Marketplace tells you when updates arrive.

[![Open your Home Assistant instance and show the repository in the Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ctandi&repository=esp32c5-wifi-presence-detector&category=integration)

Or step by step, **Home Assistant 2026.11 or newer (Marketplace):**

1. Open *Settings → Marketplace*. The first time, read and accept the warning (everything in
   the Marketplace is community-made and untested by the Home Assistant project; this
   project's code is open for you to read).
2. Select *Add from link* in the upper-right corner and enter
   `https://github.com/ctandi/esp32c5-wifi-presence-detector` (or just
   `ctandi/esp32c5-wifi-presence-detector`), then *Add*. If you have not connected GitHub
   yet, the Marketplace asks you to do so now (it shows a code that you enter on github.com;
   it gets no access to private repositories and cannot change anything); this is only
   needed for adding custom repositories and for update checks. If asked for the type, choose *Integration*.
3. Open the repository's page and select *Install*, then confirm.
4. The setup page of the integration opens if Home Assistant can load it right away. If it
   asks for a restart instead, a repair under *Settings → System → Repairs* offers it.

**Home Assistant 2026.10 (HACS):** in HACS use ⋮ → *Custom repositories*, add the
same URL with the type *Integration*, download *Wi-Fi Presence Sensor*, and restart
Home Assistant.

**Manually:** copy the folder `custom_components/wifi_presence` of this repository into
the `custom_components` folder of your Home Assistant configuration and restart.

Then continue with step 3 above: the sensor appears under *Settings → Devices & services →
Discovered*, or start the setup with
[![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=wifi_presence).

## What you get

- Clients currently on your Wi-Fi, as a count (with the list as an attribute).
- A `device_tracker` named *Wi-Fi presence* plus the device's address for every device ever
  heard. Either **track all devices automatically** (one switch), or keep them hidden and
  pick yours in the *Configure* dialog, *Devices to track*, which lists everything heard
  (with the names Home Assistant already knows, and signal strength). Put your phone's on a Person.
- A status LED (the yellow one on the XIAO ESP32-C5): slow blink while it waits for Home
  Assistant, steady when connected, a flash on activity.
- An **activity log** on the sensor's device: "*AA:BB:CC:11:22:33 (Vendor) just became present*" and
  "... is now gone". The same events can trigger automations.
- The **vendor** of each device (from the bundled IEEE registry, offline) next to its address in the
  entity names (*Wi-Fi presence AA:BB:CC:11:22:33 (Vendor)*), the device picker and the log; nothing is
  shown for randomized addresses or unknown vendors.
- A sensor you can name (for example *Wi-Fi presence living room*), so several sensors stay apart.
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

This is an early release (0.2): it works in daily use on the author's setup, and has not been
tried by many people yet. What has been verified, and how:

- **In a live Home Assistant 2026.11, through an ESPHome Bluetooth proxy:** flashing with the web
  flasher, discovery, pairing with the key, pushing and changing settings, the *Configure*
  dialog (device picker, track all, rename), re-authentication, the status LED, the activity log,
  vendor names in entity and device names, and polling
  every 30 seconds.
- **On real hardware** (Seeed XIAO ESP32-C5, ESP-IDF 5.5.1 and the CI build with 5.5.6): sniffing
  access points on both bands, the encrypted exchange, every settings option (band, search and
  listening times, hold time, ...), settings surviving reboots and updates, and 17 attack cases
  against the command channel (wrong key, flipped bits, replays, bad fragments, ...): none got
  through (`test/hardware/command_security.py`).
- **Automated tests:** C logic (frames, settings, report, LED timing), 49 protocol and vendor-lookup tests with a
  firmware-produced known-answer vector, 70 Home Assistant tests (config flow, options flow,
  re-authentication, entities, trackers, activity log events), run by CI on every push, with mutation checks while
  writing them.
- **Not verified:** more than one sensor in one Home Assistant, Home Assistant versions other
  than 2026.10 and 2026.11 (the integration needs 2026.10 or newer), flashing from
  Windows or macOS (only Linux with Chromium was used), and the Marketplace's automatic
  update notification (switching between releases by hand with *Install another version* worked).
- **Known:** with an ESP-IDF v5.5.1 build the chip got stuck after a forced reset twice in
  ~30 tries and needed a USB unplug; with the published v5.5.6 build, 10 of 10 resets were
  fine, which is encouraging but too few to call it fixed. See
  [troubleshooting](docs/MANUAL.md#troubleshooting).

Please report what you find: [issues](https://github.com/ctandi/esp32c5-wifi-presence-detector/issues).

## License

[MIT](LICENSE). The firmware builds on ESP-IDF, NimBLE and mbedTLS (Apache-2.0); the MAC vendor
table is distilled from the public IEEE Registration Authority OUI registry (`tools/update_oui.py`); the web
flasher loads [ESP Web Tools](https://esphome.github.io/esp-web-tools/) (Apache-2.0) from a CDN.

## Repository

| Path | What |
|------|------|
| `main/` | ESP32-C5 firmware (ESP-IDF, NimBLE, Wi-Fi sniffer) |
| `custom_components/wifi_presence/` | Home Assistant integration (what the Marketplace installs), with its `brand/` icons |
| `hacs.json` | Marketplace / HACS metadata |
| `web/` | The web flasher page ([ESP Web Tools](https://esphome.github.io/esp-web-tools/)) |
| `docs/MANUAL.md` | User manual |
| `PROTOCOL.md` | Bluetooth protocol |
| `tools/wp_client.py` | Command-line client (read the list, push settings) |
| `tools/update_oui.py` | Rebuilds the bundled MAC vendor table from the IEEE registry |
| `test/` | Host tests (C), protocol tests, Home Assistant tests, a hostile-client hardware test |
| `.github/workflows/build.yml` | Tests, firmware build, web flasher publishing |
| `.github/workflows/validate.yml` | HACS and hassfest checks (the Marketplace requirements) |

# Manual

This manual takes you from a bare ESP32-C5 to presence detection in Home
Assistant. Plan on about ten minutes. You only ever touch the sensor once, to
flash it; everything afterwards, including changing which Wi-Fi it watches, is done in
Home Assistant.

**Contents:**
[What you need](#what-you-need) ·
[1 Flash](#1-flash-the-sensor) ·
[2 Install the integration](#2-install-the-home-assistant-integration) ·
[3 Pair](#3-pair-the-sensor) ·
[4 Use it](#4-use-it) ·
[Settings](#settings-reference) ·
[Tuning](#tuning-recipes) ·
[Updating and resetting](#updating-and-resetting) ·
[Troubleshooting](#troubleshooting) ·
[Privacy](#privacy-and-security) ·
[Building from source](#building-from-source)

## What you need

- An **ESP32-C5** board with a USB port (for example the ESP32-C5-DevKitC-1). Only the
  C5 works: it is the ESP32 with 5 GHz Wi-Fi.
- A computer with **Chrome, Edge or another Chromium browser** and a USB cable, for the
  one-time flashing.
- **Home Assistant** 2025.1 or newer (2026.11 or newer for the built-in Marketplace), with Bluetooth within reach of the sensor: either
  a Bluetooth adapter in the Home Assistant machine or an
  [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html)
  near the sensor. The sensor itself needs only USB power.
- Place the sensor where it can hear your access points well, typically central in the
  home. It does not join your Wi-Fi, so there is no Wi-Fi password anywhere in this setup.

## 1. Flash the sensor

1. Open the web flasher: **https://ctandi.github.io/esp32c5-wifi-presence-detector/**
2. Plug the C5 into your computer and click **Install firmware**.
3. Choose the board's serial port in the browser dialog (it is usually called
   *USB JTAG/serial debug unit*) and confirm. Leave *Erase device* off unless you want a
   clean start (see [Updating and resetting](#updating-and-resetting)).
4. When it says the installation is complete, click **Logs & Console**.

Within ten seconds the sensor prints this box:

```
==================== WI-FI PRESENCE SENSOR: PAIRING ====================
 In Home Assistant: Settings > Devices & services > Wi-Fi Presence Sensor
 (it is found automatically through Bluetooth) and enter this key:

3f9a…(64 characters)…c1d4

 Bluetooth address: AA:BB:CC:11:22:33
========================================================================
```

**Copy the key line.** The sensor made this key itself when it first started, and it is
unique to your sensor. It repeats every ten seconds until Home Assistant has paired.

Now the board can go anywhere with USB power (a phone charger is fine). You do not need
the computer again.

## 2. Install the Home Assistant integration

The integration is a community repository. You add it to the Marketplace once; after that it
installs and updates like any other integration.

**Home Assistant 2026.11 or newer (Marketplace)**, the easy way:

[![Open your Home Assistant instance and show the repository in the Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ctandi&repository=esp32c5-wifi-presence-detector&category=integration)

Or by hand:

1. *Settings → Marketplace*. Accept the warning the first time you open it.
2. *Add from link* (upper-right corner), enter `ctandi/esp32c5-wifi-presence-detector`, *Add*.
   The Marketplace asks you to connect GitHub if you have not: it shows a code, you enter it
   on github.com and approve (needed to add custom repositories and to check for updates;
   it gets no access to private repositories and no permission to change anything).
   If it asks for the type, choose *Integration*.
3. Open the repository, *Install*, confirm. The integration's setup page opens when Home
   Assistant can load it right away; if a restart is needed, a repair under
   *Settings → System → Repairs* offers it. In that case restart before step 3 of this manual.

**Home Assistant 2026.10 or older (HACS):** HACS → ⋮ → *Custom repositories* → add
`https://github.com/ctandi/esp32c5-wifi-presence-detector`, type *Integration* → download
*Wi-Fi Presence Sensor* → restart Home Assistant.

**Without either:** copy the folder `custom_components/wifi_presence` from this
repository into the `custom_components` folder of your Home Assistant configuration (next to
`configuration.yaml`; create `custom_components` if it does not exist) and restart.

## 3. Pair the sensor

1. Open *Settings → Devices & services*. The sensor appears under **Discovered** as
   *Wi-Fi presence AA:BB:CC:11:22:33*: the **full Bluetooth address** printed in the box, so
   several sensors can be told apart. Click *Add*. If it does not appear, use *Add integration → Wi-Fi Presence Sensor*
   ([shortcut](https://my.home-assistant.io/redirect/config_flow_start/?domain=wifi_presence)).
2. Paste the **key** and continue. Home Assistant connects once to check the key.
3. Give the sensor a **name** (for example *Wi-Fi presence living room*; the default is its
   address) and enter **the name of your Wi-Fi** (the SSID). Add more than one if you have several
   networks or a guest network. Press Enter after each name. The country code is filled
   in from your Home Assistant setting. *Track all devices automatically* is explained in
   [Use it](#4-use-it). Everything under *Advanced settings* can stay as it is; see
   [Settings](#settings-reference).
4. Submit. Home Assistant sends the settings to the sensor over Bluetooth, and the sensor
   starts scanning at once. This also completes the pairing: the sensor stops repeating
   the key.

Within a minute the **Wi-Fi presence** device shows how many clients it hears.

## 4. Use it

You get three sensors and, for every Wi-Fi client the sensor has heard, a device tracker:

| Entity | What it tells you |
|--------|-------------------|
| *Clients present* | Number of devices currently connected to your Wi-Fi. The attribute `clients` lists them with signal strength. |
| *Access points watched* | How many of your access points (counting every band and mesh node) the sensor found. `0` means it has not found your Wi-Fi yet. |
| *Sensor uptime* | Seconds since the sensor started. |
| *Wi-Fi presence aa:bb:cc:dd:ee:ff* (tracker) | One per device, named after the **device's** address. `home` while that device is on your Wi-Fi, otherwise `not_home`. |

**Track everything, or choose.** A home network is full of TVs, plugs and lamps, so by
default the trackers start hidden (disabled) and only the ones you pick show up. If you
would rather have all of them:

- **Track all devices automatically** (*Configure*, or in the pairing dialog): every device
  the sensor hears gets an enabled tracker at once, and so does every device it hears in
  the future. Turning it on also enables the trackers that are only hidden by default. A
  tracker you switched off yourself stays off, so a single device can still be excluded
  (un-tick it in *Devices to track*, or disable the entity). Turning it off again leaves the
  trackers as they are; only new devices start hidden again.

To pick devices one by one:

1. Open *Settings → Devices & services → Wi-Fi Presence Sensor → Configure*.
2. In **Devices to track**, open the list. It shows every device the sensor has heard, the
   ones heard right now first, with their signal strength. Devices Home Assistant already knows
   by name (for example from the companion app or your router) are listed with that name.
   Tick your phone. If you cannot tell which one it is, put the phone right next to the
   sensor: it will be the strongest, or switch the phone's Wi-Fi off for a few minutes and
   see which entry disappears from the *Clients present* attribute.
3. Submit. The tracker of every ticked device is enabled at once (a `home` / `not_home`
   state within a few seconds), and the others stay hidden.
4. *Settings → People*: add that tracker to your **Person**. Your automations can use
   `person.you` as usual.

The list fills as the sensor hears devices, so a new phone shows up here after the next
check (30 seconds); open *Configure* again to add it. You can also enable or disable single
trackers in the usual entity settings; the list reflects that.

**Where to find them.** The integration page (*Settings → Devices & services → Wi-Fi
Presence Sensor*) lists the sensor as one device. The trackers are entities named *Wi-Fi
presence* plus the address of the device they follow, so searching *Settings → Entities*
for an address (or for *Wi-Fi presence*) finds them; use the *Entities* tab of the
integration, with disabled entities shown, to see all of them. If another integration
already knows a device by that address (a phone with the companion app, a router entry), Home
Assistant gives the tracker a small device of its own, named after the address; that is
why a few such entries can appear on the integration page. Development builds from before the first
release created a device per client, all named like the sensor; the integration removes
those when it starts.

Phones usually use a *private* Wi-Fi address per network. That address stays the same for
that network, so it works. If you set the phone to "rotate" the address, it looks like a
new device every time, and Wi-Fi presence cannot follow it.

**How fast is it?** A device counts as present after its third frame, and Home Assistant
asks every 30 seconds, so "home" arrives within about half a minute. "Away" is
deliberately slower: a phone that is asleep talks rarely, so the sensor waits 5 minutes
(*Keep a device present for*) before it believes the phone has left. Together with the
polling this means "away" after 5 to 5½ minutes. Both numbers are settings.

## The status LED

On the Seeed XIAO ESP32-C5 the **yellow** LED shows what the sensor is doing:

| What you see | What it means |
|--------------|---------------|
| Dark | The sensor is starting, or has no power |
| **Slow blink** (once a second) | The firmware is running, but Home Assistant is not connected: not paired yet, or Home Assistant has not polled for a while |
| **Steady on** | Home Assistant is connected: it polled recently |
| **Short flash** (the LED goes dark for a moment) | Activity: an exchange with Home Assistant, or Wi-Fi traffic of your network being heard (at most a few flashes per second) |

"Recently" means within two and a half times Home Assistant's polling period (at least 90
seconds), so a slow polling period does not make the LED blink between polls. If Home
Assistant stops polling, the LED goes back to the slow blink after that time.

The **red** LED of the XIAO ESP32-C5 is the battery-charge indicator. It is wired to the
charger chip, not to a pin, so the firmware cannot switch it. It only lights while a
battery is charging.

If the LED is inverted (lit while it should be dark), or you want it off, change it when
building the firmware (`idf.py menuconfig` → *Wi-Fi Presence Sensor*: *Status LED*, its pin
and its polarity). The web-flasher build uses the XIAO ESP32-C5's yellow LED on GPIO27, lit
when the pin is low.

## Settings reference

Open them with *Settings → Devices & services → Wi-Fi Presence Sensor → Configure*. Changes
go to the sensor immediately and survive its restarts. If the sensor is out of reach
Home Assistant says so and keeps your old settings, so the two never disagree.

| Setting | Default | Range | What it does |
|---------|---------|-------|--------------|
| **Name** | *Wi-Fi presence* and the sensor's address | any text | What the sensor is called in Home Assistant (its device and entities). Rename it any time. |
| **Wi-Fi networks (SSIDs)** | none | 1 to 8 names | Devices of every access point announcing one of these names are tracked. The names are case-sensitive. Hidden networks cannot be found. |
| **Country code** | your HA country | 2 letters | Which 5 GHz channels the sensor may listen on. Use your real country. |
| **Track all devices automatically** | off | on / off | Enables the tracker of every device the sensor hears, now and in the future. See [Use it](#4-use-it). |
| *Frequency bands* | 2.4 and 5 GHz | both / 2.4 only / 5 only | Where to search for your network. If your Wi-Fi lives on one band only, choosing it makes the search faster. |
| *Search time per channel* | 200 ms | 120 to 1500 | How long the sensor listens on each channel while looking for your access points. Must be longer than one beacon (about 100 ms). Raise it if a weak access point is not found. **A full search takes about 80 times this value** (measured with 2.4 and 5 GHz in Germany: 12 s at 150 ms, 24 s at 300 ms), and **the sensor hears no devices while it searches**. The Wi-Fi driver recommends 360 ms and logs a harmless warning in the console when you use another value; the value is honoured. |
| *Listening time per channel* | 2000 ms | 200 to 30000 | When your access points are on several channels (2.4 and 5 GHz, mesh nodes) the sensor hops between them. This is how long it stays on one. Short hops cover all channels more evenly; long hops catch more of one channel. |
| *Search again every* | 600 s | 30 to 3600 | How often the sensor looks for your access points again, to follow a channel change. Sniffing pauses for the duration of each search (see *Search time per channel*: 16 s at the default), so raise this rather than lowering the search time if you want fewer gaps. |
| *Keep a device present for* | 300 s | 10 to 43200 | A device stays "home" this long after its last frame. This is your debounce against false "away", and the delay before a real "away". |
| *Frames needed to count* | 3 | 1 to 100 | How many frames a device must send before it counts as present. Guards against one stray frame. |
| *Minimum signal strength* | -100 dBm | -100 to -20 | Frames weaker than this are ignored. -100 hears everything. Raise it (try -80) to ignore devices far away or outside the house. |
| *Check the sensor every* | 30 s | 10 to 300 | How often Home Assistant reads the list. This is a Home Assistant setting, not a sensor setting. |

## Tuning recipes

- **"My phone says away at night, though it is home."** The phone sleeps and sends few
  frames. Raise *Keep a device present for* to 600 or 900 seconds.
- **"It takes too long to notice that I left."** Lower *Keep a device present for*
  (try 120 s) and *Check the sensor every* (try 15 s). Lower values mean more risk of a
  false "away" for sleeping devices.
- **"It lists a neighbour's phone as home."** That is only possible if it is connected to
  *your* network, since the sensor counts only devices talking to your access points.
  Check for a guest network name you do not use and remove it from the list.
- **"Far-away devices flicker."** Raise *Minimum signal strength* to -85 or -80.
- **"Some mesh nodes or a band are missing (Access points watched is too low)."** Raise
  *Search time per channel* to 400 to 600 ms, and make sure the sensor is placed centrally.
- **"I have a lot of channels and devices appear slowly."** Lower *Listening time per
  channel* to 1000 ms.

## Updating and resetting

**Update the firmware:** open the web flasher again and install. With *Erase device* **off**,
the sensor keeps its key and settings and Home Assistant does not notice.

**Factory reset / new key:** tick *Erase device* when installing. The sensor then creates a **new key**, prints it, and forgets its
settings. Home Assistant shows a re-authentication prompt on the
integration (*Settings → Devices & services*): paste the new key. The settings are stored in Home Assistant and are sent to
the sensor again automatically.

**Lost the key?** It is printed on every start. Plug the sensor into a computer and
open the web flasher's *Logs & Console* (or any serial terminal at 115200 baud), or just
re-flash with *Erase device* and pair again.

**Moving to a new Home Assistant:** install the integration, add the sensor and enter
the key from the console; set the Wi-Fi name again.

## Troubleshooting

**The sensor does not show up under Discovered.**
It is found by Bluetooth, so check that a Bluetooth adapter or ESPHome proxy is near
it and that the *Bluetooth* integration works in Home Assistant. The sensor advertises
every 100 to 150 ms, with a range like any BLE device (walls matter). Use *Add integration
→ Wi-Fi Presence Sensor* if discovery stays quiet. Make sure the integration is installed
and Home Assistant was restarted.

**"The key does not match."**
Copy the key again from the console, without spaces or line breaks (spaces and dashes are
tolerated). If you flashed with *Erase device* since you copied it, the key changed.

**"Could not reach the sensor over Bluetooth."**
Out of range of the adapter or proxy, or the sensor has no power. The sensor accepts one
connection at a time and drops it after 20 seconds, so a second program trying to talk to
it at the same moment (a phone app, a second Home Assistant) makes the first fail; try
again. ESPHome Bluetooth proxies have a limited number of connection slots; if you have
many Bluetooth devices, check the proxy's logs.

**Access points watched is 0.**
The sensor does not find your Wi-Fi. Is the name spelled exactly right, with the same
capitals? Is the network hidden? Does the country code match where you live? Is the
sensor in range of the access point? The console (see step 1) logs every scan: it lists the access points it matched to your names, so no `AP '…'` lines means no match.

**Clients present is 0 but the Wi-Fi is busy.**
The sensor counts devices that are *associated with your access points*. It needs a
few seconds per channel: after a settings change, give it a minute. Raising *Search time
per channel* helps if the access point count is lower than you expect. Devices connected to
a band the sensor cannot hear well (distance) are missed.

**The console shows `wifi:Error! Should use default passive scan time parameter for WiFi scan when Bluetooth is enabled!!!!!!`.**
Harmless. The Wi-Fi driver prints it at the start of every search whose *Search time per channel*
is not 360 ms (the default is 200 ms), because it would prefer its own default while Bluetooth
is on. The search runs normally and uses the time you set; this was checked on a real sensor
by timing the searches (150 ms: 12 s, 300 ms: 24 s). It is not an error of your setup, and
the message does not appear for the very first search after power-up. Using 360 ms silences
it, at the price of longer searches (28 s) during which nothing is heard.

**The console shows `disconnected (reason 531)` after every check.**
That is normal. 531 means "the other side ended the connection": Home Assistant connects,
reads the list, and hangs up, every 30 seconds. It is not an error and not a dropped
connection. What matters is that *Sensor uptime* keeps growing in Home Assistant.

**The sensors work, but nothing shows who is home.**
The device trackers are hidden until you choose them: *Configure → Devices to track* (see
[Use it](#4-use-it)). Until a device is ticked, you only see the three sensors.

**The board does not start after flashing; the console repeats `rst:0x7 (TG0_WDT_HPSYS)`.**
The chip is stuck in a state that a reset signal cannot clear. **Unplug the USB cable,
wait a few seconds, plug it in again.** Then it starts normally and nothing is lost. This happened
twice in roughly 30 forced resets during testing, with a firmware built on ESP-IDF v5.5.1; the
published firmware is built with a newer version (v5.5.6) that includes Espressif's
fixes for ESP32-C5 reset and radio coexistence problems (advisory AR2025-008), but
this specific case has not been confirmed as fixed. A power cycle always clears it.

**The browser shows no serial port.**
Use a Chromium-based browser on a computer (not a phone), a USB cable that carries
data (not charge-only), and the board's *USB* port (some boards have two; the one labelled
USB, not UART). On Windows 10 and newer no driver is needed. If it still does not appear,
hold the **BOOT** button while plugging the board in, then try again.

**No box appears in the console.**
Wait ten seconds. If the sensor has already paired you will not see the repeating box,
only the one printed at start-up; unplug and replug the board to see it again.

**I changed something and want to start over.**
Remove the integration in Home Assistant, flash with *Erase device*, and begin at step 3.

## Privacy and security

- **Nothing about your clients is broadcast.** The Bluetooth advertisement contains only a
  service identifier. Client addresses leave the sensor only inside an AES-256-GCM message.
  Anyone can connect to the sensor, but without the key they receive random-looking bytes.
- **The key never leaves the sensor and Home Assistant.** It is generated on the sensor,
  shown on its USB console, and stored in Home Assistant. It is not in the firmware
  (every sensor has its own) and not on the web page.
- **Only Home Assistant can change the settings.** A settings command must be sealed with a
  per-connection key derived from the pairing key. Forged, altered or replayed commands are
  ignored (this was tested against a real sensor: `test/hardware/command_security.py`).
- **Not protected:** someone with physical access to the sensor can read the key from its
  flash (the same is true for an ESPHome API key), and a Wi-Fi sniffer next door sees the
  same frames the sensor does. A stranger in Bluetooth range can see that a sensor exists
  and can occupy its single connection briefly.
- **In Home Assistant, the MAC addresses of your clients are data.** The *Clients present*
  sensor lists every address as an attribute, and Home Assistant's recorder stores it in
  its history. If you do not want that, add this to `configuration.yaml`:

  ```yaml
  recorder:
    exclude:
      entities:
        - sensor.wi_fi_presence_63_86_clients_present   # use your entity id
  ```

  The trackers you enabled are stored as usual.

## Building from source

You do not need this to use the sensor. To change the firmware you need
[ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/v5.5.6/esp32c5/get-started/)
5.5.2 or newer (5.5.6 is what the published build uses; the C5 needs at least 5.4).

```sh
idf.py set-target esp32c5
idf.py build
idf.py -p /dev/ttyACM0 flash monitor      # prints the pairing box
```

There is nothing to configure: no SSID, no key, no secrets in the build. The only build
options (`idf.py menuconfig` → *Wi-Fi Presence Sensor*) are the client table size, the
Bluetooth name, the connection timeout, and the status LED (on or off, pin, polarity).

**Tests:**

| What | How |
|------|-----|
| C logic: frames, settings codec, report, fragments, LED timing (with sanitizers) | `test/run_host_tests.sh` |
| Protocol, settings, session logic, against a simulated sensor and a firmware-produced known-answer vector | `python3 -m unittest discover -s test` (needs `cryptography`, `bleak`) |
| Home Assistant integration: config flow, options, reauth, entities | `pip install pytest-homeassistant-custom-component && python test/ha/install_requirements.py`, then `pytest` |
| A real sensor, as a hostile client: forged, replayed, tampered and malformed commands | `python3 test/hardware/command_security.py --key <key>` (needs a Bluetooth adapter) |
| A real sensor, by hand | `tools/wp_client.py --key <key>`; add `--ssid MyWiFi` to push settings |

CI (`.github/workflows/build.yml`) runs the tests, builds the firmware with ESP-IDF
v5.5.6 and publishes the web flasher from the `main` branch to GitHub Pages.
For the protocol see [PROTOCOL.md](../PROTOCOL.md).

**Publishing the web flasher from your own fork:** in the repository on GitHub, *Settings →
Pages → Source: GitHub Actions*. The next push to `main` builds and publishes it to
`https://<user>.github.io/<repository>/`.

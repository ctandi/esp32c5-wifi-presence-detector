"""Constants for the Wi-Fi presence integration."""

from datetime import timedelta

DOMAIN = "wifi_presence"

# config entry data
CONF_KEY = "key"

# config entry options (the sensor's settings, pushed to it over Bluetooth)
CONF_SSIDS = "ssids"
CONF_COUNTRY = "country"
CONF_BAND = "band"
CONF_SCAN_DWELL = "scan_dwell_ms"
CONF_HOP = "hop_ms"
CONF_RESCAN = "rescan_s"
CONF_HOLD = "hold_s"
CONF_MIN_FRAMES = "min_frames"
CONF_MIN_RSSI = "min_rssi"
# kept in Home Assistant only
CONF_POLL_INTERVAL = "poll_interval_s"
CONF_TRACK_ALL = "track_all_devices"
# not stored: the form field that enables and disables device trackers
CONF_TRACKED = "tracked"
SECTION_ADVANCED = "advanced"

BAND_OPTIONS = {"both": 0, "2g": 1, "5g": 2}

# Events fired when a device becomes present or leaves, shown in the sensor's activity log.
EVENT_CLIENT_ARRIVED = "wifi_presence_client_arrived"
EVENT_CLIENT_LEFT = "wifi_presence_client_left"
# While the sensor has been running for less than this, its list is still filling up after a
# start: changes are noted silently instead of flooding the activity log.
WARMUP_S = 120

# How often Home Assistant asks the sensor for its client list.
DEFAULT_POLL_INTERVAL = 30
POLL_INTERVAL_RANGE = (10, 300)
# Give the sensor this long to answer a request.
RESPONSE_TIMEOUT = 10.0


def poll_interval(seconds: int) -> timedelta:
    """The polling period as a timedelta."""
    return timedelta(seconds=seconds)

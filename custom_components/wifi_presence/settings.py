"""Translate between the config entry's options and the sensor's settings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import (
    BAND_OPTIONS,
    CONF_BAND,
    CONF_COUNTRY,
    CONF_HOLD,
    CONF_HOP,
    CONF_MIN_FRAMES,
    CONF_MIN_RSSI,
    CONF_POLL_INTERVAL,
    CONF_RESCAN,
    CONF_SCAN_DWELL,
    CONF_SSIDS,
    DEFAULT_POLL_INTERVAL,
)
from .protocol import Config

_BAND_NAMES = {number: name for name, number in BAND_OPTIONS.items()}


def config_from_options(options: Mapping[str, Any], default_country: str = "DE") -> Config:
    """Settings for the sensor. Missing options fall back to the defaults."""
    base = Config()
    return Config(
        ssids=tuple(options.get(CONF_SSIDS, base.ssids)),
        country=options.get(CONF_COUNTRY, default_country),
        band=BAND_OPTIONS.get(options.get(CONF_BAND, "both"), base.band),
        scan_dwell_ms=int(options.get(CONF_SCAN_DWELL, base.scan_dwell_ms)),
        hop_ms=int(options.get(CONF_HOP, base.hop_ms)),
        rescan_s=int(options.get(CONF_RESCAN, base.rescan_s)),
        min_frames=int(options.get(CONF_MIN_FRAMES, base.min_frames)),
        hold_s=int(options.get(CONF_HOLD, base.hold_s)),
        min_rssi=int(options.get(CONF_MIN_RSSI, base.min_rssi)),
    )


def options_from_config(config: Config, poll_interval_s: int) -> dict[str, Any]:
    """The flat options dict stored in the config entry."""
    return {
        CONF_SSIDS: list(config.ssids),
        CONF_COUNTRY: config.country,
        CONF_BAND: _BAND_NAMES[config.band],
        CONF_SCAN_DWELL: config.scan_dwell_ms,
        CONF_HOP: config.hop_ms,
        CONF_RESCAN: config.rescan_s,
        CONF_HOLD: config.hold_s,
        CONF_MIN_FRAMES: config.min_frames,
        CONF_MIN_RSSI: config.min_rssi,
        CONF_POLL_INTERVAL: poll_interval_s,
    }


def poll_interval_from_options(options: Mapping[str, Any]) -> int:
    """Seconds between polls."""
    return int(options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))

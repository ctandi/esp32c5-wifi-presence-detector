"""Polls the sensor on a schedule and keeps its settings in sync."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import PollError, async_poll
from . import oui
from .const import DOMAIN, EVENT_CLIENT_ARRIVED, EVENT_CLIENT_LEFT, WARMUP_S, poll_interval
from .labels import known_name
from .protocol import AuthError, Report
from .session import ConfigRejected
from .settings import config_from_options, poll_interval_from_options

_LOGGER = logging.getLogger(__name__)

type WifiPresenceConfigEntry = ConfigEntry[WifiPresenceCoordinator]


class WifiPresenceCoordinator(DataUpdateCoordinator[Report]):
    """Holds the latest client list."""

    config_entry: WifiPresenceConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: WifiPresenceConfigEntry,
        address: str,
        psk: bytes,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Wi-Fi presence {address}",
            update_interval=poll_interval(poll_interval_from_options(entry.options)),
        )
        self.address = address
        self._psk = psk
        self._present: set[str] | None = None  # who was there at the last poll
        self._last_uptime: int | None = None

    async def _async_update_data(self) -> Report:
        # The settings travel with every poll: the sensor only gets them when its
        # own differ, so this also repairs a sensor that lost them.
        settings = config_from_options(self.config_entry.options, self.hass.config.country or "DE")
        try:
            result = await async_poll(
                self.hass, self.address, self._psk, self.config_entry.title, settings
            )
        except AuthError as err:
            raise ConfigEntryAuthFailed(
                "the sensor rejected the key; it was probably flashed again, enter its new key"
            ) from err
        except ConfigRejected as err:
            raise UpdateFailed(str(err)) from err
        except PollError as err:
            raise UpdateFailed(str(err)) from err
        if result.config_applied:
            _LOGGER.info("sent the settings to %s", self.address)
        self._announce_changes(result.report)
        return result.report

    def _sensor_device_id(self) -> str | None:
        """The registry id of the sensor's device: what ties an event to its activity log."""
        for device in dr.async_get(self.hass).async_get_devices(identifiers={(DOMAIN, self.address)}):
            if device.config_entry_id == self.config_entry.entry_id:
                return device.id
        return None

    def _announce_changes(self, report: Report) -> None:
        """Fire an event for every device that arrived or left since the last poll.

        These show up in the sensor's activity log and can trigger automations. Nothing is
        announced for the first poll, after the sensor restarted, or while its list is still
        filling up after a start: that would only report a restart as everybody leaving and
        arriving. A failed poll changes nothing, so an unreachable sensor does not make
        everybody "leave".
        """
        now = {client.mac: client for client in report.clients}
        restarted = self._last_uptime is not None and report.uptime_s < self._last_uptime
        self._last_uptime = report.uptime_s
        previous, self._present = self._present, set(now)
        if previous is None or restarted or report.uptime_s < WARMUP_S:
            return

        device_id = self._sensor_device_id()
        for mac in sorted(set(now) - previous):
            self._fire(EVENT_CLIENT_ARRIVED, device_id, mac, rssi=now[mac].rssi)
        for mac in sorted(previous - set(now)):
            self._fire(EVENT_CLIENT_LEFT, device_id, mac)

    def _fire(self, event: str, device_id: str | None, mac: str, **extra: int) -> None:
        self.hass.bus.async_fire(
            event,
            {
                "device_id": device_id,
                "entry_id": self.config_entry.entry_id,
                "mac": mac,
                "vendor": oui.lookup(mac),
                "name": known_name(self.hass, self.config_entry, mac),
                **extra,
            },
        )

"""Polls the sensor on a schedule and keeps its settings in sync."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import PollError, async_poll
from .const import poll_interval
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
        return result.report

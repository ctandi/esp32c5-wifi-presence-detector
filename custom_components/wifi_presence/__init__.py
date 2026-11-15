"""Wi-Fi presence sensor (ESP32-C5) read over encrypted Bluetooth."""

from __future__ import annotations

from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant

from .const import CONF_KEY
from .coordinator import WifiPresenceConfigEntry, WifiPresenceCoordinator
from .protocol import parse_key

PLATFORMS = [Platform.SENSOR, Platform.DEVICE_TRACKER]


async def async_setup_entry(hass: HomeAssistant, entry: WifiPresenceConfigEntry) -> bool:
    """Set up a sensor from a config entry."""
    coordinator = WifiPresenceCoordinator(
        hass, entry, entry.data[CONF_ADDRESS], parse_key(entry.data[CONF_KEY])
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Changed settings (options flow) are pushed to the sensor by the next poll.
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass: HomeAssistant, entry: WifiPresenceConfigEntry) -> None:
    """New options: reload so the polling period and settings take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: WifiPresenceConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

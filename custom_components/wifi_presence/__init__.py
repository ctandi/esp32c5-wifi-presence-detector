"""Wi-Fi presence sensor (ESP32-C5) read over encrypted Bluetooth."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import CONF_KEY
from .coordinator import WifiPresenceConfigEntry, WifiPresenceCoordinator
from .protocol import parse_key

PLATFORMS = [Platform.SENSOR, Platform.DEVICE_TRACKER]

_LOGGER = logging.getLogger(__name__)


def _remove_legacy_client_devices(hass: HomeAssistant, entry: WifiPresenceConfigEntry) -> None:
    """Drop the per-client devices that pre-release builds created.

    Each tracker used to get a device of its own, named like the sensor, so the
    integration page listed the sensor once per client. Trackers are plain entities
    now (Home Assistant links a tracker to another integration's device by itself).
    Only devices that are clearly ours are touched: same config entry, no identifier,
    named like the sensor, known by a MAC address only.
    """
    devices = dr.async_get(hass)
    entities = er.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        if (
            device.identifiers
            or not device.connections
            or any(kind != dr.CONNECTION_NETWORK_MAC for kind, _ in device.connections)
            or (device.name_by_user is None and device.name != entry.title)
        ):
            continue
        for reg in er.async_entries_for_device(entities, device.id, include_disabled_entities=True):
            if reg.config_entry_id == entry.entry_id and reg.domain == "device_tracker":
                entities.async_update_entity(reg.entity_id, device_id=None)
        if not er.async_entries_for_device(entities, device.id, include_disabled_entities=True):
            devices.async_remove_device(device.id)
            _LOGGER.debug("removed the leftover device %s", device.id)


async def async_setup_entry(hass: HomeAssistant, entry: WifiPresenceConfigEntry) -> bool:
    """Set up a sensor from a config entry."""
    _remove_legacy_client_devices(hass, entry)
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

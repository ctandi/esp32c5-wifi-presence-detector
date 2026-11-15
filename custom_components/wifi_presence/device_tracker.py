"""One device tracker per Wi-Fi client the sensor has ever heard.

Trackers start disabled (HA's default for scanned network clients), so hearing
every device on the network does not flood the entity list. Enable the ones you
care about, for example your phone, and assign them to a person.
"""

from __future__ import annotations

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_TRACK_ALL
from .coordinator import WifiPresenceConfigEntry, WifiPresenceCoordinator
from .labels import mac_with_vendor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WifiPresenceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create trackers for known clients and for new ones as they appear."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    # Clients seen before a restart keep their (possibly enabled) tracker, so
    # they show "away" instead of vanishing while they are not around.
    prefix = f"{entry.entry_id}_"
    for reg_entry in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if reg_entry.domain == "device_tracker" and reg_entry.unique_id.startswith(prefix):
            known.add(reg_entry.unique_id.removeprefix(prefix))
    async_add_entities(WifiClientTracker(coordinator, entry, mac) for mac in sorted(known))

    @callback
    def _add_new_clients() -> None:
        new = {c.mac for c in coordinator.data.clients} - known
        if new:
            known.update(new)
            async_add_entities(WifiClientTracker(coordinator, entry, mac) for mac in sorted(new))

    _add_new_clients()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_clients))


class WifiClientTracker(CoordinatorEntity[WifiPresenceCoordinator], ScannerEntity):
    """A Wi-Fi client: home while the sensor hears it, away otherwise."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: WifiPresenceCoordinator,
        entry: WifiPresenceConfigEntry,
        mac: str,
    ) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._unique_id = f"{entry.entry_id}_{mac}"
        self._attr_mac_address = mac
        # "Wi-Fi presence AA:BB:CC:11:22:33 (Vendor)"; no vendor, nothing added
        self._attr_name = f"Wi-Fi presence {mac_with_vendor(mac)}"
        # No device_info on purpose: ScannerEntity manages the device itself and links the
        # tracker to a device that another integration already registered for this MAC.

    @property
    def suggested_object_id(self) -> str:
        """Keep the entity id short and stable: the address only, never the vendor."""
        return f"Wi-Fi presence {self._mac}"

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Start enabled only if the user asked to track every device."""
        return bool(self.coordinator.config_entry.options.get(CONF_TRACK_ALL, False))

    @property
    def unique_id(self) -> str:
        """Unique per sensor, so two sensors can hear the same client."""
        return self._unique_id

    @property
    def is_connected(self) -> bool:
        """True while the sensor lists this client."""
        return any(c.mac == self._mac for c in self.coordinator.data.clients)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Signal strength and age of the last frame."""
        for c in self.coordinator.data.clients:
            if c.mac == self._mac:
                return {"rssi": c.rssi, "last_heard_s": c.age_s}
        return {}

"""Shared device description."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WifiPresenceCoordinator


class WifiPresenceEntity(CoordinatorEntity[WifiPresenceCoordinator]):
    """Base for the sensor's own entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WifiPresenceCoordinator) -> None:
        super().__init__(coordinator)
        address = coordinator.address
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            name=coordinator.config_entry.title,
            manufacturer="DIY",
            model="ESP32-C5 Wi-Fi presence sensor",
        )

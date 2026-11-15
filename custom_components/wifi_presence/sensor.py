"""Summary sensors of the Wi-Fi presence sensor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import WifiPresenceConfigEntry, WifiPresenceCoordinator
from .entity import WifiPresenceEntity
from .protocol import Report


@dataclass(frozen=True, kw_only=True)
class WifiPresenceSensorDescription(SensorEntityDescription):
    """Describes one sensor."""

    value_fn: Callable[[Report], int]


SENSORS = (
    WifiPresenceSensorDescription(
        key="clients",
        name="Clients present",
        icon="mdi:wifi",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda report: len(report.clients),
    ),
    WifiPresenceSensorDescription(
        key="access_points",
        name="Access points watched",
        icon="mdi:access-point",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda report: report.ap_count,
    ),
    WifiPresenceSensorDescription(
        key="uptime",
        name="Sensor uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda report: report.uptime_s,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WifiPresenceConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(WifiPresenceSensor(coordinator, desc) for desc in SENSORS)


class WifiPresenceSensor(WifiPresenceEntity, SensorEntity):
    """One summary value."""

    entity_description: WifiPresenceSensorDescription

    def __init__(
        self,
        coordinator: WifiPresenceCoordinator,
        description: WifiPresenceSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"

    @property
    def native_value(self) -> int | None:
        """Return the value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """List the clients on the main sensor."""
        if self.entity_description.key != "clients":
            return None
        report = self.coordinator.data
        return {
            "clients": [
                {"mac": c.mac, "rssi": c.rssi, "last_heard_s": c.age_s}
                for c in report.clients
            ],
            "truncated": report.truncated,
        }

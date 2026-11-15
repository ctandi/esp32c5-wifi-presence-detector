"""How a Wi-Fi client is named in lists and in the activity log."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import oui


def known_name(hass: HomeAssistant, entry: ConfigEntry, mac: str) -> str | None:
    """The name another integration gave the device with this MAC, if any.

    Several devices can share a MAC (one per integration). Ours are named after the MAC,
    so only another integration's device carries a useful name.
    """
    names = [
        device.name_by_user or device.name
        for device in dr.async_get(hass).async_get_devices(
            connections={(dr.CONNECTION_NETWORK_MAC, mac)}
        )
        if device.config_entry_id != entry.entry_id
    ]
    return next((name for name in names if name and name != mac), None)


def mac_with_vendor(mac: str) -> str:
    """"AA:BB:CC:11:22:33 (Vendor)", or just the address when no vendor is known.

    Nothing is added for addresses without a vendor, not even a placeholder.
    """
    vendor = oui.lookup(mac)
    return f"{mac} ({vendor})" if vendor else mac


def log_name(mac: str, name: str | None, vendor: str | None) -> str:
    """The subject of an activity log entry."""
    inside = f"{mac}, {vendor}" if vendor else mac
    if name:
        return f"{name} ({inside})"
    return f"{mac} ({vendor})" if vendor else mac

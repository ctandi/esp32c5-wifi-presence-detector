"""Talk to the sensor through whichever Bluetooth adapter or proxy hears it."""

from __future__ import annotations

import asyncio
import logging

from bleak import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import RESPONSE_TIMEOUT
from .protocol import AuthError, Config, ProtocolError
from .session import ConfigRejected, SessionResult, run_session

_LOGGER = logging.getLogger(__name__)

# The sensor accepts one connection at a time: never talk to it twice at once.
_LOCKS: dict[str, asyncio.Lock] = {}


class PollError(Exception):
    """The sensor could not be reached or did not answer."""


async def async_poll(
    hass: HomeAssistant,
    address: str,
    psk: bytes,
    name: str,
    config: Config | None = None,
    *,
    force: bool = False,
) -> SessionResult:
    """Connect, read the client list and push `config` if the sensor differs.

    Raises AuthError when the key is wrong, ConfigRejected when the sensor
    refuses the settings, PollError for everything else.
    """
    async with _LOCKS.setdefault(address, asyncio.Lock()):
        return await _poll(hass, address, psk, name, config, force)


async def _poll(
    hass: HomeAssistant,
    address: str,
    psk: bytes,
    name: str,
    config: Config | None,
    force: bool,
) -> SessionResult:
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise PollError("the sensor is not in range of any Bluetooth adapter or proxy")

    try:
        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, name, max_attempts=3
        )
    except (BleakError, TimeoutError) as err:
        raise PollError(f"could not connect: {err}") from err

    try:
        return await run_session(client, psk, config, force=force, timeout=RESPONSE_TIMEOUT)
    except (AuthError, ConfigRejected):
        raise
    except (BleakError, ProtocolError, TimeoutError) as err:
        raise PollError(f"bad answer from the sensor: {err!r}") from err
    finally:
        try:
            await client.disconnect()
        except (BleakError, TimeoutError):  # already gone, nothing to clean up
            _LOGGER.debug("disconnect from %s failed", address, exc_info=True)

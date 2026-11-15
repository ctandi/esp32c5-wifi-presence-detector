"""One conversation with the sensor over an already connected BleakClient.

Used by the Home Assistant integration and by tools/wp_client.py, so both
speak exactly the same protocol. No Home Assistant imports.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from bleak import BleakError

from .protocol import (
    CMD_SET_CONFIG,
    CMD_UUID,
    CTRL_UUID,
    DATA_UUID,
    STATUS_OK,
    Config,
    ProtocolError,
    Reassembler,
    Report,
    config_crc,
    encode_config,
    fragment,
    new_request,
    open_ack,
    open_report_message,
    parse_report,
    seal_command,
)

DEFAULT_MTU = 23
_MAX_WRITE = 244  # what the sensor accepts in one write, header included


class ConfigRejected(ProtocolError):
    """The sensor refused the new settings."""


@dataclass(frozen=True)
class SessionResult:
    """What one conversation produced."""

    report: Report
    config_applied: bool  # the settings were (re)sent and the sensor confirmed them


async def run_session(
    client,
    psk: bytes,
    config: Config | None = None,
    *,
    force: bool = False,
    timeout: float = 10.0,
) -> SessionResult:
    """Ask for the client list and, if needed, push settings.

    The settings are sent when they differ from what the sensor reports
    (compared by CRC), or always with `force`. Raises AuthError for a wrong key,
    ConfigRejected if the sensor refuses the settings, ProtocolError for other
    protocol problems and TimeoutError when the sensor stops answering.
    """
    reassembler = Reassembler()
    inbox: asyncio.Queue[bytes | Exception] = asyncio.Queue()

    def _on_data(_char, data: bytearray) -> None:
        try:
            message = reassembler.feed(bytes(data))
        except ProtocolError as err:
            inbox.put_nowait(err)
            return
        if message is not None:
            inbox.put_nowait(message)

    async def _next_message() -> bytes:
        item = await asyncio.wait_for(inbox.get(), timeout)
        if isinstance(item, Exception):
            raise item
        return item

    await client.start_notify(DATA_UUID, _on_data)
    try:
        return await _converse(client, psk, config, force, _next_message)
    finally:
        try:
            await client.stop_notify(DATA_UUID)  # lets the same connection be used again
        except (BleakError, EOFError, OSError, TimeoutError):
            pass  # the link may already be gone; nothing to undo


async def _converse(client, psk, config, force, _next_message) -> SessionResult:
    """The request/response exchange, with notifications already on."""
    nonce, request = new_request()
    await client.write_gatt_char(CTRL_UUID, request, response=True)
    key, plain = open_report_message(psk, nonce, await _next_message())
    report = parse_report(plain)

    if config is None:
        return SessionResult(report, False)
    blob = encode_config(config)
    expected_crc = config_crc(blob)
    if report.config_crc == expected_crc and not force:
        return SessionResult(report, False)

    counter = 1
    message = seal_command(key, counter, CMD_SET_CONFIG, blob)
    mtu = getattr(client, "mtu_size", DEFAULT_MTU) or DEFAULT_MTU
    per_chunk = max(DEFAULT_MTU - 3, min(mtu - 3, _MAX_WRITE)) - 1
    for fragment_ in fragment(message, per_chunk):
        await client.write_gatt_char(CMD_UUID, fragment_, response=True)

    ack = open_ack(key, counter, await _next_message())
    if ack.status != STATUS_OK:
        raise ConfigRejected(f"the sensor refused the settings (status {ack.status})")
    if ack.config_crc != expected_crc:
        raise ConfigRejected("the sensor confirmed different settings than were sent")
    return SessionResult(report, True)

"""Wire protocol of the C5 Wi-Fi presence sensor (see PROTOCOL.md).

Pure Python, no Home Assistant imports, so the integration, the command line
tool and the tests all share it.
"""

from __future__ import annotations

from dataclasses import dataclass
import hmac as _hmac
import hashlib
import os
import struct
import zlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SERVICE_UUID = "6e1d0001-5a3c-4f1e-9b7a-0c2d8e4f1a60"
CTRL_UUID = "6e1d0002-5a3c-4f1e-9b7a-0c2d8e4f1a60"
DATA_UUID = "6e1d0003-5a3c-4f1e-9b7a-0c2d8e4f1a60"
CMD_UUID = "6e1d0004-5a3c-4f1e-9b7a-0c2d8e4f1a60"

VERSION = 1  # message framing
REPORT_VERSION = 2
KEY_LEN = 32
NONCE_LEN = 16
TAG_LEN = 16
_LABEL = b"wifi-presence v1 session"
_REPORT_HDR = struct.Struct(">BBIBIB")  # version, flags, uptime_s, ap_count, config_crc, n
_CMSG_HDR = struct.Struct(">BI")  # version, counter
DIR_DEVICE_TO_CLIENT = 0
DIR_CLIENT_TO_DEVICE = 1
CMD_SET_CONFIG = 0x01
ACK_SET_CONFIG = 0xA1
STATUS_OK = 0
STATUS_INVALID = 1
STATUS_STORAGE = 2
_ENTRY = struct.Struct(">6sbH")  # mac, rssi, age_s
FLAG_TRUNCATED = 0x01
MAX_FRAGMENTS = 128


class ProtocolError(Exception):
    """The peer sent something that is not valid protocol."""


class AuthError(ProtocolError):
    """The message did not authenticate: wrong key or tampered data."""


@dataclass(frozen=True)
class Client:
    """One Wi-Fi client heard by the sensor."""

    mac: str
    rssi: int
    age_s: int


@dataclass(frozen=True)
class Report:
    """The decoded client list."""

    uptime_s: int
    ap_count: int
    truncated: bool
    clients: tuple[Client, ...]
    config_crc: int = 0  # CRC-32 of the settings in force, 0 = none stored yet


def parse_key(text: str) -> bytes:
    """Turn 64 hex digits into the key. Raises ValueError otherwise."""
    text = "".join(ch for ch in text if not ch.isspace() and ch not in "-:")
    if len(text) != KEY_LEN * 2:
        raise ValueError("the key must be 64 hex digits")
    return bytes.fromhex(text)  # raises ValueError for anything that is not hex


def new_request() -> tuple[bytes, bytes]:
    """Return (client_nonce, bytes to write to CTRL)."""
    nonce = os.urandom(NONCE_LEN)
    return nonce, bytes([VERSION]) + nonce


def derive_key(psk: bytes, client_nonce: bytes, dev_nonce: bytes) -> bytes:
    """Session key, unique for every request/response pair."""
    return _hmac.new(psk, _LABEL + client_nonce + dev_nonce, hashlib.sha256).digest()


def make_iv(direction: int, counter: int) -> bytes:
    """GCM nonce: direction byte, 7 zero bytes, 32-bit big-endian counter."""
    return bytes([direction]) + bytes(7) + struct.pack(">I", counter)


def seal(psk: bytes, client_nonce: bytes, dev_nonce: bytes, plaintext: bytes) -> bytes:
    """Build a report message the way the firmware does (used by the tests)."""
    header = bytes([VERSION]) + dev_nonce
    key = derive_key(psk, client_nonce, dev_nonce)
    iv = make_iv(DIR_DEVICE_TO_CLIENT, 0)
    return header + AESGCM(key).encrypt(iv, plaintext, header)


def open_report_message(psk: bytes, client_nonce: bytes, message: bytes) -> tuple[bytes, bytes]:
    """Verify and decrypt a report message.

    Returns (session key, plaintext); the session key seals the commands that
    follow. Raises ProtocolError or AuthError.
    """
    if len(message) < 1 + NONCE_LEN + TAG_LEN:
        raise ProtocolError("message too short")
    if message[0] != VERSION:
        raise ProtocolError(f"unsupported message version {message[0]}")
    header = message[: 1 + NONCE_LEN]
    dev_nonce = message[1 : 1 + NONCE_LEN]
    key = derive_key(psk, client_nonce, dev_nonce)
    try:
        plain = AESGCM(key).decrypt(make_iv(DIR_DEVICE_TO_CLIENT, 0), message[1 + NONCE_LEN :], header)
    except InvalidTag as err:
        raise AuthError("authentication failed (wrong key?)") from err
    return key, plain


def open_message(psk: bytes, client_nonce: bytes, message: bytes) -> bytes:
    """Like open_report_message, plaintext only."""
    return open_report_message(psk, client_nonce, message)[1]


def seal_command(key: bytes, counter: int, command: int, payload: bytes = b"") -> bytes:
    """Client -> device message: version || counter || AES-GCM(command || payload).

    `counter` must be higher than the previous one of this session (start at 1).
    """
    if not 0 < counter <= 0xFFFFFFFF:
        raise ValueError("counter out of range")
    header = _CMSG_HDR.pack(VERSION, counter)
    iv = make_iv(DIR_CLIENT_TO_DEVICE, counter)
    return header + AESGCM(key).encrypt(iv, bytes([command]) + payload, header)


def open_command(key: bytes, message: bytes) -> tuple[int, int, bytes]:
    """Device side of seal_command (used by the tests): (counter, command, payload)."""
    if len(message) < _CMSG_HDR.size + 1 + TAG_LEN:
        raise ProtocolError("command too short")
    version, counter = _CMSG_HDR.unpack_from(message)
    if version != VERSION:
        raise ProtocolError(f"unsupported message version {version}")
    try:
        plain = AESGCM(key).decrypt(
            make_iv(DIR_CLIENT_TO_DEVICE, counter), message[_CMSG_HDR.size :], message[: _CMSG_HDR.size]
        )
    except InvalidTag as err:
        raise AuthError("command authentication failed") from err
    return counter, plain[0], plain[1:]


@dataclass(frozen=True)
class Ack:
    """The device's answer to a SET_CONFIG command."""

    status: int
    config_crc: int


def seal_ack(key: bytes, counter: int, status: int, config_crc: int) -> bytes:
    """Device -> client acknowledgement (used by the tests)."""
    header = _CMSG_HDR.pack(VERSION, counter)
    plain = struct.pack(">BBI", ACK_SET_CONFIG, status, config_crc)
    return header + AESGCM(key).encrypt(make_iv(DIR_DEVICE_TO_CLIENT, counter), plain, header)


def open_ack(key: bytes, counter: int, message: bytes) -> Ack:
    """Verify and decode the acknowledgement of command `counter`."""
    if len(message) != _CMSG_HDR.size + 6 + TAG_LEN:
        raise ProtocolError("acknowledgement has the wrong length")
    version, got = _CMSG_HDR.unpack_from(message)
    if version != VERSION or got != counter:
        raise ProtocolError("acknowledgement does not belong to this command")
    try:
        plain = AESGCM(key).decrypt(
            make_iv(DIR_DEVICE_TO_CLIENT, counter), message[_CMSG_HDR.size :], message[: _CMSG_HDR.size]
        )
    except InvalidTag as err:
        raise AuthError("acknowledgement authentication failed") from err
    kind, status, crc = struct.unpack(">BBI", plain)
    if kind != ACK_SET_CONFIG:
        raise ProtocolError(f"unexpected acknowledgement type 0x{kind:02x}")
    return Ack(status=status, config_crc=crc)


# ---- settings -----------------------------------------------------------

BAND_BOTH = 0
BAND_2G = 1
BAND_5G = 2

# The same limits and defaults as main/wp_config.h.
SCAN_DWELL_RANGE = (120, 1500)
HOP_RANGE = (200, 30000)
RESCAN_RANGE = (30, 3600)
MIN_FRAMES_RANGE = (1, 100)
HOLD_RANGE = (10, 43200)
MIN_RSSI_RANGE = (-100, -20)
MAX_SSIDS = 8
MAX_SSID_BYTES = 32
_CFG_HDR = struct.Struct(">BB2sHHHBHbB")  # ver, band, country, dwell, hop, rescan, frames, hold, rssi, n
CONFIG_VERSION = 1


@dataclass(frozen=True)
class Config:
    """What the sensor scans for and how it decides who is present."""

    ssids: tuple[str, ...] = ()
    country: str = "DE"
    band: int = BAND_BOTH
    scan_dwell_ms: int = 200  # passive AP scan, per channel
    hop_ms: int = 2000  # sniffing, per channel, when the APs are on several channels
    rescan_s: int = 600  # between AP scans
    min_frames: int = 3  # frames before a client counts as present
    hold_s: int = 300  # a client stays present this long after its last frame
    min_rssi: int = -100  # ignore frames weaker than this (dBm)

    def validate(self) -> None:
        """Raise ValueError (message = the offending field) if something is out of range."""
        if self.band not in (BAND_BOTH, BAND_2G, BAND_5G):
            raise ValueError("band")
        if len(self.country) != 2 or not all("A" <= ch <= "Z" for ch in self.country):
            raise ValueError("country")
        for name, rng in (
            ("scan_dwell_ms", SCAN_DWELL_RANGE),
            ("hop_ms", HOP_RANGE),
            ("rescan_s", RESCAN_RANGE),
            ("min_frames", MIN_FRAMES_RANGE),
            ("hold_s", HOLD_RANGE),
            ("min_rssi", MIN_RSSI_RANGE),
        ):
            if not rng[0] <= getattr(self, name) <= rng[1]:
                raise ValueError(name)
        if len(self.ssids) > MAX_SSIDS:
            raise ValueError("ssids")
        for ssid in self.ssids:
            raw = ssid.encode()
            if not 1 <= len(raw) <= MAX_SSID_BYTES or b"\0" in raw:
                raise ValueError("ssids")


def encode_config(config: Config) -> bytes:
    """Serialise settings for SET_CONFIG. Raises ValueError if invalid."""
    config.validate()
    out = _CFG_HDR.pack(
        CONFIG_VERSION,
        config.band,
        config.country.encode(),
        config.scan_dwell_ms,
        config.hop_ms,
        config.rescan_s,
        config.min_frames,
        config.hold_s,
        config.min_rssi,
        len(config.ssids),
    )
    for ssid in config.ssids:
        raw = ssid.encode()
        out += bytes([len(raw)]) + raw
    return out


def decode_config(blob: bytes) -> Config:
    """Inverse of encode_config. Raises ProtocolError on anything malformed."""
    if len(blob) < _CFG_HDR.size:
        raise ProtocolError("settings too short")
    version, band, country, dwell, hop, rescan, frames, hold, rssi, n = _CFG_HDR.unpack_from(blob)
    if version != CONFIG_VERSION:
        raise ProtocolError(f"unsupported settings version {version}")
    ssids = []
    pos = _CFG_HDR.size
    for _ in range(n):
        if pos >= len(blob):
            raise ProtocolError("settings truncated")
        size = blob[pos]
        raw = blob[pos + 1 : pos + 1 + size]
        if len(raw) != size:
            raise ProtocolError("settings truncated")
        ssids.append(raw.decode(errors="replace"))
        pos += 1 + size
    if pos != len(blob):
        raise ProtocolError("trailing bytes in settings")
    return Config(
        ssids=tuple(ssids), country=country.decode(errors="replace"), band=band,
        scan_dwell_ms=dwell, hop_ms=hop, rescan_s=rescan, min_frames=frames,
        hold_s=hold, min_rssi=rssi,
    )


def config_crc(blob: bytes) -> int:
    """The identifier the device reports for the settings it holds."""
    return zlib.crc32(blob) & 0xFFFFFFFF


def build_report(report: Report) -> bytes:
    """Serialise a report (used by the tests)."""
    out = _REPORT_HDR.pack(
        REPORT_VERSION,
        FLAG_TRUNCATED if report.truncated else 0,
        report.uptime_s,
        report.ap_count,
        report.config_crc,
        len(report.clients),
    )
    for c in report.clients:
        out += _ENTRY.pack(bytes.fromhex(c.mac.replace(":", "")), c.rssi, c.age_s)
    return out


def parse_report(plain: bytes) -> Report:
    """Decode the plaintext report."""
    if len(plain) < _REPORT_HDR.size:
        raise ProtocolError("report too short")
    version, flags, uptime_s, ap_count, config_crc, n = _REPORT_HDR.unpack_from(plain)
    if version != REPORT_VERSION:
        raise ProtocolError(f"unsupported report version {version}")
    if len(plain) != _REPORT_HDR.size + n * _ENTRY.size:
        raise ProtocolError("report length does not match its client count")
    clients = []
    for i in range(n):
        mac, rssi, age = _ENTRY.unpack_from(plain, _REPORT_HDR.size + i * _ENTRY.size)
        clients.append(Client(mac=":".join(f"{b:02x}" for b in mac), rssi=rssi, age_s=age))
    return Report(
        uptime_s=uptime_s,
        ap_count=ap_count,
        truncated=bool(flags & FLAG_TRUNCATED),
        clients=tuple(clients),
        config_crc=config_crc,
    )


class Reassembler:
    """Collect notification fragments into one message."""

    def __init__(self) -> None:
        self._expected = 0
        self._parts: list[bytes] = []

    def feed(self, chunk: bytes) -> bytes | None:
        """Add a fragment. Returns the full message after the last one."""
        if not chunk:
            raise ProtocolError("empty fragment")
        seq = chunk[0] & 0x7F
        last = bool(chunk[0] & 0x80)
        if seq != self._expected:
            raise ProtocolError(f"fragment {seq} out of order, expected {self._expected}")
        self._parts.append(bytes(chunk[1:]))
        self._expected += 1
        if not last:
            return None
        message = b"".join(self._parts)
        self._expected = 0
        self._parts = []
        return message


def fragment(message: bytes, per_chunk: int) -> list[bytes]:
    """Split a message into fragments (used by the tests)."""
    parts = [message[i : i + per_chunk] for i in range(0, len(message), per_chunk)] or [b""]
    if len(parts) > MAX_FRAGMENTS:  # the sequence number has 7 bits
        raise ValueError(f"{len(parts)} fragments do not fit in {MAX_FRAGMENTS}")
    return [
        bytes([i | (0x80 if i == len(parts) - 1 else 0)]) + part
        for i, part in enumerate(parts)
    ]

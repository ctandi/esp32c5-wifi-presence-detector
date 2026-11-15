"""Config flow: find the sensor, enter its key, choose what it should watch."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .client import PollError, async_poll
from .const import (
    BAND_OPTIONS,
    CONF_BAND,
    CONF_COUNTRY,
    CONF_HOLD,
    CONF_HOP,
    CONF_KEY,
    CONF_MIN_FRAMES,
    CONF_MIN_RSSI,
    CONF_POLL_INTERVAL,
    CONF_RESCAN,
    CONF_SCAN_DWELL,
    CONF_SSIDS,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    POLL_INTERVAL_RANGE,
    SECTION_ADVANCED,
)
from .protocol import (
    HOLD_RANGE,
    HOP_RANGE,
    MAX_SSID_BYTES,
    MAX_SSIDS,
    MIN_FRAMES_RANGE,
    MIN_RSSI_RANGE,
    RESCAN_RANGE,
    SCAN_DWELL_RANGE,
    SERVICE_UUID,
    AuthError,
    Config,
    parse_key,
)
from .session import ConfigRejected
from .settings import config_from_options, options_from_config, poll_interval_from_options


def _title(address: str) -> str:
    """Name a sensor by the tail of its address.

    The Bluetooth name sits in the scan response, which proxies often do not
    pass on, so Home Assistant may only know the address.
    """
    return f"Wi-Fi presence {address[-5:]}"


def _number(rng: tuple[int, int], unit: str | None = None) -> NumberSelector:
    config = NumberSelectorConfig(min=rng[0], max=rng[1], step=1, mode=NumberSelectorMode.BOX)
    if unit:  # the key must be left out entirely when there is no unit
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _settings_schema(values: Mapping[str, Any]) -> vol.Schema:
    """The settings form: the essentials up front, the tuning folded away."""
    advanced = vol.Schema(
        {
            vol.Required(CONF_BAND, default=values[CONF_BAND]): SelectSelector(
                SelectSelectorConfig(
                    options=list(BAND_OPTIONS), translation_key=CONF_BAND, mode="dropdown"
                )
            ),
            vol.Required(CONF_SCAN_DWELL, default=values[CONF_SCAN_DWELL]): _number(
                SCAN_DWELL_RANGE, "ms"
            ),
            vol.Required(CONF_HOP, default=values[CONF_HOP]): _number(HOP_RANGE, "ms"),
            vol.Required(CONF_RESCAN, default=values[CONF_RESCAN]): _number(RESCAN_RANGE, "s"),
            vol.Required(CONF_HOLD, default=values[CONF_HOLD]): _number(HOLD_RANGE, "s"),
            vol.Required(CONF_MIN_FRAMES, default=values[CONF_MIN_FRAMES]): _number(
                MIN_FRAMES_RANGE
            ),
            vol.Required(CONF_MIN_RSSI, default=values[CONF_MIN_RSSI]): _number(
                MIN_RSSI_RANGE, "dBm"
            ),
            vol.Required(CONF_POLL_INTERVAL, default=values[CONF_POLL_INTERVAL]): _number(
                POLL_INTERVAL_RANGE, "s"
            ),
        }
    )
    return vol.Schema(
        {
            vol.Required(CONF_SSIDS, default=values[CONF_SSIDS]): TextSelector(
                TextSelectorConfig(multiple=True)
            ),
            vol.Required(CONF_COUNTRY, default=values[CONF_COUNTRY]): TextSelector(),
            vol.Required(SECTION_ADVANCED): section(advanced, {"collapsed": True}),
        }
    )


def _defaults(country: str) -> dict[str, Any]:
    return options_from_config(Config(country=country), DEFAULT_POLL_INTERVAL)


def _flatten(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Merge the collapsible section back into one dict."""
    flat = {k: v for k, v in user_input.items() if k != SECTION_ADVANCED}
    flat.update(user_input.get(SECTION_ADVANCED, {}))
    return flat


def _validate(flat: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Check the form. Returns (clean options, {}) or (None, errors)."""
    errors: dict[str, str] = {}

    ssids: list[str] = []
    for raw in flat.get(CONF_SSIDS, []):
        ssid = raw.strip()
        if ssid and ssid not in ssids:
            ssids.append(ssid)
    if not ssids:
        errors[CONF_SSIDS] = "no_ssid"
    elif len(ssids) > MAX_SSIDS:
        errors[CONF_SSIDS] = "too_many_ssids"
    elif any(len(ssid.encode()) > MAX_SSID_BYTES or "\0" in ssid for ssid in ssids):
        errors[CONF_SSIDS] = "ssid_too_long"

    country = str(flat.get(CONF_COUNTRY, "")).strip().upper()
    if len(country) != 2 or not country.isascii() or not country.isalpha():
        errors[CONF_COUNTRY] = "invalid_country"

    if errors:
        return None, errors
    try:
        options = {
            **flat,
            CONF_SSIDS: ssids,
            CONF_COUNTRY: country,
            CONF_SCAN_DWELL: int(flat[CONF_SCAN_DWELL]),
            CONF_HOP: int(flat[CONF_HOP]),
            CONF_RESCAN: int(flat[CONF_RESCAN]),
            CONF_HOLD: int(flat[CONF_HOLD]),
            CONF_MIN_FRAMES: int(flat[CONF_MIN_FRAMES]),
            CONF_MIN_RSSI: int(flat[CONF_MIN_RSSI]),
            CONF_POLL_INTERVAL: int(flat[CONF_POLL_INTERVAL]),
        }
        config_from_options(options).validate()
        if not POLL_INTERVAL_RANGE[0] <= options[CONF_POLL_INTERVAL] <= POLL_INTERVAL_RANGE[1]:
            raise ValueError(CONF_POLL_INTERVAL)
    except ValueError:
        return None, {"base": "invalid_settings"}
    return options, {}


class WifiPresenceConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._name: str = "Wi-Fi presence"
        self._found: dict[str, str] = {}
        self._key: bytes | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """The settings can be changed later."""
        return WifiPresenceOptionsFlow()

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """The sensor was spotted by Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self._name = _title(discovery_info.address)
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_key()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick a sensor from the ones Bluetooth can currently see."""
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            self._name = self._found[self._address]
            await self.async_set_unique_id(self._address)
            self._abort_if_unique_id_configured()
            return await self.async_step_key()

        configured = self._async_current_ids()
        self._found = {
            info.address: _title(info.address)
            for info in async_discovered_service_info(self.hass, connectable=True)
            if SERVICE_UUID in [u.lower() for u in info.service_uuids]
            and info.address not in configured
        }
        if not self._found:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(self._found)}),
        )

    async def async_step_key(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the sensor's key and check it against the sensor."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                key = parse_key(user_input[CONF_KEY])
            except ValueError:
                errors[CONF_KEY] = "invalid_key"
            else:
                assert self._address is not None
                try:
                    await async_poll(self.hass, self._address, key, self._name)
                except AuthError:
                    errors["base"] = "wrong_key"
                except PollError:
                    errors["base"] = "cannot_connect"
                else:
                    self._key = key
                    return await self.async_step_settings()

        return self.async_show_form(
            step_id="key",
            data_schema=vol.Schema({vol.Required(CONF_KEY): str}),
            description_placeholders={"name": self._name},
            errors=errors,
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """What the sensor should watch. Sending it also completes the pairing."""
        errors: dict[str, str] = {}
        values = _defaults(self.hass.config.country or "DE")
        if user_input is not None:
            options, errors = _validate(_flatten(user_input))
            if options is not None:
                assert self._address is not None and self._key is not None
                try:
                    await async_poll(
                        self.hass,
                        self._address,
                        self._key,
                        self._name,
                        config_from_options(options),
                        force=True,
                    )
                except AuthError:
                    errors["base"] = "wrong_key"
                except ConfigRejected:
                    errors["base"] = "settings_rejected"
                except PollError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(
                        title=self._name,
                        data={CONF_ADDRESS: self._address, CONF_KEY: self._key.hex()},
                        options=options,
                    )
            values = {**values, **_flatten(user_input)}

        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(values),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The sensor no longer accepts the key (it was flashed again)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the new key."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                key = parse_key(user_input[CONF_KEY])
            except ValueError:
                errors[CONF_KEY] = "invalid_key"
            else:
                try:
                    await async_poll(self.hass, entry.data[CONF_ADDRESS], key, entry.title)
                except AuthError:
                    errors["base"] = "wrong_key"
                except PollError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_KEY: key.hex()}
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_KEY): str}),
            description_placeholders={"name": entry.title},
            errors=errors,
        )


class WifiPresenceOptionsFlow(OptionsFlow):
    """Change the sensor's settings later. They are sent to it right away."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and apply the settings."""
        entry = self.config_entry
        errors: dict[str, str] = {}
        current = options_from_config(
            config_from_options(entry.options, self.hass.config.country or "DE"),
            poll_interval_from_options(entry.options),
        )
        values = current
        if user_input is not None:
            options, errors = _validate(_flatten(user_input))
            if options is not None:
                try:
                    await async_poll(
                        self.hass,
                        entry.data[CONF_ADDRESS],
                        parse_key(entry.data[CONF_KEY]),
                        entry.title,
                        config_from_options(options),
                    )
                except AuthError:
                    errors["base"] = "wrong_key"
                except ConfigRejected:
                    errors["base"] = "settings_rejected"
                except PollError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(data=options)
            values = {**current, **_flatten(user_input)}

        return self.async_show_form(
            step_id="init",
            data_schema=_settings_schema(values),
            errors=errors,
        )

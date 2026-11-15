"""Integration tests with the Bluetooth poll mocked out.

The protocol and the real device exchange are covered by test/test_protocol.py
and tools/wp_client.py; these tests check the Home Assistant side: config flow,
entities, home/away, availability and the disabled-by-default trackers.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from habluetooth import BluetoothServiceInfoBleak
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ADDRESS, CONF_NAME, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.wifi_presence.client import PollError
from custom_components.wifi_presence.const import (
    CONF_BAND,
    CONF_COUNTRY,
    CONF_HOLD,
    CONF_KEY,
    CONF_POLL_INTERVAL,
    CONF_SSIDS,
    CONF_TRACK_ALL,
    CONF_TRACKED,
    DOMAIN,
    SECTION_ADVANCED,
)
from custom_components.wifi_presence.protocol import (
    BAND_5G,
    SERVICE_UUID,
    AuthError,
    Client,
    Config,
    Report,
)
from custom_components.wifi_presence.session import ConfigRejected, SessionResult
from custom_components.wifi_presence.settings import options_from_config

ADDRESS = "AA:BB:CC:11:22:33"
KEY = "ab" * 32
PHONE = "aa:bb:cc:dd:ee:01"
TV = "aa:bb:cc:dd:ee:02"


def _report(*macs: str) -> Report:
    return Report(
        uptime_s=100,
        ap_count=5,
        truncated=False,
        clients=tuple(Client(m, -50, 3) for m in macs),
    )


def _result(*macs: str, applied: bool = False) -> SessionResult:
    return SessionResult(report=_report(*macs), config_applied=applied)


def _discovery() -> BluetoothServiceInfoBleak:
    device = BLEDevice(ADDRESS, "WiFi Presence", {})
    adv = AdvertisementData(
        local_name="WiFi Presence",
        manufacturer_data={},
        service_data={},
        service_uuids=[SERVICE_UUID],
        rssi=-60,
        tx_power=None,
        platform_data=(),
    )
    return BluetoothServiceInfoBleak(
        name="WiFi Presence",
        address=ADDRESS,
        rssi=-60,
        manufacturer_data={},
        service_data={},
        service_uuids=[SERVICE_UUID],
        source="local",
        device=device,
        advertisement=adv,
        connectable=True,
        time=0,
        tx_power=None,
    )


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        title="WiFi Presence",
        data={CONF_ADDRESS: ADDRESS, CONF_KEY: KEY},
        options=options_from_config(Config(ssids=("MyNet",), country="DE"), 30),
    )


async def _setup(hass: HomeAssistant, poll: AsyncMock) -> MockConfigEntry:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch("custom_components.wifi_presence.coordinator.async_poll", poll):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _tick(hass, freezer, poll: AsyncMock) -> None:
    with patch("custom_components.wifi_presence.coordinator.async_poll", poll):
        freezer.tick(timedelta(seconds=31))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()


# ---- config flow --------------------------------------------------------------


async def _start_flow(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=_discovery()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "key"
    return result


def _settings_input(**overrides):
    """What the settings form submits (the advanced section left at its defaults)."""
    data = {CONF_SSIDS: ["MyNet"], CONF_COUNTRY: "DE", SECTION_ADVANCED: {}}
    data.update(overrides)
    return data


async def _to_settings(hass: HomeAssistant):
    """Start the flow and get past the key step."""
    result = await _start_flow(hass)
    with patch(
        "custom_components.wifi_presence.config_flow.async_poll",
        AsyncMock(return_value=_result()),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_KEY: f"  {KEY.upper()} "}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"
    return result


async def test_flow_key_then_settings_creates_entry_and_pairs(hass: HomeAssistant) -> None:
    result = await _to_settings(hass)
    poll = AsyncMock(return_value=_result(applied=True))
    with patch("custom_components.wifi_presence.config_flow.async_poll", poll), patch(
        "custom_components.wifi_presence.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            _settings_input(
                **{CONF_SSIDS: ["MyNet", " Guest ", "MyNet", ""], CONF_COUNTRY: "at"},
            ),
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Wi-Fi presence {ADDRESS}"  # the full address, as printed by the sensor
    assert result["data"] == {CONF_ADDRESS: ADDRESS, CONF_KEY: KEY}  # key normalised
    assert result["result"].unique_id == ADDRESS
    # cleaned up: trimmed, de-duplicated, upper-case country; defaults for the rest
    assert result["options"][CONF_SSIDS] == ["MyNet", "Guest"]
    assert result["options"][CONF_COUNTRY] == "AT"
    assert result["options"][CONF_HOLD] == 300
    assert result["options"][CONF_POLL_INTERVAL] == 30

    # the settings were pushed to the sensor (forced: this is what completes the pairing)
    args, kwargs = poll.call_args
    assert args[1] == ADDRESS and args[2] == bytes.fromhex(KEY)
    assert args[4] == Config(ssids=("MyNet", "Guest"), country="AT")
    assert kwargs == {"force": True}


async def test_settings_form_starts_with_home_assistants_country(hass: HomeAssistant) -> None:
    hass.config.country = "AT"
    result = await _to_settings(hass)
    schema = result["data_schema"].schema
    country = next(k for k in schema if k == CONF_COUNTRY)
    assert country.default() == "AT"


@pytest.mark.parametrize(
    ("overrides", "errors"),
    [
        ({CONF_SSIDS: []}, {CONF_SSIDS: "no_ssid"}),
        ({CONF_SSIDS: ["  ", ""]}, {CONF_SSIDS: "no_ssid"}),
        ({CONF_SSIDS: [f"net{i}" for i in range(9)]}, {CONF_SSIDS: "too_many_ssids"}),
        ({CONF_SSIDS: ["x" * 33]}, {CONF_SSIDS: "ssid_too_long"}),
        ({CONF_SSIDS: ["é" * 17]}, {CONF_SSIDS: "ssid_too_long"}),  # 34 bytes
        ({CONF_COUNTRY: "Germany"}, {CONF_COUNTRY: "invalid_country"}),
        ({CONF_COUNTRY: "1A"}, {CONF_COUNTRY: "invalid_country"}),
    ],
)
async def test_settings_validation(hass, overrides, errors) -> None:
    result = await _to_settings(hass)
    poll = AsyncMock(return_value=_result())
    with patch("custom_components.wifi_presence.config_flow.async_poll", poll):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _settings_input(**overrides)
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"
    assert result["errors"] == errors
    poll.assert_not_called()  # nothing invalid is ever sent to the sensor


async def test_out_of_range_numbers_are_stopped_by_the_form_itself(hass: HomeAssistant) -> None:
    result = await _to_settings(hass)
    poll = AsyncMock(return_value=_result())
    for field, value in ((CONF_HOLD, 1), (CONF_HOLD, 99999), (CONF_POLL_INTERVAL, 1)):
        with patch("custom_components.wifi_presence.config_flow.async_poll", poll), pytest.raises(
            InvalidData
        ):
            await hass.config_entries.flow.async_configure(
                result["flow_id"], _settings_input(**{SECTION_ADVANCED: {field: value}})
            )
    poll.assert_not_called()


def test_the_validator_is_a_second_line_of_defence() -> None:
    from custom_components.wifi_presence.config_flow import _defaults, _validate

    flat = {**_defaults("DE"), CONF_SSIDS: ["MyNet"], CONF_HOLD: 1}
    assert _validate(flat) == (None, {"base": "invalid_settings"})
    flat[CONF_HOLD] = 300
    options, errors = _validate(flat)
    assert errors == {} and options[CONF_HOLD] == 300
    flat[CONF_POLL_INTERVAL] = 5000
    assert _validate(flat) == (None, {"base": "invalid_settings"})


@pytest.mark.parametrize(
    ("poll_error", "error"),
    [
        (PollError("gone"), "cannot_connect"),
        (ConfigRejected("no"), "settings_rejected"),
        (AuthError("key"), "wrong_key"),
    ],
)
async def test_settings_step_reports_sensor_problems_and_can_retry(hass, poll_error, error) -> None:
    result = await _to_settings(hass)
    with patch(
        "custom_components.wifi_presence.config_flow.async_poll", AsyncMock(side_effect=poll_error)
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], _settings_input())
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": error}

    with patch(
        "custom_components.wifi_presence.config_flow.async_poll", AsyncMock(return_value=_result(applied=True))
    ), patch("custom_components.wifi_presence.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], _settings_input())
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("key", "poll_error", "field", "error"),
    [
        ("not-hex", None, CONF_KEY, "invalid_key"),
        ("ab" * 31, None, CONF_KEY, "invalid_key"),
        (KEY, AuthError("nope"), "base", "wrong_key"),
        (KEY, PollError("out of range"), "base", "cannot_connect"),
    ],
)
async def test_key_step_errors_and_recovery(hass, key, poll_error, field, error) -> None:
    result = await _start_flow(hass)
    poll = AsyncMock(side_effect=poll_error, return_value=_result())
    with patch("custom_components.wifi_presence.config_flow.async_poll", poll):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_KEY: key}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "key"
    assert result["errors"] == {field: error}

    # the user can fix it and continue to the settings
    with patch(
        "custom_components.wifi_presence.config_flow.async_poll",
        AsyncMock(return_value=_result()),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_KEY: KEY}
        )
    assert result["step_id"] == "settings"


async def test_flow_aborts_when_already_configured(hass: HomeAssistant) -> None:
    _entry().add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=_discovery()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_without_sensor_aborts(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.wifi_presence.config_flow.async_discovered_service_info",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_flow_lists_discovered_sensor(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.wifi_presence.config_flow.async_discovered_service_info",
        return_value=[_discovery()],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: ADDRESS}
        )
    assert result["step_id"] == "key"


# ---- entities -----------------------------------------------------------------


async def test_sensors_and_attributes(hass: HomeAssistant) -> None:
    await _setup(hass, AsyncMock(return_value=_result(PHONE, TV)))
    state = hass.states.get("sensor.wifi_presence_clients_present")
    assert state is not None and state.state == "2"
    assert {c["mac"] for c in state.attributes["clients"]} == {PHONE, TV}
    assert hass.states.get("sensor.wifi_presence_access_points_watched").state == "5"
    assert hass.states.get("sensor.wifi_presence_sensor_uptime").state == "100"


async def test_every_heard_client_gets_a_tracker_disabled_by_default(hass) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE, TV)))
    registry = er.async_get(hass)
    trackers = [
        e for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "device_tracker"
    ]
    assert {e.unique_id for e in trackers} == {f"{entry.entry_id}_{PHONE}", f"{entry.entry_id}_{TV}"}
    assert all(e.disabled_by is er.RegistryEntryDisabler.INTEGRATION for e in trackers)


async def test_home_away_and_unavailable(hass: HomeAssistant, freezer) -> None:
    poll = AsyncMock(return_value=_result(PHONE, TV))
    entry = await _setup(hass, poll)
    registry = er.async_get(hass)

    # the user enables the phone's tracker
    phone = registry.async_get_entity_id("device_tracker", DOMAIN, f"{entry.entry_id}_{PHONE}")
    registry.async_update_entity(phone, disabled_by=None)
    with patch("custom_components.wifi_presence.coordinator.async_poll", poll):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get(phone).state == "home"
    assert hass.states.get(phone).attributes["rssi"] == -50
    assert hass.states.get(phone).attributes["mac"] == PHONE

    # the phone leaves
    await _tick(hass, freezer, AsyncMock(return_value=_result(TV)))
    assert hass.states.get(phone).state == "not_home"
    assert hass.states.get("sensor.wifi_presence_clients_present").state == "1"

    # the sensor itself becomes unreachable: unknown, not "away"
    await _tick(hass, freezer, AsyncMock(side_effect=PollError("out of range")))
    assert hass.states.get(phone).state == STATE_UNAVAILABLE

    # and comes back with the phone
    await _tick(hass, freezer, AsyncMock(return_value=_result(PHONE)))
    assert hass.states.get(phone).state == "home"


async def test_new_client_appearing_later_gets_a_tracker(hass, freezer) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE)))
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("device_tracker", DOMAIN, f"{entry.entry_id}_{TV}") is None
    await _tick(hass, freezer, AsyncMock(return_value=_result(PHONE, TV)))
    assert registry.async_get_entity_id("device_tracker", DOMAIN, f"{entry.entry_id}_{TV}") is not None


async def test_known_clients_survive_a_reload_while_absent(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE, TV)))
    registry = er.async_get(hass)
    tv = registry.async_get_entity_id("device_tracker", DOMAIN, f"{entry.entry_id}_{TV}")
    registry.async_update_entity(tv, disabled_by=None)

    # reload while the TV is switched off: its tracker must exist and say not_home
    with patch("custom_components.wifi_presence.coordinator.async_poll", AsyncMock(return_value=_result(PHONE))):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get(tv).state == "not_home"


async def test_wrong_key_at_runtime_asks_for_a_new_key(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.wifi_presence.coordinator.async_poll",
        AsyncMock(side_effect=AuthError("bad")),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flows] == [config_entries.SOURCE_REAUTH]


async def test_reauth_with_the_new_key(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    new_key = "cd" * 32
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    poll = AsyncMock(side_effect=AuthError("still the old one"))
    with patch("custom_components.wifi_presence.config_flow.async_poll", poll):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KEY: new_key})
    assert result["errors"] == {"base": "wrong_key"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KEY: "short"})
    assert result["errors"] == {CONF_KEY: "invalid_key"}

    with patch(
        "custom_components.wifi_presence.config_flow.async_poll", AsyncMock(return_value=_result())
    ), patch("custom_components.wifi_presence.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_KEY: new_key})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert entry.data[CONF_KEY] == new_key


# ---- settings travel with every poll ---------------------------------------------


async def test_poll_carries_the_settings_from_the_options(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        title="WiFi Presence",
        data={CONF_ADDRESS: ADDRESS, CONF_KEY: KEY},
        options=options_from_config(
            Config(ssids=("A", "B"), country="CH", band=BAND_5G, hold_s=900, hop_ms=1000), 60
        ),
    )
    poll = AsyncMock(return_value=_result(applied=True))
    entry.add_to_hass(hass)
    with patch("custom_components.wifi_presence.coordinator.async_poll", poll):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    args = poll.call_args.args
    assert args[2] == bytes.fromhex(KEY)
    assert args[4] == Config(ssids=("A", "B"), country="CH", band=BAND_5G, hold_s=900, hop_ms=1000)
    assert entry.runtime_data.update_interval == timedelta(seconds=60)


async def test_settings_rejection_marks_the_sensor_unavailable_not_unpaired(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    with patch(
        "custom_components.wifi_presence.coordinator.async_poll",
        AsyncMock(side_effect=ConfigRejected("refused")),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)  # no reauth prompt


# ---- changing the settings later --------------------------------------------------


def _options_input(**overrides):
    data = {
        CONF_SSIDS: ["MyNet", "Neighbour-Guest"],
        CONF_COUNTRY: "DE",
        SECTION_ADVANCED: {CONF_BAND: "5g", CONF_HOLD: 900, CONF_POLL_INTERVAL: 20},
    }
    data.update(overrides)
    return data


async def test_options_flow_shows_current_values_and_pushes_changes(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE)))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "init"
    defaults = {k.schema: k.default() for k in result["data_schema"].schema if callable(k.default)}
    assert defaults[CONF_SSIDS] == ["MyNet"] and defaults[CONF_COUNTRY] == "DE"

    push = AsyncMock(return_value=_result(PHONE, applied=True))
    with patch("custom_components.wifi_presence.config_flow.async_poll", push), patch(
        "custom_components.wifi_presence.coordinator.async_poll", AsyncMock(return_value=_result(PHONE))
    ):
        result = await hass.config_entries.options.async_configure(result["flow_id"], _options_input())
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SSIDS] == ["MyNet", "Neighbour-Guest"]
    assert entry.options[CONF_BAND] == "5g" and entry.options[CONF_HOLD] == 900
    # sent to the sensor right away, in the sensor's own terms
    assert push.call_args.args[4] == Config(
        ssids=("MyNet", "Neighbour-Guest"), country="DE", band=BAND_5G, hold_s=900
    )
    # the polling period is a Home Assistant setting and took effect on the reload
    assert entry.runtime_data.update_interval == timedelta(seconds=20)


# ---- picking the devices to track ----------------------------------------------------


def _tracker_id(hass, entry, mac):
    return er.async_get(hass).async_get_entity_id("device_tracker", DOMAIN, f"{entry.entry_id}_{mac}")


def _tracked_field(result):
    key = next(k for k in result["data_schema"].schema if k == CONF_TRACKED)
    return key, result["data_schema"].schema[key]


async def test_options_list_known_devices_and_enable_the_chosen_ones(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE, TV)))
    assert all(
        er.async_get(hass).async_get(_tracker_id(hass, entry, m)).disabled_by for m in (PHONE, TV)
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    key, selector = _tracked_field(result)
    assert key.default() == []  # nothing is tracked yet
    assert {o["value"] for o in selector.config["options"]} == {PHONE, TV}
    assert selector.config["multiple"] is True

    push = AsyncMock(return_value=_result(PHONE, TV))
    with patch("custom_components.wifi_presence.config_flow.async_poll", push), patch(
        "custom_components.wifi_presence.coordinator.async_poll", push
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _options_input(**{CONF_TRACKED: [PHONE]})
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_TRACKED not in entry.options  # a one-off action, not a stored setting

    registry = er.async_get(hass)
    assert registry.async_get(_tracker_id(hass, entry, PHONE)).disabled_by is None
    assert registry.async_get(_tracker_id(hass, entry, TV)).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(_tracker_id(hass, entry, PHONE)).state == "home"  # and it shows up

    # the form now shows the phone as tracked; un-ticking it disables the tracker again
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert _tracked_field(result)[0].default() == [PHONE]
    with patch("custom_components.wifi_presence.config_flow.async_poll", push), patch(
        "custom_components.wifi_presence.coordinator.async_poll", push
    ):
        await hass.config_entries.options.async_configure(
            result["flow_id"], _options_input(**{CONF_TRACKED: []})
        )
        await hass.async_block_till_done()
    assert registry.async_get(_tracker_id(hass, entry, PHONE)).disabled_by is er.RegistryEntryDisabler.USER


async def test_a_tracker_enabled_in_the_entity_settings_shows_as_ticked(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE, TV)))
    er.async_get(hass).async_update_entity(_tracker_id(hass, entry, TV), disabled_by=None)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert _tracked_field(result)[0].default() == [TV]


async def test_devices_are_labelled_with_the_name_home_assistant_knows(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    # a phone integration (another config entry) already registered this MAC under a name
    phone_entry = MockConfigEntry(domain="mobile_app", title="Pixel")
    phone_entry.add_to_hass(hass)
    dr.async_get(hass).async_get_or_create(
        config_entry_id=phone_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, PHONE)},
        name="Pixel 9",
    )
    with patch(
        "custom_components.wifi_presence.coordinator.async_poll",
        AsyncMock(return_value=SessionResult(
            Report(uptime_s=1, ap_count=1, truncated=False, clients=(Client(PHONE, -42, 1), Client(TV, -80, 1))), False
        )),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    labels = {o["value"]: o["label"] for o in _tracked_field(result)[1].config["options"]}
    assert labels[PHONE] == f"Pixel 9 \u00b7 {PHONE} \u00b7 -42 dBm"
    assert labels[TV] == f"{TV} \u00b7 -80 dBm"
    # and the phone's own device keeps its name: our tracker never renames it
    assert [d.name for d in dr.async_entries_for_config_entry(dr.async_get(hass), phone_entry.entry_id)] == ["Pixel 9"]
    # strongest signal first
    assert [o["value"] for o in _tracked_field(result)[1].config["options"]] == [PHONE, TV]


async def test_no_device_picker_before_any_device_was_heard(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result()))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert CONF_TRACKED not in [k.schema for k in result["data_schema"].schema]


async def test_a_failed_push_changes_nothing_about_the_trackers(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE)))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch("custom_components.wifi_presence.config_flow.async_poll", AsyncMock(side_effect=PollError("gone"))):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _options_input(**{CONF_TRACKED: [PHONE]})
        )
    assert result["errors"] == {"base": "cannot_connect"}
    assert er.async_get(hass).async_get(_tracker_id(hass, entry, PHONE)).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert result["data_schema"].schema  # the form is shown again with the choice kept
    assert _tracked_field(result)[0].default() == [PHONE]


@pytest.mark.parametrize(
    ("poll_error", "error"),
    [(PollError("gone"), "cannot_connect"), (ConfigRejected("no"), "settings_rejected")],
)
async def test_options_flow_keeps_old_options_when_the_sensor_cannot_take_them(hass, poll_error, error) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE)))
    before = dict(entry.options)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch("custom_components.wifi_presence.config_flow.async_poll", AsyncMock(side_effect=poll_error)):
        result = await hass.config_entries.options.async_configure(result["flow_id"], _options_input())
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": error}
    assert dict(entry.options) == before  # Home Assistant and sensor never disagree silently


async def test_options_flow_validates_before_talking_to_the_sensor(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE)))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    push = AsyncMock()
    with patch("custom_components.wifi_presence.config_flow.async_poll", push):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _options_input(**{CONF_SSIDS: []})
        )
    assert result["errors"] == {CONF_SSIDS: "no_ssid"}
    push.assert_not_called()


async def test_unload(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE)))
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


# ---- naming, tracking everything, and the cleanup of old devices --------------------------


async def test_the_sensor_can_be_named_when_pairing(hass: HomeAssistant) -> None:
    result = await _to_settings(hass)
    with patch(
        "custom_components.wifi_presence.config_flow.async_poll", AsyncMock(return_value=_result(applied=True))
    ), patch("custom_components.wifi_presence.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _settings_input(**{CONF_NAME: "  Wi-Fi presence living room "})
        )
    assert result["title"] == "Wi-Fi presence living room"
    assert CONF_NAME not in result["options"]  # the title is not a setting of the sensor


async def test_an_empty_name_falls_back_to_the_address(hass: HomeAssistant) -> None:
    result = await _to_settings(hass)
    default = next(k for k in result["data_schema"].schema if k == CONF_NAME).default()
    assert default == f"Wi-Fi presence {ADDRESS}"
    with patch(
        "custom_components.wifi_presence.config_flow.async_poll", AsyncMock(return_value=_result(applied=True))
    ), patch("custom_components.wifi_presence.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], _settings_input(**{CONF_NAME: "   "})
        )
    assert result["title"] == f"Wi-Fi presence {ADDRESS}"


async def test_the_sensor_can_be_renamed_later(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE)))
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert next(k for k in result["data_schema"].schema if k == CONF_NAME).default() == "WiFi Presence"
    push = AsyncMock(return_value=_result(PHONE))
    with patch("custom_components.wifi_presence.config_flow.async_poll", push), patch(
        "custom_components.wifi_presence.coordinator.async_poll", push
    ):
        await hass.config_entries.options.async_configure(
            result["flow_id"], _options_input(**{CONF_NAME: "Attic sensor"})
        )
        await hass.async_block_till_done()
    assert entry.title == "Attic sensor"
    assert CONF_NAME not in entry.options
    names = {d.name for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)}
    assert "Attic sensor" in names  # the sensor's device follows


async def test_trackers_are_named_after_the_detected_device(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE, TV)))
    registry = er.async_get(hass)
    assert registry.async_get(_tracker_id(hass, entry, PHONE)).original_name == f"Wi-Fi presence {PHONE}"
    assert registry.async_get(_tracker_id(hass, entry, TV)).original_name == f"Wi-Fi presence {TV}"
    assert _tracker_id(hass, entry, PHONE).endswith(PHONE.replace(":", "_"))  # and the id says so too


async def test_trackers_do_not_get_devices_of_their_own(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE, TV)))
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert [d.name for d in devices] == ["WiFi Presence"]  # only the sensor itself


async def test_track_all_enables_every_new_tracker_from_the_start(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS, title="WiFi Presence",
        data={CONF_ADDRESS: ADDRESS, CONF_KEY: KEY},
        options={**options_from_config(Config(ssids=("MyNet",)), 30), CONF_TRACK_ALL: True},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.wifi_presence.coordinator.async_poll", AsyncMock(return_value=_result(PHONE, TV))):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert all(registry.async_get(_tracker_id(hass, entry, m)).disabled_by is None for m in (PHONE, TV))
    assert hass.states.get(_tracker_id(hass, entry, PHONE)).state == "home"


async def test_without_track_all_new_trackers_stay_hidden(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE)))
    assert entry.options.get(CONF_TRACK_ALL, False) is False
    assert er.async_get(hass).async_get(_tracker_id(hass, entry, PHONE)).disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_turning_on_track_all_enables_the_hidden_ones_but_respects_exclusions(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE, TV, "aa:bb:cc:dd:ee:03")))
    registry = er.async_get(hass)
    skipped = _tracker_id(hass, entry, TV)
    registry.async_update_entity(skipped, disabled_by=er.RegistryEntryDisabler.USER)  # the user excluded the TV

    result = await hass.config_entries.options.async_init(entry.entry_id)
    push = AsyncMock(return_value=_result(PHONE, TV, "aa:bb:cc:dd:ee:03"))
    with patch("custom_components.wifi_presence.config_flow.async_poll", push), patch(
        "custom_components.wifi_presence.coordinator.async_poll", push
    ):
        await hass.config_entries.options.async_configure(
            result["flow_id"], _options_input(**{CONF_TRACK_ALL: True})
        )
        await hass.async_block_till_done()
    assert entry.options[CONF_TRACK_ALL] is True
    assert registry.async_get(_tracker_id(hass, entry, PHONE)).disabled_by is None
    assert registry.async_get(_tracker_id(hass, entry, "aa:bb:cc:dd:ee:03")).disabled_by is None
    assert registry.async_get(skipped).disabled_by is er.RegistryEntryDisabler.USER  # still excluded


async def test_with_track_all_a_device_is_excluded_by_unticking_it(hass: HomeAssistant) -> None:
    entry = await _setup(hass, AsyncMock(return_value=_result(PHONE, TV)))
    registry = er.async_get(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    push = AsyncMock(return_value=_result(PHONE, TV))
    with patch("custom_components.wifi_presence.config_flow.async_poll", push), patch(
        "custom_components.wifi_presence.coordinator.async_poll", push
    ):
        await hass.config_entries.options.async_configure(result["flow_id"], _options_input(**{CONF_TRACK_ALL: True}))
        await hass.async_block_till_done()
        assert all(registry.async_get(_tracker_id(hass, entry, m)).disabled_by is None for m in (PHONE, TV))
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert _tracked_field(result)[0].default() == [PHONE, TV]  # everything ticked
        await hass.config_entries.options.async_configure(
            result["flow_id"], _options_input(**{CONF_TRACK_ALL: True, CONF_TRACKED: [PHONE]})
        )
        await hass.async_block_till_done()
    assert registry.async_get(_tracker_id(hass, entry, PHONE)).disabled_by is None
    assert registry.async_get(_tracker_id(hass, entry, TV)).disabled_by is er.RegistryEntryDisabler.USER


async def test_old_per_client_devices_are_cleaned_up_on_start(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    devices, entities = dr.async_get(hass), er.async_get(hass)
    # what pre-release builds left behind: a device per client, named like the sensor
    legacy = devices.async_get_or_create(
        config_entry_id=entry.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, PHONE)}, name=entry.title
    )
    tracker = entities.async_get_or_create(
        "device_tracker", DOMAIN, f"{entry.entry_id}_{PHONE}", config_entry=entry, device_id=legacy.id,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
    )
    # things that must survive: someone else's device for another MAC, and a device the user renamed
    phone_entry = MockConfigEntry(domain="mobile_app")
    phone_entry.add_to_hass(hass)
    others = devices.async_get_or_create(
        config_entry_id=phone_entry.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, TV)}, name=entry.title
    )
    renamed = devices.async_get_or_create(
        config_entry_id=entry.entry_id, connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:09")}, name="Kitchen radio"
    )

    with patch("custom_components.wifi_presence.coordinator.async_poll", AsyncMock(return_value=_result(PHONE))):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    names = sorted(d.name for d in dr.async_entries_for_config_entry(devices, entry.entry_id))
    assert names == ["Kitchen radio", "WiFi Presence"]  # the stray device is gone, the sensor stays
    assert devices.async_get(others.id) is not None and devices.async_get(renamed.id) is not None
    kept = entities.async_get(tracker.entity_id)
    assert kept is not None and kept.device_id is None and kept.unique_id == f"{entry.entry_id}_{PHONE}"

"""Describe the presence events for the activity log (Logbook)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_CLIENT_ARRIVED, EVENT_CLIENT_LEFT
from .labels import log_name

# The activity log shows plain text, so the wording is chosen here, in the language of
# Home Assistant: "<device> <message>".
_MESSAGES = {
    EVENT_CLIENT_ARRIVED: {"en": "just became present", "de": "ist jetzt anwesend"},
    EVENT_CLIENT_LEFT: {"en": "is now gone", "de": "ist nicht mehr da"},
}


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, Any]]], None],
) -> None:
    """Tell the activity log how to show the presence events."""
    language = "de" if str(hass.config.language).lower().startswith("de") else "en"

    def _describe(event: Event) -> dict[str, Any]:
        data = event.data
        return {
            LOGBOOK_ENTRY_NAME: log_name(data["mac"], data.get("name"), data.get("vendor")),
            LOGBOOK_ENTRY_MESSAGE: _MESSAGES[event.event_type][language],
        }

    for event_type in _MESSAGES:
        async_describe_event(DOMAIN, event_type, _describe)

"""Text platform for the WLED Text Display integration.

Creates one text entity per WLED segment.  The stored value is always
treated as a Jinja2 template and rendered before being pushed to WLED.
Plain text (no template delimiters) renders to itself.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.template import Template

from . import WledTextCoordinator
from .const import DOMAIN, LOGGER

# Regex patterns for extracting entity IDs from template strings
_ENTITY_PATTERNS = [
    re.compile(r"""states\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"""),
    re.compile(r"""state_translated\s*\(\s*['\"]([^'\"]+)['\"]\s*\)"""),
    re.compile(r"""is_state\s*\(\s*['\"]([^'\"]+)['\"]\s*,"""),
    re.compile(r"""state_attr\s*\(\s*['\"]([^'\"]+)['\"]\s*,"""),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WLED text entities for a config entry."""
    coordinator: WledTextCoordinator = hass.data[DOMAIN][entry.entry_id]

    seg_count = await coordinator.async_get_segments()
    if seg_count == 0:
        seg_count = entry.data.get("seg_count", 1)
        LOGGER.debug(
            "Using stored segment count %d for %s", seg_count, coordinator.entry_id
        )

    async_add_entities(
        WledTextEntity(coordinator, seg_id) for seg_id in range(seg_count)
    )


def _extract_entities(template_str: str) -> set[str]:
    """Extract entity IDs referenced in a template string."""
    entities: set[str] = set()
    for pattern in _ENTITY_PATTERNS:
        for match in pattern.finditer(template_str):
            entity_id = match.group(1)
            if "." in entity_id:
                entities.add(entity_id)
    return entities


class WledTextEntity(TextEntity):
    """Text entity for a single WLED segment.

    The stored value is always treated as a Jinja2 template.
    Plain text renders to itself.  The rendered result is pushed to
    WLED and re-evaluated whenever a referenced entity changes.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:led-strip-variant"

    def __init__(
        self,
        coordinator: WledTextCoordinator,
        segment_id: int,
    ) -> None:
        """Initialize the text entity."""
        self._coordinator = coordinator
        self._segment_id = segment_id
        self._template: Template | None = None
        self._unsub_state_tracker: callback | None = None
        self._attr_native_value = ""
        self._attr_unique_id = f"{coordinator.entry_id}_seg_{segment_id}"
        self._attr_name = f"Segment {segment_id}"

    @property
    def device_info(self):
        """Return device info from coordinator."""
        return self._coordinator.device_info

    # --- template lifecycle ------------------------------------------------

    def _apply_template(self, template_str: str) -> None:
        """Set up the template and start tracking its entities."""
        self._template = Template(template_str, self.hass)
        self._stop_tracking()
        entities = _extract_entities(template_str)
        if entities:
            LOGGER.debug(
                "Segment %d tracking entities: %s",
                self._segment_id,
                entities,
            )
            self._unsub_state_tracker = async_track_state_change_event(
                self.hass,
                list(entities),
                self._handle_state_change,
            )

    def _stop_tracking(self) -> None:
        """Stop tracking state changes."""
        if self._unsub_state_tracker is not None:
            self._unsub_state_tracker()
            self._unsub_state_tracker = None

    def _render(self) -> str:
        """Render the template and return the result."""
        if self._template is None:
            return self._attr_native_value or ""
        try:
            result = self._template.async_render()
            return str(result) if result is not None else ""
        except Exception as err:
            LOGGER.warning(
                "Template render error for segment %d: %s",
                self._segment_id,
                err,
            )
            return ""

    async def _handle_state_change(self, event: Event) -> None:
        """Handle a state change event for a tracked entity."""
        rendered = self._render()
        LOGGER.debug(
            "Segment %d re-rendered after state change: %r",
            self._segment_id,
            rendered,
        )
        self._coordinator.async_schedule_push(self._segment_id, rendered)

    async def async_set_value(self, value: str) -> None:
        """Set the template value and push the rendered result to WLED."""
        self._attr_native_value = value
        self._apply_template(value)
        self.async_write_ha_state()
        rendered = self._render()
        self._coordinator.async_schedule_push(self._segment_id, rendered)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up resources when entity is removed."""
        self._stop_tracking()

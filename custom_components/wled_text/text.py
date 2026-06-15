"""Text platform for the WLED Text Display integration.

Creates one text entity per WLED segment. Each entity can either
be set manually (via text.set_value) or automatically via a
Jinja2 template that re-evaluates on entity state changes.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.template import Template

from . import WledTextCoordinator
from .const import (
    DOMAIN,
    LOGGER,
    OPT_SEG_TEMPLATE_PREFIX,
    OPT_SEG_TEMPLATE_SUFFIX,
)

# RenderInfo from homeassistant.helpers.template for entity extraction
# This may not exist in all HA versions
_HAS_RENDER_INFO = False
try:
    from homeassistant.helpers.template import RenderInfo, render_info_cv as _render_info_cv

    _HAS_RENDER_INFO = True
except ImportError:
    pass

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

    entities: list[WledTextEntity] = []
    for seg_id in range(seg_count):
        template_key = f"{OPT_SEG_TEMPLATE_PREFIX}{seg_id}{OPT_SEG_TEMPLATE_SUFFIX}"
        template_str = entry.options.get(template_key, "")
        entity = WledTextEntity(coordinator, seg_id, template_str)
        entities.append(entity)

    if entities:
        async_add_entities(entities)


def _extract_entities_via_regex(template_str: str) -> set[str]:
    """Extract entity IDs from a template string using regex patterns."""
    entities: set[str] = set()
    for pattern in _ENTITY_PATTERNS:
        for match in pattern.finditer(template_str):
            entity_id = match.group(1)
            if "." in entity_id:
                entities.add(entity_id)
    return entities


class WledTextEntity(TextEntity):
    """Text entity representing the text on a single WLED segment."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:led-strip-variant"

    def __init__(
        self,
        coordinator: WledTextCoordinator,
        segment_id: int,
        template_str: str,
    ) -> None:
        """Initialize the text entity."""
        self._coordinator = coordinator
        self._segment_id = segment_id
        self._template_str = template_str or ""
        self._template: Template | None = None
        self._unsub_state_tracker: callback | None = None
        self._attr_native_value = ""
        self._attr_unique_id = f"{coordinator.entry_id}_seg_{segment_id}"
        self._attr_name = f"Segment {segment_id}"

    @property
    def device_info(self):
        """Return device info from coordinator."""
        return self._coordinator.device_info

    async def _render_template(self) -> str | None:
        """Render the template and return the result, or None on error."""
        try:
            result = self._template.async_render()
            return str(result) if result is not None else ""
        except Exception as err:
            LOGGER.warning(
                "Template render error for segment %d: %s",
                self._segment_id,
                err,
            )
            return None

    def _extract_entities(self) -> set[str]:
        """Extract entity IDs referenced by the template.

        Uses RenderInfo if available (most accurate), falls back to
        regex-based extraction.
        """
        entities: set[str] = set()

        # Method 1: Use RenderInfo (if available)
        if _HAS_RENDER_INFO and self._template is not None:
            try:
                render_info = RenderInfo()
                token = _render_info_cv.set(render_info)
                try:
                    self._template.async_render()
                except Exception:
                    pass  # Entity collection happens during rendering
                finally:
                    _render_info_cv.reset(token)

                if render_info.entities:
                    entities = render_info.entities

                # Handle all_states tracking
                if render_info.all_states:
                    # Template references all states - track everything
                    # For now, track nothing and warn
                    LOGGER.debug(
                        "Template for segment %d tracks all states, "
                        "only specific entity tracking is supported",
                        self._segment_id,
                    )
            except Exception:
                pass

        # Method 2: Fall back to regex extraction
        if not entities:
            entities = _extract_entities_via_regex(self._template_str)

        return entities

    async def _handle_state_change(self, event: Any) -> None:
        """Handle a state change event for a tracked entity."""
        result = await self._render_template()
        if result is not None and result != self._attr_native_value:
            LOGGER.debug(
                "Template for segment %d changed to: %s",
                self._segment_id,
                result,
            )
            self._attr_native_value = result
            self.async_write_ha_state()
            self._coordinator.async_schedule_push(self._segment_id, result)

    async def async_added_to_hass(self) -> None:
        """Called when entity is added to Home Assistant."""
        await super().async_added_to_hass()

        if not self._template_str:
            return

        try:
            self._template = Template(self._template_str, self.hass)
        except Exception as err:
            LOGGER.error(
                "Invalid template for segment %d: %s",
                self._segment_id,
                err,
            )
            return

        # Extract entities and start state tracking
        entities = self._extract_entities()

        if entities:
            LOGGER.debug(
                "Tracking %d entities for segment %d: %s",
                len(entities),
                self._segment_id,
                entities,
            )
            self._unsub_state_tracker = async_track_state_change_event(
                self.hass,
                list(entities),
                self._handle_state_change,
            )

        # Initial render and push
        result = await self._render_template()
        if result is not None:
            self._attr_native_value = result
            self._coordinator.async_schedule_push(self._segment_id, result)

    async def async_set_value(self, value: str) -> None:
        """Set the text value.

        If a template is configured, manual set_value is ignored
        (the template result takes precedence).
        """
        if self._template_str:
            return

        self._attr_native_value = value
        self.async_write_ha_state()
        self._coordinator.async_schedule_push(self._segment_id, value)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up resources when entity is removed."""
        if self._unsub_state_tracker is not None:
            self._unsub_state_tracker()
            self._unsub_state_tracker = None

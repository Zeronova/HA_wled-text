"""Text platform for the WLED Text Display integration.

Creates one text entity per WLED segment. Setting the text entity
pushes the value to the corresponding WLED segment.

Special behaviour: if the stored value contains Jinja2 template
delimiters ({{ or {%), it's treated as a template and auto-rendered
on entity state changes. Static values are pushed as-is.
"""

from __future__ import annotations

import re
from typing import Any, Callable

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

# RenderInfo from homeassistant.helpers.template for accurate entity extraction
_HAS_RENDER_INFO = False
try:
    from homeassistant.helpers.template import (  # type: ignore[attr-defined]
        RenderInfo,
        render_info_cv as _render_info_cv,
    )

    _HAS_RENDER_INFO = True
except ImportError:
    pass


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


def _extract_entities_via_regex(template_str: str) -> set[str]:
    """Extract entity IDs from a template string via regex."""
    entities: set[str] = set()
    for pattern in _ENTITY_PATTERNS:
        for match in pattern.finditer(template_str):
            entity_id = match.group(1)
            if "." in entity_id:
                entities.add(entity_id)
    return entities


class WledTextEntity(TextEntity):
    """Text entity for a single WLED segment.

    When native_value contains template delimiters ({{ / {%), it is
    treated as a Jinja2 template and auto-rendered on state changes.
    Otherwise the value is pushed to WLED verbatim.
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
        self._template_raw: str = ""
        self._unsub_state_tracker: callback | None = None
        self._attr_native_value = ""
        self._attr_unique_id = f"{coordinator.entry_id}_seg_{segment_id}"
        self._attr_name = f"Segment {segment_id}"

    @property
    def device_info(self):
        """Return device info from coordinator."""
        return self._coordinator.device_info

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        attrs: dict[str, Any] = {}
        if self._template_raw:
            attrs["template"] = self._template_raw
        return attrs

    # --- template lifecycle ------------------------------------------------

    def _init_template(self, template_str: str) -> None:
        """Set up template tracking from a raw template string."""
        self._template_raw = template_str
        self._template = Template(template_str, self.hass)

        # Extract entity references (RenderInfo first, regex fallback)
        entities = self._extract_entities()

        if entities:
            self._stop_tracking()
            self._unsub_state_tracker = async_track_state_change_event(
                self.hass,
                list(entities),
                self._handle_state_change,
            )

    def _clear_template(self) -> None:
        """Remove template tracking."""
        self._template_raw = ""
        self._template = None
        self._stop_tracking()

    def _stop_tracking(self) -> None:
        """Stop tracking state changes."""
        if self._unsub_state_tracker is not None:
            self._unsub_state_tracker()
            self._unsub_state_tracker = None

    def _is_template_string(self, value: str) -> bool:
        """Check if a string looks like a Jinja2 template."""
        return "{{" in value or "{%" in value

    def _extract_entities(self) -> set[str]:
        """Extract entity IDs referenced by the template.

        Uses RenderInfo if available (most accurate), falls back to
        regex-based extraction.
        """
        entities: set[str] = set()

        if _HAS_RENDER_INFO and self._template is not None:
            try:
                render_info = RenderInfo()
                token = _render_info_cv.set(render_info)
                try:
                    self._template.async_render()
                except Exception:
                    pass  # Collection happens during rendering
                finally:
                    _render_info_cv.reset(token)

                entities = render_info.entities
            except Exception:
                pass

        if not entities:
            entities = _extract_entities_via_regex(self._template_raw)

        return entities

    def _render_template(self) -> str:
        """Render the template and return the result.

        Returns empty string on error.
        """
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
        if not self._template:
            return
        rendered = self._render_template()
        if rendered != self._attr_native_value:
            LOGGER.debug(
                "Segment %d template re-rendered: %r -> %r",
                self._segment_id,
                self._attr_native_value,
                rendered,
            )
            self._attr_native_value = rendered
            self.async_write_ha_state()
            self._coordinator.async_schedule_push(self._segment_id, rendered)

    async def async_set_value(self, value: str) -> None:
        """Set the text value.

        If the value looks like a Jinja2 template, it's stored as such
        and auto-rendered when referenced states change.  Static text
        is pushed to WLED immediately.
        """
        if self._is_template_string(value):
            self._init_template(value)
            rendered = self._render_template()
            self._attr_native_value = rendered
        else:
            self._clear_template()
            self._attr_native_value = value

        self.async_write_ha_state()
        self._coordinator.async_schedule_push(self._segment_id, self._attr_native_value)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up resources when entity is removed."""
        self._stop_tracking()

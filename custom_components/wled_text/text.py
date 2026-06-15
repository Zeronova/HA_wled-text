"""Text platform for the WLED Text Display integration.

Creates one text entity per WLED segment. Each entity can either
be set manually (via text.set_value) or automatically via a
Jinja2 template that re-evaluates on entity state changes.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.template import Template, async_track_template_result

from . import WledTextCoordinator
from .const import (
    DOMAIN,
    LOGGER,
    OPT_SEG_TEMPLATE_PREFIX,
    OPT_SEG_TEMPLATE_SUFFIX,
)


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
        self._unsub_template: callback | None = None
        self._attr_native_value = ""
        self._attr_unique_id = f"{coordinator.entry_id}_seg_{segment_id}"
        self._attr_name = f"Segment {segment_id}"

    @property
    def device_info(self):
        """Return device info from coordinator."""
        return self._coordinator.device_info

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

        self._unsub_template = async_track_template_result(
            self.hass,
            [self._template],
            self._handle_template_update,
        )

    async def _handle_template_update(
        self, event: Any, updates: list[Any]
    ) -> None:
        """Handle template result changes."""
        for update in updates:
            if getattr(update, "template", None) is self._template:
                result = str(update.result) if update.result is not None else ""
                if result != self._attr_native_value:
                    self._attr_native_value = result
                    self.async_write_ha_state()
                    self._coordinator.async_schedule_push(
                        self._segment_id, result
                    )

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
        if self._unsub_template is not None:
            self._unsub_template()
            self._unsub_template = None

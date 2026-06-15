"""Text platform for the WLED Text Display integration.

Creates one text entity per WLED segment. Setting the text entity
pushes the value to the corresponding WLED segment.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WledTextCoordinator
from .const import DOMAIN, LOGGER


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
        entity = WledTextEntity(coordinator, seg_id)
        entities.append(entity)

    async_add_entities(entities)


class WledTextEntity(TextEntity):
    """Text entity representing the text on a single WLED segment."""

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
        self._attr_native_value = ""
        self._attr_unique_id = f"{coordinator.entry_id}_seg_{segment_id}"
        self._attr_name = f"Segment {segment_id}"

    @property
    def device_info(self):
        """Return device info from coordinator."""
        return self._coordinator.device_info

    async def async_set_value(self, value: str) -> None:
        """Set the text and push to WLED."""
        self._attr_native_value = value
        self.async_write_ha_state()
        self._coordinator.async_schedule_push(self._segment_id, value)

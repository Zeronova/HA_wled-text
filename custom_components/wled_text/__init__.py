"""The WLED Text Display integration.

Displays text on WLED segments by pushing text content
via the WLED JSON API. Supports templates for dynamic content.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    DATA_HOST,
    DATA_NAME,
    DATA_PORT,
    DATA_SEG_COUNT,
    DATA_WLED_NAME,
    DATA_WLED_VERSION,
    DEFAULT_PORT,
    DOMAIN,
    ENDPOINT_STATE,
    LOGGER,
    PUSH_DEBOUNCE,
)

PLATFORMS = [Platform.TEXT]


class WledTextCoordinator:
    """Coordinates text pushing to a WLED controller."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        host: str,
        port: int,
        name: str,
        wled_name: str | None = None,
        wled_version: str | None = None,
        seg_count: int = 1,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self._host = host
        self._port = port
        self._name = name
        self._wled_name = wled_name or name
        self._wled_version = wled_version
        self._seg_count = seg_count

        self._texts: dict[int, str] = {}
        self._debounce_timer: asyncio.TimerHandle | None = None
        self._push_lock = asyncio.Lock()
        self._device_info: DeviceInfo | None = None
        self._session: aiohttp.ClientSession | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this WLED controller."""
        if self._device_info is None:
            self._device_info = DeviceInfo(
                identifiers={(DOMAIN, self.entry_id)},
                name=self._name,
                manufacturer="WLED",
                model="WLED Controller",
                sw_version=self._wled_version or "unknown",
                configuration_url=f"http://{self._host}:{self._port}",
            )
        return self._device_info

    @property
    def session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None:
            self._session = async_get_clientsession(self.hass)
        return self._session

    async def async_get_segments(self) -> int:
        """Fetch segment count from WLED."""
        url = f"http://{self._host}:{self._port}{ENDPOINT_STATE}"
        try:
            async with self.session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    return 0
                data = await resp.json()
                segments = data.get("seg", [])
                return len(segments)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            LOGGER.warning("Could not fetch segments from %s: %s", self._host, err)
            return 0

    def async_schedule_push(self, segment_id: int, text: str) -> None:
        """Schedule a push to WLED, debouncing within the configured window."""
        self._texts[segment_id] = text
        self._cancel_debounce()
        self._debounce_timer = self.hass.loop.call_later(
            PUSH_DEBOUNCE,
            lambda: self.hass.async_create_task(self._async_push_all()),
        )

    def _cancel_debounce(self) -> None:
        """Cancel a pending debounce timer."""
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
            self._debounce_timer = None

    async def _async_push_all(self) -> None:
        """Push all pending texts to WLED."""
        if self._push_lock.locked():
            return

        async with self._push_lock:
            if not self._texts:
                return

            # Build segment array
            segs = [
                {"id": sid, "n": text}
                for sid, text in sorted(self._texts.items())
                if text
            ]
            if not segs:
                return

            payload = {"seg": segs}
            url = f"http://{self._host}:{self._port}{ENDPOINT_STATE}"

            try:
                async with self.session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status != 200:
                        LOGGER.warning(
                            "WLED push failed (status %s) to %s", resp.status, self._host
                        )
                    else:
                        LOGGER.debug(
                            "Pushed %d segment texts to %s", len(segs), self._host
                        )
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                LOGGER.warning(
                    "WLED push error to %s: %s", self._host, err
                )

    async def async_shutdown(self) -> None:
        """Clean up resources."""
        self._cancel_debounce()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WLED Text from a config entry."""
    coordinator = WledTextCoordinator(
        hass,
        entry_id=entry.entry_id,
        host=entry.data[DATA_HOST],
        port=entry.data.get(DATA_PORT, DEFAULT_PORT),
        name=entry.data.get(DATA_NAME, entry.title),
        wled_name=entry.data.get(DATA_WLED_NAME),
        wled_version=entry.data.get(DATA_WLED_VERSION),
        seg_count=entry.data.get(DATA_SEG_COUNT, 1),
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle config entry update (options change)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_shutdown()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok

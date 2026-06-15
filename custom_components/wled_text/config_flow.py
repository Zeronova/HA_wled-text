"""Config flow for WLED Text Display integration."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    DEFAULT_PORT,
    DOMAIN,
    LOGGER,
    DATA_HOST,
    DATA_PORT,
    DATA_NAME,
    DATA_WLED_VERSION,
    DATA_WLED_NAME,
    DATA_SEG_COUNT,
    ENDPOINT_INFO,
    ENDPOINT_STATE,
)


class WledTextConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WLED Text Display."""

    VERSION = 1

    async def _try_connect(self, host: str, port: int) -> dict[str, Any] | None:
        """Test connection and return WLED info."""
        url_info = f"http://{host}:{port}{ENDPOINT_INFO}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url_info, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return None

    async def _fetch_segments(self, host: str, port: int) -> list[dict[str, Any]]:
        """Fetch segments from WLED."""
        url = f"http://{host}:{port}{ENDPOINT_STATE}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    return data.get("seg", [])
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            name = user_input[CONF_NAME].strip() or host

            info = await self._try_connect(host, port)
            if info is None:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{host}_{port}")
                self._abort_if_unique_id_configured()

                # Discover segments
                segments = await self._fetch_segments(host, port)
                seg_count = max(len(segments), 1)

                wled_name = info.get("name", name)
                wled_version = info.get("ver", "unknown")

                return self.async_create_entry(
                    title=name,
                    data={
                        DATA_HOST: host,
                        DATA_PORT: port,
                        DATA_NAME: name,
                        DATA_WLED_NAME: wled_name,
                        DATA_WLED_VERSION: wled_version,
                        DATA_SEG_COUNT: seg_count,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=""): str,
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

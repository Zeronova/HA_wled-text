"""Constants for the WLED Text Display integration."""

from __future__ import annotations

import logging

DOMAIN = "wled_text"
LOGGER = logging.getLogger(__package__)

CONF_HOST = "host"
CONF_PORT = "port"
CONF_NAME = "name"

DEFAULT_PORT = 80

# Config entry data keys
DATA_HOST = "host"
DATA_PORT = "port"
DATA_NAME = "name"
DATA_WLED_VERSION = "wled_version"
DATA_WLED_NAME = "wled_name"
DATA_SEG_COUNT = "seg_count"

# API endpoints
ENDPOINT_INFO = "/json/info"
ENDPOINT_STATE = "/json/state"

# Debounce delay (seconds)
PUSH_DEBOUNCE = 0.3

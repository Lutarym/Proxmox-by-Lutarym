"""Diagnosedaten fuer die Proxmox Integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_HOST, CONF_PASSWORD, CONF_TOKEN_ID, CONF_TOKEN_SECRET, CONF_USER, DOMAIN
from .coordinator import ProxmoxCoordinator

REDACT_CONFIG = {CONF_HOST, CONF_USER, CONF_TOKEN_ID, CONF_TOKEN_SECRET, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Diagnosedaten zusammenstellen."""
    coordinator: ProxmoxCoordinator = hass.data[DOMAIN][entry.entry_id]

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), REDACT_CONFIG),
            "options": dict(entry.options),
        },
        "last_update_success": coordinator.last_update_success,
        "update_interval": (
            coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None
        ),
        "data": coordinator.data,
        "pending_removal": (
            coordinator.tracker.async_pending()
            if getattr(coordinator, "tracker", None) is not None
            else []
        ),
    }

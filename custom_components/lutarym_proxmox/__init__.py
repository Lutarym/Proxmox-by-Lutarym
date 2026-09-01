"""Lutarym Proxmox VE Integration fuer Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .api import ProxmoxClient
from .cleanup import StaleResourceTracker
from .const import (
    CONF_AUTO_ADD,
    CONF_ENABLE_CONTROLS,
    CONF_GRACE_PERIOD,
    CONF_INCLUDE_TEMPLATES,
    CONF_NODE_DETAILS,
    CONF_TASK_WINDOW,
    CONF_TIMEOUT,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_REALM,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    CONF_USER,
    CONF_VERIFY_SSL,
    DEFAULT_ENABLE_CONTROLS,
    DEFAULT_GRACE_PERIOD,
    DEFAULT_NODE_DETAILS,
    DEFAULT_PORT,
    DEFAULT_REALM,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TASK_WINDOW,
    DEFAULT_TIMEOUT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    EXCLUDE_KEYS,
    INCLUDE_KEYS,
)
from .coordinator import ProxmoxCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config Entry einrichten."""
    client = ProxmoxClient(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        user=entry.data[CONF_USER],
        realm=entry.data.get(CONF_REALM, DEFAULT_REALM),
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        token_id=entry.data.get(CONF_TOKEN_ID) or None,
        token_secret=entry.data.get(CONF_TOKEN_SECRET) or None,
        password=entry.data.get(CONF_PASSWORD) or None,
        timeout=int(entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
    )

    coordinator = ProxmoxCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    tracker = StaleResourceTracker(hass, entry, coordinator)
    await tracker.async_load()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    coordinator.tracker = tracker

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    tracker.async_check()
    entry.async_on_unload(coordinator.async_add_listener(tracker.async_check))

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Merkzettel der Vorhaltezeit mitloeschen."""
    tracker = StaleResourceTracker(hass, entry, None)  # type: ignore[arg-type]
    await tracker.async_remove_storage()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Config Entry entladen."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN, None)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Aeltere Eintraege auf das neue Auswahlformat heben.

    Version 1 kannte nur Einschlusslisten. Damit bestehende Installationen ihr
    Verhalten behalten, wird die Auto-Uebernahme dort abgeschaltet. Sie laesst
    sich unter Konfigurieren jederzeit einschalten.
    """
    if entry.version > 2:
        return False

    if entry.version == 1:
        options = dict(entry.options)
        migrated = {
            CONF_AUTO_ADD: False,
            CONF_GRACE_PERIOD: DEFAULT_GRACE_PERIOD,
            CONF_SCAN_INTERVAL: options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            CONF_ENABLE_CONTROLS: DEFAULT_ENABLE_CONTROLS,
            CONF_NODE_DETAILS: DEFAULT_NODE_DETAILS,
            CONF_TASK_WINDOW: DEFAULT_TASK_WINDOW,
            # Version 1 hat Templates mitgezaehlt, das bleibt so erhalten
            CONF_INCLUDE_TEMPLATES: True,
        }
        for resource_type, include_key in INCLUDE_KEYS.items():
            migrated[include_key] = options.get(include_key, [])
            migrated[EXCLUDE_KEYS[resource_type]] = []

        hass.config_entries.async_update_entry(entry, options=migrated, version=2)
        _LOGGER.info(
            "Proxmox-Eintrag auf Version 2 gehoben, Auto-Uebernahme bleibt aus"
        )

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Bei geaenderten Optionen neu laden."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Manuelles Entfernen erlauben, solange die Ressource weg ist."""
    coordinator: ProxmoxCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if coordinator is None or not coordinator.data:
        return True

    valid = coordinator.valid_device_ids()
    if any(
        identifier[0] == DOMAIN and identifier[1] in valid
        for identifier in device_entry.identifiers
    ):
        return False

    tracker = getattr(coordinator, "tracker", None)
    if tracker is not None:
        for identifier in device_entry.identifiers:
            if identifier[0] == DOMAIN:
                tracker.async_forget(identifier[1])

    return True

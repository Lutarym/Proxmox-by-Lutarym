"""Binary Sensoren fuer Proxmox VE."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TYPE_LXC, TYPE_NODE, TYPE_QEMU, TYPE_STORAGE
from .coordinator import ProxmoxCoordinator
from .entity import ProxmoxEntity, async_setup_dynamic_entities


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Binary Sensoren anlegen und neue Ressourcen laufend nachziehen."""
    coordinator: ProxmoxCoordinator = hass.data[DOMAIN][entry.entry_id]

    def _build(resource_type: str, resource_key: str) -> list[BinarySensorEntity]:
        if resource_type == TYPE_NODE:
            return [ProxmoxNodeOnline(coordinator, resource_key)]
        if resource_type == TYPE_STORAGE:
            return [ProxmoxStorageActive(coordinator, resource_key)]
        return [ProxmoxGuestRunning(coordinator, resource_type, resource_key)]

    async_setup_dynamic_entities(entry, coordinator, async_add_entities, _build)


class ProxmoxNodeOnline(ProxmoxEntity, BinarySensorEntity):
    """Node online oder offline."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "node_online"

    def __init__(self, coordinator: ProxmoxCoordinator, node: str) -> None:
        super().__init__(coordinator, TYPE_NODE, node, "online")

    @property
    def is_on(self) -> bool | None:
        """True wenn der Node online ist."""
        res = self.resource
        if res is None:
            return None
        return res.get("status") == "online"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Zusatzinfos zum Node."""
        res = self.resource or {}
        return {
            "node": res.get("node"),
            "level": res.get("level"),
            "cpu_cores": res.get("maxcpu"),
        }


class ProxmoxGuestRunning(ProxmoxEntity, BinarySensorEntity):
    """VM oder Container laeuft."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_translation_key = "guest_running"

    def __init__(
        self, coordinator: ProxmoxCoordinator, guest_type: str, vmid: str
    ) -> None:
        super().__init__(coordinator, guest_type, vmid, "running")

    @property
    def is_on(self) -> bool | None:
        """True wenn der Gast laeuft."""
        res = self.resource
        if res is None:
            return None
        return res.get("status") == "running"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Zusatzinfos zum Gast."""
        res = self.resource or {}
        return {
            "vmid": res.get("vmid"),
            "node": res.get("node"),
            "status": res.get("status"),
            "template": bool(res.get("template")),
            "tags": res.get("tags"),
        }


class ProxmoxStorageActive(ProxmoxEntity, BinarySensorEntity):
    """Storage aktiv oder nicht."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "storage_problem"

    def __init__(self, coordinator: ProxmoxCoordinator, storage_id: str) -> None:
        super().__init__(coordinator, TYPE_STORAGE, storage_id, "problem")

    @property
    def is_on(self) -> bool | None:
        """True bedeutet Problem, also Storage nicht verfuegbar."""
        res = self.resource
        if res is None:
            return None
        return res.get("status") != "available"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Zusatzinfos zum Storage."""
        res = self.resource or {}
        return {
            "storage": res.get("storage"),
            "node": res.get("node"),
            "plugintype": res.get("plugintype"),
            "content": res.get("content"),
            "shared": bool(res.get("shared")),
            "status": res.get("status"),
        }

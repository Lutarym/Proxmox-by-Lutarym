"""Steuer-Buttons fuer VMs und Container."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLE_CONTROLS, DEFAULT_ENABLE_CONTROLS, DOMAIN, TYPE_LXC, TYPE_QEMU
from .coordinator import ProxmoxCoordinator
from .entity import ProxmoxEntity, async_setup_dynamic_entities


@dataclass(frozen=True, kw_only=True)
class ProxmoxButtonDescription(ButtonEntityDescription):
    """Beschreibt einen Steuer-Button."""

    command: str
    requires_running: bool


QEMU_BUTTONS: tuple[ProxmoxButtonDescription, ...] = (
    ProxmoxButtonDescription(
        key="start",
        translation_key="start",
        command="start",
        requires_running=False,
    ),
    ProxmoxButtonDescription(
        key="shutdown",
        translation_key="shutdown",
        command="shutdown",
        requires_running=True,
    ),
    ProxmoxButtonDescription(
        key="stop",
        translation_key="stop",
        command="stop",
        requires_running=True,
    ),
    ProxmoxButtonDescription(
        key="reboot",
        translation_key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        command="reboot",
        requires_running=True,
    ),
    ProxmoxButtonDescription(
        key="reset",
        translation_key="reset",
        device_class=ButtonDeviceClass.RESTART,
        command="reset",
        requires_running=True,
        entity_registry_enabled_default=False,
    ),
    ProxmoxButtonDescription(
        key="suspend",
        translation_key="suspend",
        command="suspend",
        requires_running=True,
        entity_registry_enabled_default=False,
    ),
    ProxmoxButtonDescription(
        key="resume",
        translation_key="resume",
        command="resume",
        requires_running=False,
        entity_registry_enabled_default=False,
    ),
)

LXC_BUTTONS: tuple[ProxmoxButtonDescription, ...] = (
    ProxmoxButtonDescription(
        key="start",
        translation_key="start",
        command="start",
        requires_running=False,
    ),
    ProxmoxButtonDescription(
        key="shutdown",
        translation_key="shutdown",
        command="shutdown",
        requires_running=True,
    ),
    ProxmoxButtonDescription(
        key="stop",
        translation_key="stop",
        command="stop",
        requires_running=True,
    ),
    ProxmoxButtonDescription(
        key="reboot",
        translation_key="reboot",
        device_class=ButtonDeviceClass.RESTART,
        command="reboot",
        requires_running=True,
    ),
)


BUTTONS_BY_TYPE = {
    TYPE_QEMU: QEMU_BUTTONS,
    TYPE_LXC: LXC_BUTTONS,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Buttons anlegen und neue Gaeste laufend nachziehen."""
    settings = {**entry.data, **entry.options}
    if not settings.get(CONF_ENABLE_CONTROLS, DEFAULT_ENABLE_CONTROLS):
        return

    coordinator: ProxmoxCoordinator = hass.data[DOMAIN][entry.entry_id]

    def _build(resource_type: str, resource_key: str) -> list[ButtonEntity]:
        descriptions = BUTTONS_BY_TYPE.get(resource_type)
        if not descriptions:
            return []
        return [
            ProxmoxGuestButton(coordinator, resource_type, resource_key, description)
            for description in descriptions
        ]

    async_setup_dynamic_entities(entry, coordinator, async_add_entities, _build)


class ProxmoxGuestButton(ProxmoxEntity, ButtonEntity):
    """Sendet einen Steuerbefehl an VM oder Container."""

    entity_description: ProxmoxButtonDescription

    def __init__(
        self,
        coordinator: ProxmoxCoordinator,
        guest_type: str,
        vmid: str,
        description: ProxmoxButtonDescription,
    ) -> None:
        super().__init__(coordinator, guest_type, vmid, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Button nur anbieten, wenn der Befehl sinnvoll ist."""
        if not super().available:
            return False
        res = self.resource or {}
        if res.get("template"):
            return False
        running = res.get("status") == "running"
        if self.entity_description.requires_running:
            return running
        if self.entity_description.key == "start":
            return not running
        return True

    async def async_press(self) -> None:
        """Befehl ausfuehren."""
        res = self.resource
        if res is None:
            return
        await self.coordinator.async_guest_command(
            node=str(res.get("node")),
            vm_type=self._resource_type,
            vmid=int(res.get("vmid")),
            command=self.entity_description.command,
        )

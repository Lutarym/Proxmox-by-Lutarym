"""Gemeinsame Basisklasse fuer alle Proxmox-Entitaeten."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    SIGNAL_RESOURCE_REMOVED,
    TYPE_LXC,
    TYPE_NODE,
    TYPE_QEMU,
    TYPE_STORAGE,
)
from .coordinator import ProxmoxCoordinator

_LOGGER = logging.getLogger(__name__)

MODEL_NAMES = {
    TYPE_NODE: "Node",
    TYPE_QEMU: "Virtuelle Maschine",
    TYPE_LXC: "LXC Container",
    TYPE_STORAGE: "Storage",
}


@callback
def async_setup_dynamic_entities(
    entry: ConfigEntry,
    coordinator: ProxmoxCoordinator,
    async_add_entities: AddEntitiesCallback,
    build: Callable[[str, str], Iterable[Entity]],
) -> None:
    """Entitaeten anlegen und bei jedem Update auf neue Ressourcen pruefen.

    Legt eine spaeter in Proxmox erstellte VM, einen neuen Container, Node oder
    Storage ohne Neustart als Entitaeten an.

    Ein Schluessel wird bewusst erst dann vergessen, wenn das Geraet nach
    Ablauf der Vorhaltezeit tatsaechlich entfernt wurde. Wuerde er schon beim
    Verschwinden der Ressource vergessen, legte eine Rueckkehr Entitaeten mit
    bereits vergebener unique_id an, die Home Assistant verwirft.
    """
    known: set[tuple[str, str]] = set()

    @callback
    def _sync() -> None:
        if not coordinator.last_update_success:
            return

        new = coordinator.current_keys() - known
        if not new:
            return

        known.update(new)

        entities: list[Entity] = []
        for resource_type, resource_key in sorted(new):
            entities.extend(build(resource_type, resource_key))

        if entities:
            _LOGGER.debug("Lege %d neue Entitaeten an", len(entities))
            async_add_entities(entities)

    @callback
    def _forget(resource: tuple[str, str]) -> None:
        """Nach dem Entfernen eines Geraets darf die Ressource wiederkommen."""
        known.discard(resource)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))
    entry.async_on_unload(
        async_dispatcher_connect(
            coordinator.hass,
            SIGNAL_RESOURCE_REMOVED.format(entry.entry_id),
            _forget,
        )
    )


class ProxmoxEntity(CoordinatorEntity[ProxmoxCoordinator]):
    """Basis fuer Sensoren, Binary Sensoren und Buttons."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ProxmoxCoordinator,
        resource_type: str,
        resource_key: str,
        entity_key: str,
    ) -> None:
        super().__init__(coordinator)
        self._resource_type = resource_type
        self._resource_key = resource_key
        self._entity_key = entity_key

        entry_id = coordinator.entry.entry_id
        safe_key = str(resource_key).replace("/", "_")
        self._attr_unique_id = (
            f"{entry_id}_{resource_type}_{safe_key}_{entity_key}"
        )

    @property
    def _bucket(self) -> dict[str, Any]:
        """Datenbereich, in dem diese Ressource liegt."""
        if not self.coordinator.data:
            return {}
        if self._resource_type == TYPE_NODE:
            return self.coordinator.data.get("nodes", {})
        if self._resource_type == TYPE_STORAGE:
            return self.coordinator.data.get("storage", {})
        return self.coordinator.data.get(self._resource_type, {})

    @property
    def resource(self) -> dict[str, Any] | None:
        """Rohdaten dieser Ressource aus dem letzten Abruf."""
        return self._bucket.get(self._resource_key)

    @property
    def available(self) -> bool:
        """Entitaet ist nur verfuegbar, wenn die Ressource noch existiert."""
        return super().available and self.resource is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Geraeteeintrag, an dem diese Entitaet haengt."""
        res = self.resource or {}
        entry_id = self.coordinator.entry.entry_id

        if self._resource_type == TYPE_NODE:
            name = f"Proxmox Node {self._resource_key}"
        elif self._resource_type == TYPE_STORAGE:
            storage = res.get("storage", self._resource_key)
            node = res.get("node", "")
            name = f"Proxmox Storage {storage} ({node})" if node else f"Proxmox Storage {storage}"
        else:
            guest_name = res.get("name") or self._resource_key
            name = f"{guest_name} ({self._resource_key})"

        return DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{self._resource_type}_{self._resource_key}")},
            name=name,
            manufacturer=MANUFACTURER,
            model=MODEL_NAMES.get(self._resource_type, "Proxmox"),
            configuration_url=(
                f"https://{self.coordinator.entry.data['host']}:"
                f"{self.coordinator.entry.data.get('port', 8006)}/"
            ),
        )

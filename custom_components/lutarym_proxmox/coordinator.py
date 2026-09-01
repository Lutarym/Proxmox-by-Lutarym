"""DataUpdateCoordinator fuer Proxmox VE."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ProxmoxAuthError, ProxmoxClient, ProxmoxConnectionError
from .const import (
    CONF_AUTO_ADD,
    CONF_INCLUDE_TEMPLATES,
    CONF_NODE_DETAILS,
    CONF_SCAN_INTERVAL,
    CONF_TASK_WINDOW,
    DEFAULT_AUTO_ADD,
    DEFAULT_INCLUDE_TEMPLATES,
    DEFAULT_NODE_DETAILS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TASK_WINDOW,
    DOMAIN,
    EXCLUDE_KEYS,
    INCLUDE_KEYS,
    MAX_TASKS,
    TYPE_LXC,
    TYPE_NODE,
    TYPE_QEMU,
    TYPE_STORAGE,
)

_LOGGER = logging.getLogger(__name__)

RESOURCE_TYPES = (TYPE_NODE, TYPE_QEMU, TYPE_LXC, TYPE_STORAGE)

BUCKETS = {
    TYPE_NODE: "nodes",
    TYPE_QEMU: "qemu",
    TYPE_LXC: "lxc",
    TYPE_STORAGE: "storage",
}


class ProxmoxCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Holt alle Proxmox-Daten in einem Zyklus."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ProxmoxClient,
    ) -> None:
        settings = {**entry.data, **entry.options}

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=settings.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )

        self.entry = entry
        self.client = client
        self.tracker: Any = None

        self.auto_add: bool = bool(settings.get(CONF_AUTO_ADD, DEFAULT_AUTO_ADD))
        self.node_details: bool = bool(
            settings.get(CONF_NODE_DETAILS, DEFAULT_NODE_DETAILS)
        )
        self.include_templates: bool = bool(
            settings.get(CONF_INCLUDE_TEMPLATES, DEFAULT_INCLUDE_TEMPLATES)
        )
        self.task_window: float = float(
            settings.get(CONF_TASK_WINDOW, DEFAULT_TASK_WINDOW)
        )
        self._include: dict[str, set[str]] = {
            rtype: set(settings.get(INCLUDE_KEYS[rtype], []) or [])
            for rtype in RESOURCE_TYPES
        }
        self._exclude: dict[str, set[str]] = {
            rtype: set(settings.get(EXCLUDE_KEYS[rtype], []) or [])
            for rtype in RESOURCE_TYPES
        }

    def _wanted(self, resource_type: str, key: str) -> bool:
        """Entscheidet, ob eine Ressource ueberwacht werden soll.

        Bei aktivierter Auto-Uebernahme zaehlt nur die Ausschlussliste, damit
        spaeter angelegte VMs und Container von selbst dazukommen. Ist sie
        abgeschaltet, wird strikt gegen die Einschlussliste geprueft.
        """
        if self.auto_add:
            return key not in self._exclude[resource_type]

        include = self._include[resource_type]
        if not include:
            return True
        return key in include

    async def _async_update_data(self) -> dict[str, Any]:
        """Von Home Assistant im Update-Intervall aufgerufen."""
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except ProxmoxAuthError as err:
            raise ConfigEntryAuthFailed(f"Anmeldung abgelehnt: {err}") from err
        except ProxmoxConnectionError as err:
            raise UpdateFailed(f"Proxmox nicht erreichbar: {err}") from err

    def _fetch(self) -> dict[str, Any]:
        """Blockierender Teil des Datenabrufs."""
        data: dict[str, Any] = {
            "version": {},
            "nodes": {},
            "qemu": {},
            "lxc": {},
            "storage": {},
            "tasks": [],
            "failed_tasks": 0,
        }

        data["version"] = self.client.get_version()
        resources = self.client.get_resources()

        for res in resources:
            res_type = res.get("type")

            if res_type == TYPE_NODE:
                node = str(res.get("node", ""))
                if not node or not self._wanted(TYPE_NODE, node):
                    continue
                data["nodes"][node] = dict(res)

            elif res_type in (TYPE_QEMU, TYPE_LXC):
                vmid = res.get("vmid")
                if vmid is None:
                    continue
                if res.get("template") and not self.include_templates:
                    continue
                vmid_str = str(vmid)
                if not self._wanted(res_type, vmid_str):
                    continue
                data[res_type][vmid_str] = dict(res)

            elif res_type == TYPE_STORAGE:
                storage_id = res.get("id")
                if not storage_id:
                    continue
                storage_id = str(storage_id)
                if not self._wanted(TYPE_STORAGE, storage_id):
                    continue
                data["storage"][storage_id] = dict(res)

        for node in list(data["nodes"]) if self.node_details else []:
            try:
                status = self.client.get_node_status(node)
            except ProxmoxConnectionError as err:
                _LOGGER.debug("Node-Status %s nicht abrufbar: %s", node, err)
                continue
            data["nodes"][node]["detail"] = status

        tasks = self.client.get_tasks()
        data["tasks"] = tasks[:MAX_TASKS]
        data["failed_tasks"] = self.client.count_failed_tasks(tasks, self.task_window)

        return data

    def current_keys(self) -> set[tuple[str, str]]:
        """Alle aktuell vorhandenen Ressourcen als Typ-Schluessel-Paare.

        Grundlage dafuer, dass Plattformen neue Entitaeten nachlegen und
        verschwundene erkennen koennen.
        """
        if not self.data:
            return set()
        return {
            (rtype, key)
            for rtype in RESOURCE_TYPES
            for key in self.data.get(BUCKETS[rtype], {})
        }

    def valid_device_ids(self) -> set[str]:
        """Geraete-Identifier, die es aktuell noch geben darf."""
        entry_id = self.entry.entry_id
        ids = {f"{entry_id}_cluster"}
        for rtype, key in self.current_keys():
            ids.add(f"{entry_id}_{rtype}_{key}")
        return ids

    async def async_guest_command(
        self, node: str, vm_type: str, vmid: int, command: str
    ) -> None:
        """Steuerbefehl senden und danach sofort aktualisieren."""
        try:
            await self.hass.async_add_executor_job(
                self.client.guest_command, node, vm_type, vmid, command
            )
        except (ProxmoxAuthError, ProxmoxConnectionError) as err:
            _LOGGER.error(
                "Befehl %s fuer %s %s auf %s fehlgeschlagen: %s",
                command,
                vm_type,
                vmid,
                node,
                err,
            )
            raise
        await self.async_request_refresh()

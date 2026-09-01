"""Sensoren fuer Proxmox VE."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TYPE_LXC, TYPE_NODE, TYPE_QEMU, TYPE_STORAGE
from .coordinator import ProxmoxCoordinator
from .entity import ProxmoxEntity, async_setup_dynamic_entities

_LOGGER = logging.getLogger(__name__)

UPTIME_TOLERANCE = 30


def _ratio(value: Any, maximum: Any) -> float | None:
    """Anteil in Prozent, oder None wenn nicht berechenbar."""
    try:
        value = float(value)
        maximum = float(maximum)
    except (TypeError, ValueError):
        return None
    if maximum <= 0:
        return None
    return value / maximum * 100


def _number(value: Any) -> float | int | None:
    """Zahl oder None, ohne Exception bei fehlenden Feldern."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, kw_only=True)
class ProxmoxSensorDescription(SensorEntityDescription):
    """Beschreibt einen Proxmox-Sensor."""

    value_fn: Callable[[dict[str, Any]], Any]


def _detail(res: dict[str, Any], *path: str) -> Any:
    """Wert aus dem Detailstatus eines Nodes lesen."""
    current: Any = res.get("detail") or {}
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


NODE_SENSORS: tuple[ProxmoxSensorDescription, ...] = (
    ProxmoxSensorDescription(
        key="cpu",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda res: (
            float(res["cpu"]) * 100 if _number(res.get("cpu")) is not None else None
        ),
    ),
    ProxmoxSensorDescription(
        key="cpu_cores",
        translation_key="cpu_cores",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda res: _number(res.get("maxcpu")),
    ),
    ProxmoxSensorDescription(
        key="memory_percent",
        translation_key="memory_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda res: _ratio(res.get("mem"), res.get("maxmem")),
    ),
    ProxmoxSensorDescription(
        key="memory_used",
        translation_key="memory_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda res: _number(res.get("mem")),
    ),
    ProxmoxSensorDescription(
        key="memory_total",
        translation_key="memory_total",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
        value_fn=lambda res: _number(res.get("maxmem")),
    ),
    ProxmoxSensorDescription(
        key="disk_percent",
        translation_key="disk_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda res: _ratio(res.get("disk"), res.get("maxdisk")),
    ),
    ProxmoxSensorDescription(
        key="disk_used",
        translation_key="disk_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda res: _number(res.get("disk")),
    ),
    ProxmoxSensorDescription(
        key="disk_total",
        translation_key="disk_total",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
        value_fn=lambda res: _number(res.get("maxdisk")),
    ),
    ProxmoxSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda res: _number(res.get("uptime")),
    ),
    ProxmoxSensorDescription(
        key="load_1",
        translation_key="load_1",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda res: _number((_detail(res, "loadavg") or [None])[0]),
    ),
    ProxmoxSensorDescription(
        key="load_5",
        translation_key="load_5",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda res: _number(
            (_detail(res, "loadavg") or [None, None])[1]
            if len(_detail(res, "loadavg") or []) > 1
            else None
        ),
    ),
    ProxmoxSensorDescription(
        key="load_15",
        translation_key="load_15",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda res: _number(
            (_detail(res, "loadavg") or [None, None, None])[2]
            if len(_detail(res, "loadavg") or []) > 2
            else None
        ),
    ),
    ProxmoxSensorDescription(
        key="io_wait",
        translation_key="io_wait",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda res: (
            float(_detail(res, "wait")) * 100
            if _number(_detail(res, "wait")) is not None
            else None
        ),
    ),
    ProxmoxSensorDescription(
        key="swap_percent",
        translation_key="swap_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda res: _ratio(
            _detail(res, "swap", "used"), _detail(res, "swap", "total")
        ),
    ),
    ProxmoxSensorDescription(
        key="rootfs_percent",
        translation_key="rootfs_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda res: _ratio(
            _detail(res, "rootfs", "used"), _detail(res, "rootfs", "total")
        ),
    ),
    ProxmoxSensorDescription(
        key="kernel_version",
        translation_key="kernel_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda res: _detail(res, "kversion"),
    ),
    ProxmoxSensorDescription(
        key="pve_version",
        translation_key="pve_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda res: _detail(res, "pveversion"),
    ),
)

GUEST_SENSORS: tuple[ProxmoxSensorDescription, ...] = (
    ProxmoxSensorDescription(
        key="cpu",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda res: (
            float(res["cpu"]) * 100 if _number(res.get("cpu")) is not None else None
        ),
    ),
    ProxmoxSensorDescription(
        key="cpu_cores",
        translation_key="cpu_cores",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda res: _number(res.get("maxcpu")),
    ),
    ProxmoxSensorDescription(
        key="memory_percent",
        translation_key="memory_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda res: _ratio(res.get("mem"), res.get("maxmem")),
    ),
    ProxmoxSensorDescription(
        key="memory_used",
        translation_key="memory_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda res: _number(res.get("mem")),
    ),
    ProxmoxSensorDescription(
        key="memory_total",
        translation_key="memory_total",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
        value_fn=lambda res: _number(res.get("maxmem")),
    ),
    ProxmoxSensorDescription(
        key="disk_percent",
        translation_key="disk_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda res: _ratio(res.get("disk"), res.get("maxdisk")),
    ),
    ProxmoxSensorDescription(
        key="disk_used",
        translation_key="disk_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda res: _number(res.get("disk")),
    ),
    ProxmoxSensorDescription(
        key="disk_total",
        translation_key="disk_total",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        suggested_display_precision=2,
        value_fn=lambda res: _number(res.get("maxdisk")),
    ),
    ProxmoxSensorDescription(
        key="network_in",
        translation_key="network_in",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda res: _number(res.get("netin")),
    ),
    ProxmoxSensorDescription(
        key="network_out",
        translation_key="network_out",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda res: _number(res.get("netout")),
    ),
    ProxmoxSensorDescription(
        key="disk_read",
        translation_key="disk_read",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda res: _number(res.get("diskread")),
    ),
    ProxmoxSensorDescription(
        key="disk_write",
        translation_key="disk_write",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda res: _number(res.get("diskwrite")),
    ),
    ProxmoxSensorDescription(
        key="last_boot",
        translation_key="last_boot",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda res: _number(res.get("uptime")),
    ),
    ProxmoxSensorDescription(
        key="status_text",
        translation_key="status_text",
        device_class=SensorDeviceClass.ENUM,
        options=["running", "stopped", "paused", "suspended", "unknown"],
        value_fn=lambda res: res.get("status") or "unknown",
    ),
)

STORAGE_SENSORS: tuple[ProxmoxSensorDescription, ...] = (
    ProxmoxSensorDescription(
        key="disk_percent",
        translation_key="disk_percent",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda res: _ratio(res.get("disk"), res.get("maxdisk")),
    ),
    ProxmoxSensorDescription(
        key="disk_used",
        translation_key="disk_used",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda res: _number(res.get("disk")),
    ),
    ProxmoxSensorDescription(
        key="disk_free",
        translation_key="disk_free",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda res: (
            float(res["maxdisk"]) - float(res["disk"])
            if _number(res.get("maxdisk")) is not None
            and _number(res.get("disk")) is not None
            else None
        ),
    ),
    ProxmoxSensorDescription(
        key="disk_total",
        translation_key="disk_total",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        suggested_display_precision=2,
        value_fn=lambda res: _number(res.get("maxdisk")),
    ),
)


DETAIL_ONLY_KEYS = frozenset(
    {
        "load_1",
        "load_5",
        "load_15",
        "io_wait",
        "swap_percent",
        "rootfs_percent",
        "kernel_version",
        "pve_version",
    }
)

DESCRIPTIONS_BY_TYPE = {
    TYPE_NODE: NODE_SENSORS,
    TYPE_QEMU: GUEST_SENSORS,
    TYPE_LXC: GUEST_SENSORS,
    TYPE_STORAGE: STORAGE_SENSORS,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sensoren anlegen und neue Ressourcen laufend nachziehen."""
    coordinator: ProxmoxCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([ProxmoxFailedTaskSensor(coordinator)])

    def _build(resource_type: str, resource_key: str) -> list[SensorEntity]:
        descriptions = DESCRIPTIONS_BY_TYPE[resource_type]
        if resource_type == TYPE_NODE and not coordinator.node_details:
            descriptions = tuple(
                d for d in descriptions if d.key not in DETAIL_ONLY_KEYS
            )
        return [
            ProxmoxSensor(coordinator, resource_type, resource_key, description)
            for description in descriptions
        ]

    async_setup_dynamic_entities(entry, coordinator, async_add_entities, _build)


class ProxmoxSensor(ProxmoxEntity, SensorEntity):
    """Sensor auf Basis einer Beschreibung."""

    entity_description: ProxmoxSensorDescription

    def __init__(
        self,
        coordinator: ProxmoxCoordinator,
        resource_type: str,
        resource_key: str,
        description: ProxmoxSensorDescription,
    ) -> None:
        super().__init__(coordinator, resource_type, resource_key, description.key)
        self.entity_description = description
        self._last_boot: datetime | None = None

    @property
    def native_value(self) -> Any:
        """Aktueller Messwert."""
        res = self.resource
        if res is None:
            return None

        try:
            value = self.entity_description.value_fn(res)
        except (KeyError, TypeError, ValueError, IndexError) as err:
            _LOGGER.debug(
                "Sensor %s konnte nicht berechnet werden: %s", self.unique_id, err
            )
            return None

        if self.entity_description.key == "last_boot":
            return self._boot_time(value)

        return value

    def _boot_time(self, uptime: Any) -> datetime | None:
        """Uptime in einen stabilen Boot-Zeitstempel umrechnen."""
        if uptime is None or uptime <= 0:
            self._last_boot = None
            return None

        boot = datetime.now(timezone.utc) - timedelta(seconds=float(uptime))

        if self._last_boot is not None:
            drift = abs((boot - self._last_boot).total_seconds())
            if drift < UPTIME_TOLERANCE:
                return self._last_boot

        self._last_boot = boot.replace(microsecond=0)
        return self._last_boot

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Zusatzinfos am Statussensor."""
        if self.entity_description.key != "status_text":
            return None
        res = self.resource or {}
        return {
            "vmid": res.get("vmid"),
            "node": res.get("node"),
            "tags": res.get("tags"),
            "template": bool(res.get("template")),
            "ha_state": res.get("hastate"),
        }


class ProxmoxFailedTaskSensor(ProxmoxEntity, SensorEntity):
    """Zaehlt fehlgeschlagene Cluster-Tasks der letzten 24 Stunden."""

    _attr_translation_key = "failed_tasks"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ProxmoxCoordinator) -> None:
        super().__init__(coordinator, TYPE_NODE, "_cluster", "failed_tasks")

    @property
    def available(self) -> bool:
        """Immer verfuegbar, solange der Coordinator Daten hat."""
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> int | None:
        """Anzahl fehlgeschlagener Tasks."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("failed_tasks", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Die letzten fehlgeschlagenen Tasks als Liste."""
        data = self.coordinator.data or {}
        failed = [
            {
                "node": task.get("node"),
                "type": task.get("type"),
                "user": task.get("user"),
                "status": task.get("status"),
                "starttime": task.get("starttime"),
            }
            for task in data.get("tasks", [])
            if task.get("status") and task.get("status") != "OK"
        ]
        return {"failed": failed[:10]}

    @property
    def device_info(self):
        """Eigenes Geraet fuer clusterweite Werte."""
        entry = self.coordinator.entry
        version = (self.coordinator.data or {}).get("version", {})
        return {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_cluster")},
            "name": f"Proxmox {entry.data['host']}",
            "manufacturer": "Proxmox",
            "model": "Cluster",
            "sw_version": version.get("version"),
            "configuration_url": (
                f"https://{entry.data['host']}:{entry.data.get('port', 8006)}/"
            ),
        }

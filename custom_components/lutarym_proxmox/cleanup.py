"""Vorhaltezeit fuer verschwundene Proxmox-Ressourcen.

Verschwindet eine VM, ein Container, ein Node oder ein Storage aus Proxmox,
wird das zugehoerige Geraet nicht sofort geloescht, sondern zunaechst nur
vorgemerkt. Erst wenn die Ressource die eingestellte Vorhaltezeit lang nicht
zurueckkehrt, wird das Geraet samt Entitaeten entfernt. Damit ueberstehen
Migrationen, Wiederherstellungen aus dem Backup und laengere Wartungen die
Abwesenheit, ohne dass die Verlaufsdaten verloren gehen.

Der Merkzettel wird im Speicher von Home Assistant abgelegt und ueberlebt
deshalb auch einen Neustart.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import (
    CONF_GRACE_PERIOD,
    DEFAULT_GRACE_PERIOD,
    DOMAIN,
    SIGNAL_RESOURCE_REMOVED,
    STORAGE_SAVE_DELAY,
    STORAGE_VERSION,
)
from .coordinator import ProxmoxCoordinator

_LOGGER = logging.getLogger(__name__)

SECONDS_PER_DAY = 86400


class StaleResourceTracker:
    """Merkt sich fehlende Ressourcen und loescht sie erst nach Ablauf."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        coordinator: ProxmoxCoordinator,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._missing: dict[str, dict[str, Any]] = {}
        self._known: dict[str, tuple[str, str]] = {}

    @property
    def grace_seconds(self) -> float:
        """Vorhaltezeit in Sekunden aus den Optionen."""
        settings = {**self.entry.data, **self.entry.options}
        days = settings.get(CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD)
        try:
            return max(0.0, float(days)) * SECONDS_PER_DAY
        except (TypeError, ValueError):
            return DEFAULT_GRACE_PERIOD * SECONDS_PER_DAY

    async def async_load(self) -> None:
        """Merkzettel aus dem Speicher lesen."""
        stored = await self._store.async_load()
        if not stored:
            return

        missing = stored.get("missing")
        if isinstance(missing, dict):
            self._missing = {
                identifier: entry
                for identifier, entry in missing.items()
                if isinstance(entry, dict) and "since" in entry
            }
            _LOGGER.debug(
                "%d vorgemerkte Ressourcen aus dem Speicher geladen",
                len(self._missing),
            )

    @callback
    def _schedule_save(self) -> None:
        """Merkzettel verzoegert schreiben, um haeufige Zugriffe zu buendeln."""
        self._store.async_delay_save(
            lambda: {"missing": self._missing}, STORAGE_SAVE_DELAY
        )

    async def async_remove_storage(self) -> None:
        """Merkzettel loeschen, wenn die Integration entfernt wird."""
        await self._store.async_remove()

    @callback
    def async_forget(self, identifier: str) -> None:
        """Vormerkung verwerfen, etwa nach manuellem Loeschen eines Geraets."""
        if self._missing.pop(identifier, None) is not None:
            self._schedule_save()

    @callback
    def async_check(self) -> None:
        """Nach jedem Abruf pruefen, was fehlt und was faellig ist."""
        if not self.coordinator.last_update_success or not self.coordinator.data:
            return

        entry_id = self.entry.entry_id
        current: dict[str, tuple[str, str]] = {
            f"{entry_id}_{rtype}_{key}": (rtype, key)
            for rtype, key in self.coordinator.current_keys()
        }
        self._known.update(current)

        changed = self._clear_returned(current)
        changed |= self._process_absent(current)

        if changed:
            self._schedule_save()

    def _clear_returned(self, current: dict[str, tuple[str, str]]) -> bool:
        """Vormerkungen zurueckgekehrter Ressourcen aufheben."""
        returned = [
            identifier for identifier in self._missing if identifier in current
        ]
        for identifier in returned:
            del self._missing[identifier]
            _LOGGER.info(
                "Ressource %s ist zurueck, Vormerkung zum Loeschen aufgehoben",
                identifier,
            )
        return bool(returned)

    def _process_absent(self, current: dict[str, tuple[str, str]]) -> bool:
        """Fehlende Geraete vormerken oder nach Ablauf entfernen."""
        registry = dr.async_get(self.hass)
        entry_id = self.entry.entry_id
        cluster_id = f"{entry_id}_cluster"
        grace = self.grace_seconds
        now = time.time()
        changed = False

        for device in dr.async_entries_for_config_entry(registry, entry_id):
            identifiers = [i[1] for i in device.identifiers if i[0] == DOMAIN]
            if not identifiers:
                continue

            identifier = identifiers[0]
            if identifier == cluster_id or identifier in current:
                continue

            record = self._missing.get(identifier)

            if record is None:
                resource = self._known.get(identifier)
                record = {
                    "since": now,
                    "type": resource[0] if resource else None,
                    "key": resource[1] if resource else None,
                    "name": device.name,
                }
                self._missing[identifier] = record
                changed = True

                if grace > 0:
                    _LOGGER.info(
                        "Ressource %s fehlt, Geraet wird nach %.0f Tagen entfernt",
                        device.name or identifier,
                        grace / SECONDS_PER_DAY,
                    )

            since = float(record.get("since", now))
            if now - since < grace:
                continue

            _LOGGER.info(
                "Vorhaltezeit fuer %s abgelaufen, Geraet wird entfernt",
                device.name or identifier,
            )
            registry.async_update_device(device.id, remove_config_entry_id=entry_id)
            del self._missing[identifier]
            self._known.pop(identifier, None)
            changed = True

            resource_type = record.get("type")
            resource_key = record.get("key")
            if resource_type and resource_key:
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_RESOURCE_REMOVED.format(entry_id),
                    (resource_type, resource_key),
                )

        return changed

    @callback
    def async_pending(self) -> list[dict[str, Any]]:
        """Aktuell vorgemerkte Ressourcen mit Restzeit in Tagen."""
        grace = self.grace_seconds
        now = time.time()
        return [
            {
                "identifier": identifier,
                "name": record.get("name"),
                "missing_since": record.get("since"),
                "days_left": round(
                    max(0.0, grace - (now - float(record.get("since", now))))
                    / SECONDS_PER_DAY,
                    2,
                ),
            }
            for identifier, record in self._missing.items()
        ]

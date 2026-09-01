"""Blockierender Proxmox-VE-API-Wrapper.

Alle Methoden hier sind synchron und muessen aus einem Executor heraus
aufgerufen werden. Der Coordinator uebernimmt das.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from proxmoxer import ProxmoxAPI
from proxmoxer.core import AuthenticationError, ResourceException

from .const import (
    DEFAULT_TIMEOUT,
    SECONDS_PER_HOUR,
    TYPE_LXC,
    TYPE_NODE,
    TYPE_QEMU,
    TYPE_STORAGE,
)

_LOGGER = logging.getLogger(__name__)


class ProxmoxAuthError(Exception):
    """Anmeldedaten wurden abgelehnt."""


class ProxmoxConnectionError(Exception):
    """Server nicht erreichbar oder Antwort unbrauchbar."""


class ProxmoxClient:
    """Duenne Huelle um proxmoxer mit definierter Fehlerbehandlung."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        realm: str,
        verify_ssl: bool,
        token_id: str | None = None,
        token_secret: str | None = None,
        password: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._host = host
        self._port = port
        self._user = f"{user}@{realm}" if "@" not in user else user
        self._realm = realm
        self._verify_ssl = verify_ssl
        self._token_id = token_id
        self._token_secret = token_secret
        self._password = password
        self._timeout = timeout
        self._api: ProxmoxAPI | None = None

    @property
    def user(self) -> str:
        """Vollstaendiger Benutzername inklusive Realm."""
        return self._user

    def connect(self) -> ProxmoxAPI:
        """Client-Objekt erzeugen (bei Token ohne Netzwerkzugriff)."""
        if self._api is not None:
            return self._api

        kwargs: dict[str, Any] = {
            "user": self._user,
            "port": self._port,
            "verify_ssl": self._verify_ssl,
            "timeout": self._timeout,
        }
        if self._token_id:
            kwargs["token_name"] = self._token_id
            kwargs["token_value"] = self._token_secret
        else:
            kwargs["password"] = self._password

        try:
            self._api = ProxmoxAPI(self._host, **kwargs)
        except AuthenticationError as err:
            raise ProxmoxAuthError(str(err)) from err
        except ResourceException as err:
            raise ProxmoxConnectionError(str(err)) from err
        except Exception as err:  # noqa: BLE001
            raise ProxmoxConnectionError(str(err)) from err

        return self._api

    def reset(self) -> None:
        """Verbindung verwerfen, damit sie neu aufgebaut wird."""
        self._api = None

    def _call(self, func, *args, **kwargs) -> Any:
        """API-Aufruf mit einheitlicher Fehlerzuordnung."""
        try:
            return func(*args, **kwargs)
        except AuthenticationError as err:
            self.reset()
            raise ProxmoxAuthError(str(err)) from err
        except ResourceException as err:
            status = getattr(err, "status_code", None)
            if status in (401, 403):
                self.reset()
                raise ProxmoxAuthError(str(err)) from err
            raise ProxmoxConnectionError(str(err)) from err
        except Exception as err:  # noqa: BLE001
            self.reset()
            raise ProxmoxConnectionError(str(err)) from err

    def get_version(self) -> dict[str, Any]:
        """Proxmox-Version abfragen. Dient zugleich als Verbindungstest."""
        api = self.connect()
        result = self._call(api.version.get)
        return result if isinstance(result, dict) else {}

    def get_resources(self) -> list[dict[str, Any]]:
        """Alle Cluster-Ressourcen in einem Aufruf holen."""
        api = self.connect()
        result = self._call(api.cluster.resources.get)
        return result if isinstance(result, list) else []

    def get_node_status(self, node: str) -> dict[str, Any]:
        """Detailstatus eines Nodes (Load, Swap, IO-Wait, Kernel)."""
        api = self.connect()
        result = self._call(api.nodes(node).status.get)
        return result if isinstance(result, dict) else {}

    def get_tasks(self) -> list[dict[str, Any]]:
        """Cluster-Tasks abfragen."""
        api = self.connect()
        try:
            result = self._call(api.cluster.tasks.get)
        except ProxmoxConnectionError as err:
            _LOGGER.debug("Tasks nicht abrufbar: %s", err)
            return []
        return result if isinstance(result, list) else []

    def discover(self) -> dict[str, dict[str, str]]:
        """Ressourcen fuer die Auswahl im Config Flow ermitteln."""
        found: dict[str, dict[str, str]] = {
            TYPE_NODE: {},
            TYPE_QEMU: {},
            TYPE_LXC: {},
            TYPE_STORAGE: {},
        }

        for res in self.get_resources():
            res_type = res.get("type")
            if res_type == TYPE_NODE:
                node = res.get("node")
                if node:
                    found[TYPE_NODE][str(node)] = str(node)
            elif res_type in (TYPE_QEMU, TYPE_LXC):
                vmid = res.get("vmid")
                if vmid is None:
                    continue
                name = res.get("name") or f"{res_type.upper()} {vmid}"
                node = res.get("node", "?")
                found[res_type][str(vmid)] = f"{vmid} - {name} ({node})"
            elif res_type == TYPE_STORAGE:
                storage_id = res.get("id")
                if not storage_id:
                    continue
                name = res.get("storage", storage_id)
                node = res.get("node", "?")
                found[TYPE_STORAGE][str(storage_id)] = f"{name} ({node})"

        return found

    def count_failed_tasks(
        self, tasks: list[dict[str, Any]], window_hours: float
    ) -> int:
        """Fehlgeschlagene Tasks im eingestellten Zeitfenster zaehlen."""
        cutoff = time.time() - window_hours * SECONDS_PER_HOUR
        failed = 0
        for task in tasks:
            status = task.get("status")
            if not status or status == "OK":
                continue
            endtime = task.get("endtime") or task.get("starttime") or 0
            if endtime >= cutoff:
                failed += 1
        return failed

    def guest_command(self, node: str, vm_type: str, vmid: int, command: str) -> None:
        """Steuerbefehl an VM oder Container senden."""
        api = self.connect()
        endpoint = api.nodes(node).qemu if vm_type == TYPE_QEMU else api.nodes(node).lxc
        self._call(getattr(endpoint(vmid).status, command).post)

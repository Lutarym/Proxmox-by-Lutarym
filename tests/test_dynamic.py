"""Prueft, dass neue Ressourcen Entitaeten bekommen und verschwundene entfernt werden."""

import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "custom_components", "lutarym_proxmox")
sys.path.insert(0, os.path.join(ROOT, "custom_components"))

fake = types.ModuleType("proxmoxer")
core = types.ModuleType("proxmoxer.core")


class AuthenticationError(Exception):
    pass


class ResourceException(Exception):
    def __init__(self, status_code=500, msg="", content=""):
        self.status_code = status_code
        super().__init__(msg)


core.AuthenticationError = AuthenticationError
core.ResourceException = ResourceException
fake.core = core

RESOURCES = []


class FakeEndpoint:
    def __init__(self, path):
        self.path = path

    def __call__(self, arg):
        return FakeEndpoint(f"{self.path}/{arg}")

    def __getattr__(self, name):
        if name in ("get", "post"):
            return lambda *a, **k: self._resolve()
        return FakeEndpoint(f"{self.path}/{name}")

    def _resolve(self):
        if self.path == "/version":
            return {"version": "8.3.2"}
        if self.path == "/cluster/resources":
            return list(RESOURCES)
        if self.path == "/cluster/tasks":
            return []
        if self.path.startswith("/nodes/"):
            return {
                "loadavg": ["0.1", "0.1", "0.1"], "wait": 0.0,
                "swap": {"used": 0, "total": 1},
                "rootfs": {"used": 1, "total": 2},
                "kversion": "6.8", "pveversion": "8.3.2",
            }
        return None


class FakeProxmoxAPI(FakeEndpoint):
    def __init__(self, host, **kwargs):
        super().__init__("")


fake.ProxmoxAPI = FakeProxmoxAPI
sys.modules["proxmoxer"] = fake
sys.modules["proxmoxer.core"] = core

from lutarym_proxmox import api as px_api  # noqa: E402
from lutarym_proxmox import binary_sensor, button, config_flow, entity, sensor  # noqa: E402
from lutarym_proxmox.const import (  # noqa: E402
    CONF_AUTO_ADD, EXCLUDE_KEYS, INCLUDE_KEYS,
)
from lutarym_proxmox.coordinator import ProxmoxCoordinator  # noqa: E402

REMOVE_LISTENERS = []


def _connect(hass, signal, fn):
    REMOVE_LISTENERS.append(fn)
    return lambda: REMOVE_LISTENERS.remove(fn)


entity.async_dispatcher_connect = _connect

FAILURES = []


def check(label, cond, detail=""):
    if cond:
        print(f"  OK   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def node(name):
    return {"type": "node", "node": name, "id": f"node/{name}", "status": "online",
            "cpu": 0.1, "maxcpu": 8, "mem": 1, "maxmem": 10, "disk": 1,
            "maxdisk": 10, "uptime": 100}


def guest(vmid, gtype="qemu", name=None, status="running"):
    return {"type": gtype, "vmid": vmid, "id": f"{gtype}/{vmid}",
            "name": name or f"guest{vmid}", "node": "pve1", "status": status,
            "cpu": 0.1, "maxcpu": 2, "mem": 1, "maxmem": 10, "disk": 1,
            "maxdisk": 10, "netin": 1, "netout": 1, "diskread": 1,
            "diskwrite": 1, "uptime": 100, "template": 0}


def storage(name):
    return {"type": "storage", "id": f"storage/pve1/{name}", "storage": name,
            "node": "pve1", "status": "available", "disk": 1, "maxdisk": 10}


client = px_api.ProxmoxClient(host="h", port=8006, user="u", realm="pve",
                              verify_ssl=False, token_id="t", token_secret="s")


class FakeEntry:
    entry_id = "e1"
    data = {"host": "h", "port": 8006}

    def __init__(self, options):
        self.options = options
        self.unloads = []

    def async_on_unload(self, fn):
        self.unloads.append(fn)


def make_coordinator(options):
    entry = FakeEntry(options)
    coord = ProxmoxCoordinator.__new__(ProxmoxCoordinator)
    coord.entry = entry
    coord.client = client
    settings = {**entry.data, **options}
    coord.auto_add = bool(settings.get(CONF_AUTO_ADD, True))
    types_ = ("node", "qemu", "lxc", "storage")
    coord._include = {t: set(settings.get(INCLUDE_KEYS[t], []) or []) for t in types_}
    coord._exclude = {t: set(settings.get(EXCLUDE_KEYS[t], []) or []) for t in types_}
    coord.hass = object()
    coord.node_details = True
    coord.include_templates = True
    coord.task_window = 24
    coord.last_update_success = True
    coord._listeners = {}
    coord.data = None
    return coord, entry


def add_listener(coord, fn):
    """Ersatz fuer DataUpdateCoordinator.async_add_listener."""
    coord._listeners[id(fn)] = fn
    return lambda: coord._listeners.pop(id(fn), None)


def poll(coord):
    """Einen Abrufzyklus samt Benachrichtigung der Listener simulieren."""
    coord.data = coord._fetch()
    for fn in list(coord._listeners.values()):
        fn()


print("\n=== 1. Auswahl wird als Ausschluss gespeichert ===")
discovered = {
    "node": {"pve1": "pve1"},
    "qemu": {"100": "100 - ha", "101": "101 - opnsense"},
    "lxc": {"200": "200 - paperless"},
    "storage": {"storage/pve1/local": "local"},
}
user_input = {
    "nodes": ["pve1"],
    "qemu": ["100"],
    "lxc": ["200"],
    "storage": ["storage/pve1/local"],
    "auto_add": True,
    "scan_interval": 30,
}
opts = config_flow._resource_options(user_input, discovered)
check("abgewaehlte VM 101 landet im Ausschluss", opts["exclude_qemu"] == ["101"], opts)
check("ausgewaehlte VM nicht im Ausschluss", "100" not in opts["exclude_qemu"])
check("auto_add gespeichert", opts["auto_add"] is True)
check("Einschlussliste bleibt erhalten", opts["qemu"] == ["100"])

print("\n=== 2. Neue VM erscheint in den Daten (auto_add an) ===")
RESOURCES[:] = [node("pve1"), guest(100), guest(101), guest(200, "lxc"),
                storage("local")]
coord, entry = make_coordinator(opts)
coord.async_add_listener = lambda fn: add_listener(coord, fn)

poll(coord)
check("abgewaehlte VM 101 fehlt", "101" not in coord.data["qemu"], list(coord.data["qemu"]))
check("VM 100 vorhanden", "100" in coord.data["qemu"])

RESOURCES.append(guest(102, name="neue-vm"))
poll(coord)
check("neue VM 102 in den Daten", "102" in coord.data["qemu"], list(coord.data["qemu"]))
check("abgewaehlte VM 101 weiterhin gefiltert", "101" not in coord.data["qemu"])

print("\n=== 3. Entitaeten werden fuer die neue VM angelegt ===")
RESOURCES[:] = [node("pve1"), guest(100), storage("local")]
coord, entry = make_coordinator({"auto_add": True, "scan_interval": 30})
coord.async_add_listener = lambda fn: add_listener(coord, fn)

created = {"sensor": [], "binary_sensor": [], "button": []}


def adder(platform):
    def _add(entities, update_before_add=False):
        created[platform].extend(entities)
    return _add


coord.data = coord._fetch()

sensor_build = {
    "node": sensor.NODE_SENSORS,
    "qemu": sensor.GUEST_SENSORS,
    "lxc": sensor.GUEST_SENSORS,
    "storage": sensor.STORAGE_SENSORS,
}
entity.async_setup_dynamic_entities(
    entry, coord, adder("sensor"),
    lambda t, k: [sensor.ProxmoxSensor(coord, t, k, d) for d in sensor_build[t]],
)
entity.async_setup_dynamic_entities(
    entry, coord, adder("binary_sensor"),
    lambda t, k: (
        [binary_sensor.ProxmoxNodeOnline(coord, k)] if t == "node"
        else [binary_sensor.ProxmoxStorageActive(coord, k)] if t == "storage"
        else [binary_sensor.ProxmoxGuestRunning(coord, t, k)]
    ),
)
entity.async_setup_dynamic_entities(
    entry, coord, adder("button"),
    lambda t, k: [
        button.ProxmoxGuestButton(coord, t, k, d)
        for d in button.BUTTONS_BY_TYPE.get(t, ())
    ],
)

start_counts = {k: len(v) for k, v in created.items()}
check("Sensoren beim Start angelegt", start_counts["sensor"] > 0, start_counts)
check("Buttons nur fuer den Gast", start_counts["button"] == len(button.QEMU_BUTTONS),
      start_counts["button"])

RESOURCES.append(guest(102, name="neue-vm"))
poll(coord)

new_sensors = [e for e in created["sensor"] if e._resource_key == "102"]
new_binary = [e for e in created["binary_sensor"] if e._resource_key == "102"]
new_buttons = [e for e in created["button"] if e._resource_key == "102"]
check("Sensoren fuer VM 102 nachgelegt",
      len(new_sensors) == len(sensor.GUEST_SENSORS), len(new_sensors))
check("Binary Sensor fuer VM 102 nachgelegt", len(new_binary) == 1, len(new_binary))
check("Buttons fuer VM 102 nachgelegt",
      len(new_buttons) == len(button.QEMU_BUTTONS), len(new_buttons))
check("VM 102 liefert einen Wert",
      new_sensors[0].native_value is not None, new_sensors[0].native_value)
check("VM 102 ist verfuegbar", new_sensors[0].available is True)

print("\n=== 4. Kein doppeltes Anlegen bei weiteren Abrufen ===")
before = len(created["sensor"])
poll(coord)
poll(coord)
check("Anzahl unveraendert nach zwei Abrufen",
      len(created["sensor"]) == before, (before, len(created["sensor"])))
uids = [e.unique_id for e in created["sensor"]]
check("keine doppelten unique_id", len(uids) == len(set(uids)))

print("\n=== 5. Neuer Node, Container und Storage werden erkannt ===")
RESOURCES.extend([node("pve2"), guest(201, "lxc", "neuer-ct"), storage("nas")])
poll(coord)
check("neuer Node hat Sensoren",
      any(e._resource_type == "node" and e._resource_key == "pve2"
          for e in created["sensor"]))
check("neuer Container hat Sensoren",
      any(e._resource_type == "lxc" and e._resource_key == "201"
          for e in created["sensor"]))
check("neuer Container hat LXC-Buttons",
      len([e for e in created["button"] if e._resource_key == "201"])
      == len(button.LXC_BUTTONS))
check("neuer Storage hat Sensoren",
      any(e._resource_type == "storage" and e._resource_key == "storage/pve1/nas"
          for e in created["sensor"]))

print("\n=== 6. Geloeschte VM: Geraet wird zum Entfernen vorgemerkt ===")
valid_before = coord.valid_device_ids()
check("VM 102 gilt als gueltig", "e1_qemu_102" in valid_before)

RESOURCES[:] = [r for r in RESOURCES if r.get("vmid") != 102]
poll(coord)
valid_after = coord.valid_device_ids()
check("VM 102 nicht mehr gueltig", "e1_qemu_102" not in valid_after)
check("VM 100 weiterhin gueltig", "e1_qemu_100" in valid_after)
check("Cluster-Geraet bleibt immer gueltig", "e1_cluster" in valid_after)

stale = [e for e in created["sensor"] if e._resource_key == "102"][0]
check("Sensor der geloeschten VM ist nicht verfuegbar", stale.available is False)
check("Sensor der geloeschten VM liefert None", stale.native_value is None)

print("\n=== 7. Rueckkehr innerhalb der Vorhaltezeit legt nichts doppelt an ===")
# Solange das Geraet noch existiert, duerfen keine zweiten Entitaeten mit
# derselben unique_id entstehen. Home Assistant wuerde sie verwerfen.
count_before = len([e for e in created["sensor"] if e._resource_key == "102"])
RESOURCES.append(guest(102, name="neue-vm"))
poll(coord)
count_after = len([e for e in created["sensor"] if e._resource_key == "102"])
check("keine doppelten Entitaeten bei Rueckkehr",
      count_after == count_before, (count_before, count_after))
check("zurueckgekehrte VM wieder verfuegbar",
      [e for e in created["sensor"] if e._resource_key == "102"][0].available)

print("\n=== 7b. Erst nach dem Entfernen des Geraets wird neu angelegt ===")
# Das Signal kommt vom Tracker, sobald die Vorhaltezeit abgelaufen ist.
RESOURCES[:] = [r for r in RESOURCES if r.get("vmid") != 102]
poll(coord)
for fn in list(REMOVE_LISTENERS):
    fn(("qemu", "102"))
count_mid = len([e for e in created["sensor"] if e._resource_key == "102"])
RESOURCES.append(guest(102, name="neue-vm"))
poll(coord)
count_end = len([e for e in created["sensor"] if e._resource_key == "102"])
check("nach dem Entfernen wird wieder angelegt",
      count_end == count_mid + len(sensor.GUEST_SENSORS),
      (count_mid, count_end))

print("\n=== 8. auto_add aus: neue VM bleibt draussen ===")
RESOURCES[:] = [node("pve1"), guest(100)]
strict_opts = {
    "auto_add": False,
    "nodes": ["pve1"], "qemu": ["100"], "lxc": [], "storage": [],
    "exclude_nodes": [], "exclude_qemu": [], "exclude_lxc": [],
    "exclude_storage": [],
    "scan_interval": 30,
}
scoord, sentry = make_coordinator(strict_opts)
scoord.async_add_listener = lambda fn: add_listener(scoord, fn)
poll(scoord)
check("VM 100 vorhanden", "100" in scoord.data["qemu"])
RESOURCES.append(guest(103, name="ungewollt"))
poll(scoord)
check("neue VM 103 bleibt aussen vor", "103" not in scoord.data["qemu"],
      list(scoord.data["qemu"]))

print("\n=== 9. Ausschluss wirkt auch nach dem Einrichten ===")
RESOURCES[:] = [node("pve1"), guest(100), guest(101)]
excl_opts = {"auto_add": True, "exclude_qemu": ["101"], "scan_interval": 30}
ecoord, eentry = make_coordinator(excl_opts)
ecoord.async_add_listener = lambda fn: add_listener(ecoord, fn)
poll(ecoord)
check("ausgeschlossene VM fehlt", "101" not in ecoord.data["qemu"])
check("ausgeschlossene VM nicht in valid_device_ids",
      "e1_qemu_101" not in ecoord.valid_device_ids())

print("\n=== 10. Kein Anlegen waehrend gestoerter Verbindung ===")
RESOURCES[:] = [node("pve1"), guest(100)]
fcoord, fentry = make_coordinator({"auto_add": True, "scan_interval": 30})
fcoord.async_add_listener = lambda fn: add_listener(fcoord, fn)
fcreated = []
fcoord.data = fcoord._fetch()
entity.async_setup_dynamic_entities(
    fentry, fcoord, lambda ents, update_before_add=False: fcreated.extend(ents),
    lambda t, k: [sensor.ProxmoxSensor(fcoord, t, k, sensor.GUEST_SENSORS[0])]
    if t == "qemu" else [],
)
n_before = len(fcreated)
fcoord.last_update_success = False
RESOURCES.append(guest(104))
fcoord.data = fcoord._fetch()
for fn in list(fcoord._listeners.values()):
    fn()
check("bei fehlgeschlagenem Update nichts angelegt",
      len(fcreated) == n_before, (n_before, len(fcreated)))
fcoord.last_update_success = True
for fn in list(fcoord._listeners.values()):
    fn()
check("nach Erholung wird nachgeholt", len(fcreated) > n_before)

print("\n=== 11. Uebersetzungen fuer den neuen Schalter ===")
for lang in ("en", "de"):
    tr = json.load(open(os.path.join(BASE, "translations", f"{lang}.json")))
    sel = tr["config"]["step"]["resources"]
    check(f"{lang}: auto_add beschriftet", "auto_add" in sel["data"])
    check(f"{lang}: auto_add erklaert", "auto_add" in sel["data_description"])
    opt = tr["options"]["step"]["resources"]
    check(f"{lang}: auto_add im Options-Flow", "auto_add" in opt["data"])

strings = json.load(open(os.path.join(BASE, "strings.json")))
en = json.load(open(os.path.join(BASE, "translations", "en.json")))
check("strings.json synchron", strings == en)

print("\n=== 12. Config-Entry-Version ===")
check("Config Flow auf Version 2", config_flow.ProxmoxConfigFlow.VERSION == 2)

print("\n" + "=" * 60)
if FAILURES:
    print(f"FEHLGESCHLAGEN: {len(FAILURES)}")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("ALLE TESTS BESTANDEN")

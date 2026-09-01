"""Prueft die Vorhaltezeit vor dem Loeschen verschwundener Ressourcen."""

import asyncio
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
fake.ProxmoxAPI = object
sys.modules["proxmoxer"] = fake
sys.modules["proxmoxer.core"] = core

from lutarym_proxmox import cleanup, config_flow  # noqa: E402
from lutarym_proxmox.const import (  # noqa: E402
    CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD, DOMAIN,
)

FAILURES = []
DAY = 86400


def check(label, cond, detail=""):
    if cond:
        print(f"  OK   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# --- Testdoubles -----------------------------------------------------------

CLOCK = {"now": 1_000_000.0}
cleanup.time = types.SimpleNamespace(time=lambda: CLOCK["now"])

SENT = []
cleanup.async_dispatcher_send = lambda hass, signal, payload: SENT.append(
    (signal, payload)
)


class FakeDevice:
    def __init__(self, identifier, name):
        self.id = f"dev_{identifier}"
        self.identifiers = {(DOMAIN, identifier)}
        self.name = name


class FakeRegistry:
    def __init__(self):
        self.devices = {}
        self.removed = []

    def add(self, identifier, name):
        self.devices[identifier] = FakeDevice(identifier, name)

    def async_update_device(self, device_id, remove_config_entry_id=None):
        for identifier, dev in list(self.devices.items()):
            if dev.id == device_id:
                del self.devices[identifier]
                self.removed.append(identifier)


REGISTRY = FakeRegistry()
cleanup.dr = types.SimpleNamespace(
    async_get=lambda hass: REGISTRY,
    async_entries_for_config_entry=lambda reg, entry_id: list(reg.devices.values()),
)


class FakeStore:
    """Ersetzt den HA-Speicher und behaelt den Inhalt im Prozess."""

    files = {}

    def __init__(self, hass, version, key):
        self.key = key

    async def async_load(self):
        return FakeStore.files.get(self.key)

    def async_delay_save(self, data_func, delay):
        FakeStore.files[self.key] = json.loads(json.dumps(data_func()))

    async def async_remove(self):
        FakeStore.files.pop(self.key, None)


cleanup.Store = FakeStore


class FakeEntry:
    entry_id = "e1"
    data = {"host": "h", "port": 8006}

    def __init__(self, options=None):
        self.options = options or {}


class FakeCoordinator:
    hass = object()

    def __init__(self, keys):
        self.last_update_success = True
        self.data = {"nodes": {}}
        self._keys = set(keys)

    def set_keys(self, keys):
        self._keys = set(keys)

    def current_keys(self):
        return set(self._keys)


def make_tracker(options=None, keys=(), devices=()):
    entry = FakeEntry(options)
    coord = FakeCoordinator(keys)
    tracker = cleanup.StaleResourceTracker(FakeCoordinator.hass, entry, coord)
    REGISTRY.devices.clear()
    REGISTRY.removed.clear()
    for identifier, name in devices:
        REGISTRY.add(identifier, name)
    return tracker, coord


print("\n=== 1. Standardwert ist 14 Tage ===")
tracker, coord = make_tracker()
check("Vorhaltezeit 14 Tage", tracker.grace_seconds == 14 * DAY,
      tracker.grace_seconds / DAY)
check("Konstante ist 14", DEFAULT_GRACE_PERIOD == 14)

tracker7, _ = make_tracker({CONF_GRACE_PERIOD: 7})
check("7 Tage einstellbar", tracker7.grace_seconds == 7 * DAY)
tracker0, _ = make_tracker({CONF_GRACE_PERIOD: 0})
check("0 Tage bedeutet sofort", tracker0.grace_seconds == 0)
trackerbad, _ = make_tracker({CONF_GRACE_PERIOD: "kaputt"})
check("unbrauchbarer Wert faellt auf 14 zurueck",
      trackerbad.grace_seconds == 14 * DAY)

print("\n=== 2. VM verschwindet, Geraet bleibt zunaechst ===")
FakeStore.files.clear()
CLOCK["now"] = 1_000_000.0
tracker, coord = make_tracker(
    {CONF_GRACE_PERIOD: 14},
    keys=[("qemu", "100"), ("qemu", "102"), ("node", "pve1")],
    devices=[("e1_qemu_100", "ha (100)"), ("e1_qemu_102", "neue-vm (102)"),
             ("e1_node_pve1", "Proxmox Node pve1"), ("e1_cluster", "Proxmox h")],
)
tracker.async_check()
check("nichts entfernt solange alles da ist", REGISTRY.removed == [])
check("keine Vormerkung", tracker.async_pending() == [])

coord.set_keys([("qemu", "100"), ("node", "pve1")])
tracker.async_check()
check("Geraet noch vorhanden", "e1_qemu_102" in REGISTRY.devices)
pending = tracker.async_pending()
check("genau eine Vormerkung", len(pending) == 1, pending)
check("Restzeit 14 Tage", pending[0]["days_left"] == 14.0, pending)
check("Name mitgemerkt", pending[0]["name"] == "neue-vm (102)")

print("\n=== 3. Nach 13 Tagen noch da, nach 14 geloescht ===")
CLOCK["now"] += 13 * DAY
tracker.async_check()
check("nach 13 Tagen nicht geloescht", "e1_qemu_102" in REGISTRY.devices)
check("Restzeit 1 Tag", tracker.async_pending()[0]["days_left"] == 1.0)

CLOCK["now"] += 1 * DAY + 60
tracker.async_check()
check("nach 14 Tagen geloescht", "e1_qemu_102" not in REGISTRY.devices)
check("genau dieses Geraet entfernt", REGISTRY.removed == ["e1_qemu_102"],
      REGISTRY.removed)
check("Vormerkung aufgeraeumt", tracker.async_pending() == [])
check("andere Geraete unberuehrt",
      "e1_qemu_100" in REGISTRY.devices and "e1_node_pve1" in REGISTRY.devices)
check("Cluster-Geraet nie angetastet", "e1_cluster" in REGISTRY.devices)

print("\n=== 4. Signal zum Vergessen des Schluessels ===")
check("Signal gesendet", len(SENT) == 1, SENT)
check("Signal traegt Typ und Schluessel", SENT[0][1] == ("qemu", "102"), SENT)
check("Signal an den richtigen Eintrag",
      SENT[0][0] == "lutarym_proxmox_resource_removed_e1", SENT)

print("\n=== 5. Rueckkehr innerhalb der Frist hebt die Vormerkung auf ===")
SENT.clear()
FakeStore.files.clear()
CLOCK["now"] = 2_000_000.0
tracker, coord = make_tracker(
    {CONF_GRACE_PERIOD: 14},
    keys=[("qemu", "100"), ("lxc", "200")],
    devices=[("e1_qemu_100", "ha"), ("e1_lxc_200", "paperless")],
)
tracker.async_check()

coord.set_keys([("qemu", "100")])
tracker.async_check()
check("Container vorgemerkt", len(tracker.async_pending()) == 1)

CLOCK["now"] += 10 * DAY
coord.set_keys([("qemu", "100"), ("lxc", "200")])
tracker.async_check()
check("Vormerkung aufgehoben", tracker.async_pending() == [])
check("Geraet nie entfernt", "e1_lxc_200" in REGISTRY.devices)
check("kein Signal gesendet", SENT == [])

CLOCK["now"] += 20 * DAY
tracker.async_check()
check("auch spaeter nicht geloescht", "e1_lxc_200" in REGISTRY.devices)

print("\n=== 6. Frist ueberlebt einen Neustart ===")
SENT.clear()
FakeStore.files.clear()
CLOCK["now"] = 3_000_000.0
tracker, coord = make_tracker(
    {CONF_GRACE_PERIOD: 14},
    keys=[("qemu", "100"), ("qemu", "101")],
    devices=[("e1_qemu_100", "ha"), ("e1_qemu_101", "opnsense")],
)
tracker.async_check()
coord.set_keys([("qemu", "100")])
tracker.async_check()
check("Merkzettel geschrieben", "lutarym_proxmox.e1" in FakeStore.files,
      list(FakeStore.files))
saved = FakeStore.files["lutarym_proxmox.e1"]["missing"]["e1_qemu_101"]
check("Zeitpunkt gespeichert", saved["since"] == 3_000_000.0, saved)
check("Typ und Schluessel gespeichert",
      saved["type"] == "qemu" and saved["key"] == "101", saved)

CLOCK["now"] += 10 * DAY
tracker2 = cleanup.StaleResourceTracker(
    FakeCoordinator.hass, FakeEntry({CONF_GRACE_PERIOD: 14}), coord
)
run(tracker2.async_load())
check("Vormerkung nach Neustart gelesen", len(tracker2.async_pending()) == 1)
check("Restzeit korrekt weitergezaehlt",
      tracker2.async_pending()[0]["days_left"] == 4.0,
      tracker2.async_pending())

tracker2.async_check()
check("nach Neustart noch nicht geloescht", "e1_qemu_101" in REGISTRY.devices)
CLOCK["now"] += 5 * DAY
tracker2.async_check()
check("nach Ablauf auch ueber den Neustart hinweg geloescht",
      "e1_qemu_101" not in REGISTRY.devices)
check("Signal trotz Neustart mit Typ und Schluessel",
      SENT and SENT[-1][1] == ("qemu", "101"), SENT)

print("\n=== 7. Vorhaltezeit 0 loescht sofort ===")
SENT.clear()
FakeStore.files.clear()
CLOCK["now"] = 4_000_000.0
tracker, coord = make_tracker(
    {CONF_GRACE_PERIOD: 0},
    keys=[("qemu", "100"), ("qemu", "105")],
    devices=[("e1_qemu_100", "ha"), ("e1_qemu_105", "temp")],
)
tracker.async_check()
coord.set_keys([("qemu", "100")])
tracker.async_check()
check("sofort geloescht", "e1_qemu_105" not in REGISTRY.devices)
check("keine Vormerkung uebrig", tracker.async_pending() == [])

print("\n=== 8. Bei gestoerter Verbindung passiert nichts ===")
SENT.clear()
FakeStore.files.clear()
CLOCK["now"] = 5_000_000.0
tracker, coord = make_tracker(
    {CONF_GRACE_PERIOD: 0},
    keys=[("qemu", "100")],
    devices=[("e1_qemu_100", "ha")],
)
tracker.async_check()
coord.last_update_success = False
coord.set_keys([])
tracker.async_check()
check("kein Loeschen bei fehlgeschlagenem Abruf",
      "e1_qemu_100" in REGISTRY.devices)
check("keine Vormerkung bei fehlgeschlagenem Abruf",
      tracker.async_pending() == [])

coord.data = None
coord.last_update_success = True
tracker.async_check()
check("kein Loeschen ohne Daten", "e1_qemu_100" in REGISTRY.devices)

print("\n=== 9. Manuelles Vergessen ===")
FakeStore.files.clear()
CLOCK["now"] = 6_000_000.0
tracker, coord = make_tracker(
    {CONF_GRACE_PERIOD: 14},
    keys=[("qemu", "100"), ("qemu", "106")],
    devices=[("e1_qemu_100", "ha"), ("e1_qemu_106", "weg")],
)
tracker.async_check()
coord.set_keys([("qemu", "100")])
tracker.async_check()
check("vorgemerkt", len(tracker.async_pending()) == 1)
tracker.async_forget("e1_qemu_106")
check("Vormerkung entfernt", tracker.async_pending() == [])

print("\n=== 10. Config Flow speichert die Vorhaltezeit ===")
opts = config_flow._behaviour_options(
    {"scan_interval": 30, "grace_period": 30, "enable_controls": True,
     "node_details": True, "task_window": 24}
)
check("Vorhaltezeit gespeichert", opts[CONF_GRACE_PERIOD] == 30, opts)
opts0 = config_flow._behaviour_options({"scan_interval": 30, "grace_period": 0})
check("0 wird nicht auf den Standard gehoben", opts0[CONF_GRACE_PERIOD] == 0)
opts_def = config_flow._behaviour_options({"scan_interval": 30})
check("fehlender Wert wird zum Standard",
      opts_def[CONF_GRACE_PERIOD] == DEFAULT_GRACE_PERIOD)

schema = config_flow._behaviour_schema()
fields = {str(k.schema) for k in schema.schema}
check("Feld im Formular", "grace_period" in fields, fields)

print("\n=== 11. Uebersetzungen ===")
for lang in ("en", "de"):
    tr = json.load(open(os.path.join(BASE, "translations", f"{lang}.json")))
    step = tr["config"]["step"]["behaviour"]
    check(f"{lang}: grace_period beschriftet", "grace_period" in step["data"])
    check(f"{lang}: grace_period erklaert",
          "grace_period" in step["data_description"])
    opt = tr["options"]["step"]["behaviour"]
    check(f"{lang}: grace_period im Options-Flow", "grace_period" in opt["data"])

strings = json.load(open(os.path.join(BASE, "strings.json")))
en = json.load(open(os.path.join(BASE, "translations", "en.json")))
check("strings.json synchron", strings == en)

print("\n" + "=" * 60)
if FAILURES:
    print(f"FEHLGESCHLAGEN: {len(FAILURES)}")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("ALLE TESTS BESTANDEN")

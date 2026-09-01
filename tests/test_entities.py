"""Prueft Entitaetsklassen, Manifest und Config-Flow-Schema."""

import json
import sys
import types

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "custom_components"))

# proxmoxer mocken
fake = types.ModuleType("proxmoxer")
fake.ProxmoxAPI = object
core = types.ModuleType("proxmoxer.core")


class AuthenticationError(Exception):
    pass


class ResourceException(Exception):
    pass


core.AuthenticationError = AuthenticationError
core.ResourceException = ResourceException
fake.core = core
sys.modules["proxmoxer"] = fake
sys.modules["proxmoxer.core"] = core

FAILURES = []


def check(label, cond, detail=""):
    if cond:
        print(f"  OK   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


BASE = os.path.join(ROOT, "custom_components", "lutarym_proxmox")

print("\n=== 1. Manifest gegen HA-Schema ===")
manifest = json.load(open(f"{BASE}/manifest.json"))

from homeassistant.loader import Manifest  # noqa: E402

required = ["domain", "name", "documentation", "codeowners", "version", "iot_class"]
for key in required:
    check(f"manifest hat {key}", key in manifest, manifest.keys())

valid_iot = [
    "assumed_state", "cloud_polling", "cloud_push",
    "local_polling", "local_push", "calculated",
]
check("iot_class gueltig", manifest["iot_class"] in valid_iot, manifest["iot_class"])
check("integration_type gueltig",
      manifest.get("integration_type") in ("hub", "device", "service", "helper", None),
      manifest.get("integration_type"))
check("config_flow true", manifest.get("config_flow") is True)
check("requirements gepinnt",
      all("==" in r for r in manifest["requirements"]), manifest["requirements"])
check("version semver-artig", manifest["version"].count(".") == 2, manifest["version"])
check("kein ungueltiges Feld 'manifest_version'", "manifest_version" not in manifest)
check("kein ungueltiges Feld 'homeassistant'", "homeassistant" not in manifest)

print("\n=== 2. hacs.json ===")
hacs = json.load(open(os.path.join(ROOT, "hacs.json")))
allowed = {
    "name", "content_in_root", "filename", "country", "homeassistant",
    "persistent_directory", "hacs", "zip_release", "hide_default_branch",
    "render_readme",
}
extra = set(hacs) - allowed
check("nur gueltige hacs.json-Felder", not extra, extra)
check("name gesetzt", "name" in hacs)

check("Ordner custom_components/<domain> vorhanden",
      os.path.isdir(os.path.join(ROOT, "custom_components", manifest["domain"])))
check("Domain stimmt mit Ordnernamen ueberein",
      manifest["domain"] == "lutarym_proxmox")

print("\n=== 3. Entitaetsklassen instanziieren ===")
from lutarym_proxmox import binary_sensor, button, entity, sensor  # noqa: E402
from lutarym_proxmox.coordinator import ProxmoxCoordinator  # noqa: E402


class FakeEntry:
    entry_id = "abc123"
    data = {"host": "10.0.0.5", "port": 8006}
    options = {}


class FakeCoordinator:
    entry = FakeEntry()
    last_update_success = True
    node_details = True
    include_templates = True
    task_window = 24
    data = {
        "version": {"version": "8.3.2"},
        "nodes": {
            "pve1": {
                "node": "pve1", "status": "online", "cpu": 0.1, "maxcpu": 8,
                "mem": 100, "maxmem": 1000, "disk": 10, "maxdisk": 100,
                "uptime": 3600, "level": "",
                "detail": {"loadavg": ["1.0", "0.9", "0.8"], "wait": 0.01,
                           "swap": {"used": 1, "total": 10},
                           "rootfs": {"used": 5, "total": 10},
                           "kversion": "6.8", "pveversion": "8.3.2"},
            }
        },
        "qemu": {
            "100": {"vmid": 100, "name": "ha", "node": "pve1", "status": "running",
                    "cpu": 0.05, "maxcpu": 2, "mem": 50, "maxmem": 100,
                    "disk": 0, "maxdisk": 100, "netin": 10, "netout": 20,
                    "diskread": 1, "diskwrite": 2, "uptime": 100, "template": 0},
            "900": {"vmid": 900, "name": "tpl", "node": "pve1", "status": "stopped",
                    "template": 1, "maxcpu": 1, "maxmem": 10, "uptime": 0},
        },
        "lxc": {
            "200": {"vmid": 200, "name": "paperless", "node": "pve1",
                    "status": "stopped", "cpu": 0, "maxcpu": 1, "mem": 0,
                    "maxmem": 100, "disk": 5, "maxdisk": 100, "netin": 0,
                    "netout": 0, "uptime": 0, "template": 0},
        },
        "storage": {
            "storage/pve1/local": {"storage": "local", "node": "pve1",
                                   "status": "available", "disk": 10,
                                   "maxdisk": 100, "plugintype": "dir"},
        },
        "tasks": [{"node": "pve1", "type": "x", "status": "failed",
                   "starttime": 1, "user": "root"}],
        "failed_tasks": 1,
    }

    def __init__(self):
        pass


coord = FakeCoordinator()

all_uids = set()
dupes = []
entities = []

for node in coord.data["nodes"]:
    for d in sensor.NODE_SENSORS:
        entities.append(sensor.ProxmoxSensor(coord, "node", node, d))
    entities.append(binary_sensor.ProxmoxNodeOnline(coord, node))

for gtype in ("qemu", "lxc"):
    for vmid in coord.data[gtype]:
        for d in sensor.GUEST_SENSORS:
            entities.append(sensor.ProxmoxSensor(coord, gtype, vmid, d))
        entities.append(binary_sensor.ProxmoxGuestRunning(coord, gtype, vmid))

for sid in coord.data["storage"]:
    for d in sensor.STORAGE_SENSORS:
        entities.append(sensor.ProxmoxSensor(coord, "storage", sid, d))
    entities.append(binary_sensor.ProxmoxStorageActive(coord, sid))

for vmid in coord.data["qemu"]:
    for d in button.QEMU_BUTTONS:
        entities.append(button.ProxmoxGuestButton(coord, "qemu", vmid, d))
for vmid in coord.data["lxc"]:
    for d in button.LXC_BUTTONS:
        entities.append(button.ProxmoxGuestButton(coord, "lxc", vmid, d))

entities.append(sensor.ProxmoxFailedTaskSensor(coord))

check(f"{len(entities)} Entitaeten erzeugt", len(entities) > 80, len(entities))

for e in entities:
    uid = e.unique_id
    if uid in all_uids:
        dupes.append(uid)
    all_uids.add(uid)
check("keine doppelte unique_id ueber alle Plattformen", not dupes, dupes)

errors = []
for e in entities:
    try:
        _ = e.device_info
    except Exception as exc:
        errors.append(f"{e.unique_id}: device_info {exc!r}")
    try:
        _ = e.available
    except Exception as exc:
        errors.append(f"{e.unique_id}: available {exc!r}")
    if hasattr(e, "native_value"):
        try:
            _ = e.native_value
        except Exception as exc:
            errors.append(f"{e.unique_id}: native_value {exc!r}")
    if hasattr(e, "is_on"):
        try:
            _ = e.is_on
        except Exception as exc:
            errors.append(f"{e.unique_id}: is_on {exc!r}")
    try:
        _ = e.extra_state_attributes
    except Exception as exc:
        errors.append(f"{e.unique_id}: attrs {exc!r}")
check("keine Exception in Properties", not errors, errors[:5])

print("\n=== 4. Button-Verfuegbarkeit nach Gastzustand ===")
btns = {
    (e._resource_key, e.entity_description.key): e
    for e in entities
    if isinstance(e, button.ProxmoxGuestButton)
}
check("Start bei laufender VM ausgeblendet",
      btns[("100", "start")].available is False)
check("Stop bei laufender VM verfuegbar",
      btns[("100", "stop")].available is True)
check("Start bei gestopptem Container verfuegbar",
      btns[("200", "start")].available is True)
check("Stop bei gestopptem Container ausgeblendet",
      btns[("200", "stop")].available is False)
check("Template hat keine aktiven Buttons",
      all(not btns[("900", k)].available for k in ("start", "stop", "reboot")))

print("\n=== 5. Verfuegbarkeit bei verschwundener Ressource ===")
gone = sensor.ProxmoxSensor(coord, "qemu", "999", sensor.GUEST_SENSORS[0])
check("unbekannte VM ist nicht verfuegbar", gone.available is False)
check("unbekannte VM liefert None", gone.native_value is None)

print("\n=== 6. device_info Inhalte ===")
node_sensor = next(e for e in entities if e._resource_type == "node"
                   and e._entity_key == "cpu")
di = node_sensor.device_info
check("Node-Geraet benannt", di["name"] == "Proxmox Node pve1", di["name"])
check("identifiers enthaelt entry_id",
      any("abc123" in i[1] for i in di["identifiers"]), di["identifiers"])
check("configuration_url gesetzt",
      di["configuration_url"] == "https://10.0.0.5:8006/", di["configuration_url"])

vm_sensor = next(e for e in entities if e._resource_type == "qemu"
                 and e._resource_key == "100" and e._entity_key == "cpu")
check("VM-Geraet mit Name und ID",
      vm_sensor.device_info["name"] == "ha (100)",
      vm_sensor.device_info["name"])

cluster = entities[-1]
check("Cluster-Geraet mit sw_version",
      cluster.device_info["sw_version"] == "8.3.2")

print("\n=== 7. last_boot ist stabil ===")
lb = next(e for e in entities if e._resource_type == "node"
          and e._entity_key == "last_boot")
v1 = lb.native_value
v2 = lb.native_value
check("Boot-Zeit schwankt nicht zwischen Abrufen", v1 == v2, (v1, v2))
check("Boot-Zeit hat Zeitzone", v1 is not None and v1.tzinfo is not None)

lb_stopped = next(e for e in entities if e._resource_type == "lxc"
                  and e._entity_key == "last_boot")
check("gestoppter Gast hat keine Boot-Zeit", lb_stopped.native_value is None)

print("\n=== 8. Config-Flow-Schemata bauen ===")
from lutarym_proxmox import config_flow as cf  # noqa: E402

try:
    s1 = cf._connection_schema()
    check("Verbindungsschema baubar", s1 is not None)
except Exception as exc:
    check("Verbindungsschema baubar", False, repr(exc))

discovered = {
    "node": {"pve1": "pve1"},
    "qemu": {"100": "100 - ha (pve1)"},
    "lxc": {"200": "200 - paperless (pve1)"},
    "storage": {"storage/pve1/local": "local (pve1)"},
}
try:
    s2 = cf._resource_schema(discovered)
    check("Ressourcenschema baubar", s2 is not None)
except Exception as exc:
    check("Ressourcenschema baubar", False, repr(exc))

try:
    s3 = cf._resource_schema({"node": {}, "qemu": {}, "lxc": {}, "storage": {}})
    check("Ressourcenschema ohne Ressourcen baubar", s3 is not None)
except Exception as exc:
    check("Ressourcenschema ohne Ressourcen baubar", False, repr(exc))

try:
    s4 = cf._behaviour_schema()
    check("Verhaltensschema baubar", s4 is not None)
except Exception as exc:
    check("Verhaltensschema baubar", False, repr(exc))

ui = {"auth_method": "token", "token_id": "", "token_secret": ""}
check("fehlender Token wird erkannt",
      cf._validate_credentials(ui) == "missing_token")
ui2 = {"auth_method": "password", "password": ""}
check("fehlendes Passwort wird erkannt",
      cf._validate_credentials(ui2) == "missing_password")
ui3 = {"auth_method": "token", "token_id": "a", "token_secret": "b"}
check("gueltiger Token akzeptiert", cf._validate_credentials(ui3) is None)
check("Passwortfeld bei Token geleert", ui3["password"] == "")

print("\n=== 9. Strings und Uebersetzungen identisch strukturiert ===")
strings = json.load(open(f"{BASE}/strings.json"))
en = json.load(open(f"{BASE}/translations/en.json"))
de = json.load(open(f"{BASE}/translations/de.json"))


def keypaths(obj, prefix=""):
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(f"{prefix}{k}")
            out |= keypaths(v, f"{prefix}{k}.")
    return out


check("strings.json == en.json Struktur", keypaths(strings) == keypaths(en))
diff = keypaths(en) ^ keypaths(de)
check("de.json vollstaendig wie en.json", not diff, diff)

flow_steps = set(en["config"]["step"])
check("alle Flow-Schritte uebersetzt",
      flow_steps == {"user", "resources", "behaviour", "reauth_confirm"}, flow_steps)
option_steps = set(en["options"]["step"])
check("Options-Flow vollstaendig uebersetzt",
      option_steps == {"init", "resources", "behaviour"}, option_steps)
check("Menue beschriftet",
      set(en["options"]["step"]["init"]["menu_options"]) == {"resources", "behaviour"})

print("\n" + "=" * 60)
if FAILURES:
    print(f"FEHLGESCHLAGEN: {len(FAILURES)}")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("ALLE TESTS BESTANDEN")

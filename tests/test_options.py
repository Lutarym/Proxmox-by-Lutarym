"""Prueft, dass jeder abgefragte Parameter auch wirklich wirkt."""

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

CALLS = []
NOW = 1_000_000.0

RESOURCES = [
    {"type": "node", "node": "pve1", "id": "node/pve1", "status": "online",
     "cpu": 0.1, "maxcpu": 8, "mem": 1, "maxmem": 10, "disk": 1, "maxdisk": 10,
     "uptime": 100},
    {"type": "node", "node": "pve2", "id": "node/pve2", "status": "online",
     "cpu": 0.2, "maxcpu": 4, "mem": 1, "maxmem": 10, "disk": 1, "maxdisk": 10,
     "uptime": 100},
    {"type": "qemu", "vmid": 100, "id": "qemu/100", "name": "ha", "node": "pve1",
     "status": "running", "cpu": 0.1, "maxcpu": 2, "mem": 1, "maxmem": 10,
     "disk": 0, "maxdisk": 10, "netin": 1, "netout": 1, "uptime": 100,
     "template": 0},
    {"type": "qemu", "vmid": 900, "id": "qemu/900", "name": "debian-tpl",
     "node": "pve1", "status": "stopped", "maxcpu": 1, "maxmem": 10,
     "maxdisk": 10, "uptime": 0, "template": 1},
    {"type": "lxc", "vmid": 950, "id": "lxc/950", "name": "ct-tpl", "node": "pve1",
     "status": "stopped", "maxcpu": 1, "maxmem": 10, "maxdisk": 10, "uptime": 0,
     "template": 1},
    {"type": "storage", "id": "storage/pve1/local", "storage": "local",
     "node": "pve1", "status": "available", "disk": 1, "maxdisk": 10},
]

TASKS = [
    {"node": "pve1", "type": "vzdump", "status": "OK",
     "starttime": NOW - 3600, "endtime": NOW - 3500},
    {"node": "pve1", "type": "qmstart", "status": "failed",
     "starttime": NOW - 7200, "endtime": NOW - 7100},
    {"node": "pve1", "type": "vzdump", "status": "error",
     "starttime": NOW - 200000, "endtime": NOW - 199000},
]


class FakeEndpoint:
    def __init__(self, path):
        self.path = path

    def __call__(self, arg):
        return FakeEndpoint(f"{self.path}/{arg}")

    def __getattr__(self, name):
        if name in ("get", "post"):
            def method(*a, **k):
                CALLS.append(f"{name.upper()} {self.path}")
                return self._resolve()
            return method
        return FakeEndpoint(f"{self.path}/{name}")

    def _resolve(self):
        if self.path == "/version":
            return {"version": "8.3.2"}
        if self.path == "/cluster/resources":
            return list(RESOURCES)
        if self.path == "/cluster/tasks":
            return list(TASKS)
        if self.path.startswith("/nodes/"):
            return {"loadavg": ["0.5", "0.4", "0.3"], "wait": 0.01,
                    "swap": {"used": 1, "total": 10},
                    "rootfs": {"used": 1, "total": 10},
                    "kversion": "6.8", "pveversion": "8.3.2"}
        return None


class FakeProxmoxAPI(FakeEndpoint):
    def __init__(self, host, **kwargs):
        super().__init__("")
        self.kwargs = kwargs


fake.ProxmoxAPI = FakeProxmoxAPI
sys.modules["proxmoxer"] = fake
sys.modules["proxmoxer.core"] = core

from lutarym_proxmox import api as px_api  # noqa: E402
from lutarym_proxmox import button, config_flow, const, sensor  # noqa: E402
from lutarym_proxmox.coordinator import ProxmoxCoordinator  # noqa: E402

px_api.time = types.SimpleNamespace(time=lambda: NOW)

FAILURES = []


def check(label, cond, detail=""):
    if cond:
        print(f"  OK   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


class FakeEntry:
    entry_id = "e1"

    def __init__(self, data=None, options=None):
        self.data = {"host": "h", "port": 8006, **(data or {})}
        self.options = options or {}


def make_coordinator(options=None, data=None):
    """Coordinator mit echter Initialisierungslogik, ohne HA-Kern."""
    entry = FakeEntry(data, options)
    coord = ProxmoxCoordinator.__new__(ProxmoxCoordinator)
    settings = {**entry.data, **entry.options}
    coord.entry = entry
    coord.client = px_api.ProxmoxClient(
        host="h", port=8006, user="u", realm="pve", verify_ssl=False,
        token_id="t", token_secret="s",
    )
    coord.tracker = None
    coord.auto_add = bool(settings.get(const.CONF_AUTO_ADD, const.DEFAULT_AUTO_ADD))
    coord.node_details = bool(
        settings.get(const.CONF_NODE_DETAILS, const.DEFAULT_NODE_DETAILS)
    )
    coord.include_templates = bool(
        settings.get(const.CONF_INCLUDE_TEMPLATES, const.DEFAULT_INCLUDE_TEMPLATES)
    )
    coord.task_window = float(
        settings.get(const.CONF_TASK_WINDOW, const.DEFAULT_TASK_WINDOW)
    )
    types_ = ("node", "qemu", "lxc", "storage")
    coord._include = {t: set(settings.get(const.INCLUDE_KEYS[t], []) or []) for t in types_}
    coord._exclude = {t: set(settings.get(const.EXCLUDE_KEYS[t], []) or []) for t in types_}
    coord.last_update_success = True
    coord.data = None
    return coord


print("\n=== 1. Alle Parameter haben Standardwerte und Grenzen ===")
expected = {
    "CONF_TIMEOUT": ("DEFAULT_TIMEOUT", "MIN_TIMEOUT", "MAX_TIMEOUT"),
    "CONF_SCAN_INTERVAL": ("DEFAULT_SCAN_INTERVAL", "MIN_SCAN_INTERVAL",
                           "MAX_SCAN_INTERVAL"),
    "CONF_GRACE_PERIOD": ("DEFAULT_GRACE_PERIOD", "MIN_GRACE_PERIOD",
                          "MAX_GRACE_PERIOD"),
    "CONF_TASK_WINDOW": ("DEFAULT_TASK_WINDOW", "MIN_TASK_WINDOW",
                         "MAX_TASK_WINDOW"),
}
for conf, (default, low, high) in expected.items():
    ok = all(hasattr(const, name) for name in (conf, default, low, high))
    check(f"{conf} vollstaendig definiert", ok)
    if ok:
        check(f"{conf}: Standard liegt im Bereich",
              getattr(const, low) <= getattr(const, default) <= getattr(const, high),
              (getattr(const, low), getattr(const, default), getattr(const, high)))

for conf, default in (
    ("CONF_AUTO_ADD", "DEFAULT_AUTO_ADD"),
    ("CONF_ENABLE_CONTROLS", "DEFAULT_ENABLE_CONTROLS"),
    ("CONF_NODE_DETAILS", "DEFAULT_NODE_DETAILS"),
    ("CONF_INCLUDE_TEMPLATES", "DEFAULT_INCLUDE_TEMPLATES"),
):
    check(f"{conf} definiert",
          hasattr(const, conf) and isinstance(getattr(const, default), bool))

check("keine festen Werte mehr in const",
      not hasattr(const, "API_TIMEOUT") and not hasattr(const, "FAILED_TASK_WINDOW"))

print("\n=== 2. Timeout wirkt bis in den API-Aufruf ===")
c = px_api.ProxmoxClient(host="h", port=8006, user="u", realm="pve",
                         verify_ssl=False, token_id="t", token_secret="s")
check("Standard 20 s", c.connect().kwargs["timeout"] == 20,
      c.connect().kwargs["timeout"])
c90 = px_api.ProxmoxClient(host="h", port=8006, user="u", realm="pve",
                           verify_ssl=False, token_id="t", token_secret="s",
                           timeout=90)
check("eigener Wert wird durchgereicht", c90.connect().kwargs["timeout"] == 90)

client_from_flow = config_flow._client_from_input(
    {"host": "h", "port": 8006, "user": "u", "realm": "pve",
     "verify_ssl": False, "token_id": "t", "token_secret": "s", "timeout": 45}
)
check("Config Flow reicht Timeout durch",
      client_from_flow.connect().kwargs["timeout"] == 45)

print("\n=== 3. Abfrageintervall landet im Coordinator ===")
opts = config_flow._behaviour_options(
    {"scan_interval": 120, "grace_period": 7, "enable_controls": False,
     "node_details": False, "task_window": 48}
)
check("Intervall uebernommen", opts["scan_interval"] == 120, opts)
check("Vorhaltezeit uebernommen", opts["grace_period"] == 7)
check("Buttons abgeschaltet", opts["enable_controls"] is False)
check("Node-Details abgeschaltet", opts["node_details"] is False)
check("Task-Fenster uebernommen", opts["task_window"] == 48)
check("alle Verhaltensfelder gespeichert",
      set(opts) == {"scan_interval", "grace_period", "enable_controls",
                    "node_details", "task_window"}, set(opts))

print("\n=== 4. Templates einbeziehen ===")
coord = make_coordinator({const.CONF_INCLUDE_TEMPLATES: False})
data = coord._fetch()
check("Template-VM ausgeblendet", "900" not in data["qemu"], list(data["qemu"]))
check("Template-Container ausgeblendet", "950" not in data["lxc"], list(data["lxc"]))
check("normale VM bleibt", "100" in data["qemu"])

coord = make_coordinator({const.CONF_INCLUDE_TEMPLATES: True})
data = coord._fetch()
check("Template-VM eingeblendet", "900" in data["qemu"])
check("Template-Container eingeblendet", "950" in data["lxc"])

check("Standard blendet Templates aus", const.DEFAULT_INCLUDE_TEMPLATES is False)

print("\n=== 5. Node-Details sparen API-Aufrufe ===")
CALLS.clear()
coord = make_coordinator({const.CONF_NODE_DETAILS: True})
data_on = coord._fetch()
calls_on = len(CALLS)

CALLS.clear()
coord_off = make_coordinator({const.CONF_NODE_DETAILS: False})
data_off = coord_off._fetch()
calls_off = len(CALLS)

check("mit Details mehr Aufrufe", calls_on == calls_off + 2,
      f"an: {calls_on}, aus: {calls_off}")
check("Detail vorhanden wenn aktiv", "detail" in data_on["nodes"]["pve1"])
check("Detail fehlt wenn aus", "detail" not in data_off["nodes"]["pve1"])
check("Grundwerte bleiben auch ohne Details",
      data_off["nodes"]["pve1"]["cpu"] == 0.1)

detail_sensors = [d for d in sensor.NODE_SENSORS if d.key in sensor.DETAIL_ONLY_KEYS]
check("Detailsensoren identifiziert", len(detail_sensors) == 8, len(detail_sensors))
check("Last gehoert dazu", "load_1" in sensor.DETAIL_ONLY_KEYS)
check("CPU gehoert nicht dazu", "cpu" not in sensor.DETAIL_ONLY_KEYS)

print("\n=== 6. Zeitfenster fehlgeschlagener Tasks ===")
coord24 = make_coordinator({const.CONF_TASK_WINDOW: 24})
check("24 h findet 1 Fehler", coord24._fetch()["failed_tasks"] == 1)
coord72 = make_coordinator({const.CONF_TASK_WINDOW: 72})
check("72 h findet 2 Fehler", coord72._fetch()["failed_tasks"] == 2)
coord1 = make_coordinator({const.CONF_TASK_WINDOW: 1})
check("1 h findet 0 Fehler", coord1._fetch()["failed_tasks"] == 0)

print("\n=== 7. Steuer-Buttons abschaltbar ===")
check("Standard ist an", const.DEFAULT_ENABLE_CONTROLS is True)
src = open(os.path.join(BASE, "button.py")).read()
check("button.py prueft den Schalter", "CONF_ENABLE_CONTROLS" in src)
check("button.py bricht frueh ab", "return\n\n    coordinator" in src)

print("\n=== 8. Formulare enthalten alle Parameter ===")
conn_fields = {str(k.schema) for k in config_flow._connection_schema().schema}
expected_conn = {"host", "port", "user", "realm", "auth_method", "token_id",
                 "token_secret", "password", "verify_ssl", "timeout"}
check("Schritt 1 vollstaendig", conn_fields == expected_conn,
      expected_conn ^ conn_fields)

discovered = {"node": {"pve1": "pve1"}, "qemu": {"100": "100"},
              "lxc": {"200": "200"}, "storage": {"s1": "s1"}}
res_fields = {str(k.schema) for k in config_flow._resource_schema(discovered).schema}
expected_res = {"nodes", "qemu", "lxc", "storage", "auto_add", "include_templates"}
check("Schritt 2 vollstaendig", res_fields == expected_res,
      expected_res ^ res_fields)

beh_fields = {str(k.schema) for k in config_flow._behaviour_schema().schema}
expected_beh = {"scan_interval", "grace_period", "enable_controls",
                "node_details", "task_window"}
check("Schritt 3 vollstaendig", beh_fields == expected_beh,
      expected_beh ^ beh_fields)

overlap = conn_fields & (res_fields | beh_fields)
check("kein Feld doppelt abgefragt", not overlap, overlap)

print("\n=== 9. Vorbelegung uebernimmt bestehende Werte ===")
defaults = {"scan_interval": 90, "grace_period": 3, "enable_controls": False,
            "node_details": False, "task_window": 12}
schema = config_flow._behaviour_schema(defaults)
shown = {str(k.schema): k.default() for k in schema.schema}
for key, value in defaults.items():
    check(f"{key} vorbelegt mit {value}", shown[key] == value, shown[key])

conn_defaults = {"host": "1.2.3.4", "port": 9006, "user": "hass",
                 "realm": "pve", "timeout": 60, "verify_ssl": False}
cshown = {str(k.schema): k.default() for k in
          config_flow._connection_schema(conn_defaults).schema}
check("Host vorbelegt", cshown["host"] == "1.2.3.4")
check("Port vorbelegt", cshown["port"] == 9006)
check("Timeout vorbelegt", cshown["timeout"] == 60)
check("Secret nie vorbelegt", cshown["token_secret"] == "")
check("Passwort nie vorbelegt", cshown["password"] == "")

print("\n=== 10. Uebersetzungen fuer jedes Feld ===")
for lang in ("en", "de"):
    tr = json.load(open(os.path.join(BASE, "translations", f"{lang}.json")))
    steps = tr["config"]["step"]

    check(f"{lang}: Schritte vorhanden",
          set(steps) == {"user", "resources", "behaviour", "reauth_confirm"},
          set(steps))

    for step_id, fields in (("user", conn_fields),
                            ("resources", res_fields),
                            ("behaviour", beh_fields)):
        missing = fields - set(steps[step_id]["data"])
        check(f"{lang}: {step_id} alle Felder beschriftet", not missing, missing)

    described = set(steps["behaviour"].get("data_description", {}))
    check(f"{lang}: jedes Verhaltensfeld erklaert",
          beh_fields <= described, beh_fields - described)

    opts_tr = tr["options"]["step"]
    check(f"{lang}: Options-Menue vorhanden",
          set(opts_tr["init"]["menu_options"]) == {"resources", "behaviour"})
    for step_id, fields in (("resources", res_fields), ("behaviour", beh_fields)):
        missing = fields - set(opts_tr[step_id]["data"])
        check(f"{lang}: Options-{step_id} vollstaendig", not missing, missing)

strings = json.load(open(os.path.join(BASE, "strings.json")))
en = json.load(open(os.path.join(BASE, "translations", "en.json")))
de = json.load(open(os.path.join(BASE, "translations", "de.json")))


def paths(obj, prefix=""):
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(prefix + k)
            out |= paths(v, prefix + k + ".")
    return out


check("strings.json synchron", strings == en)
diff = paths(en) ^ paths(de)
check("de deckungsgleich mit en", not diff, diff)

print("\n=== 11. Migration setzt alle neuen Felder ===")
init_src = open(os.path.join(BASE, "__init__.py")).read()
for key in ("CONF_ENABLE_CONTROLS", "CONF_NODE_DETAILS", "CONF_TASK_WINDOW",
            "CONF_INCLUDE_TEMPLATES", "CONF_GRACE_PERIOD"):
    check(f"Migration setzt {key}", f"{key}:" in init_src)
check("Migration erhaelt Templates der Version 1",
      "CONF_INCLUDE_TEMPLATES: True" in init_src)

print("\n" + "=" * 60)
if FAILURES:
    print(f"FEHLGESCHLAGEN: {len(FAILURES)}")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("ALLE TESTS BESTANDEN")

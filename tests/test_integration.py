"""Prueft die Integration gegen einen simulierten Proxmox-Server."""

import sys
import time
import types

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "custom_components", "lutarym_proxmox")
sys.path.insert(0, os.path.join(ROOT, "custom_components"))

# --- Simulierter Proxmox-Server -------------------------------------------

NOW = time.time()

RESOURCES = [
    {
        "type": "node", "node": "pve1", "id": "node/pve1", "status": "online",
        "cpu": 0.0847, "maxcpu": 8, "mem": 12884901888, "maxmem": 33554432000,
        "disk": 45155565568, "maxdisk": 67799756800, "uptime": 864000, "level": "",
    },
    {
        "type": "node", "node": "pve2", "id": "node/pve2", "status": "offline",
        "cpu": 0, "maxcpu": 4, "mem": 0, "maxmem": 16777216000,
        "disk": 0, "maxdisk": 0, "uptime": 0, "level": "",
    },
    {
        "type": "qemu", "vmid": 100, "id": "qemu/100", "name": "homeassistant",
        "node": "pve1", "status": "running", "cpu": 0.0202, "maxcpu": 4,
        "mem": 5179975680, "maxmem": 8589934592, "disk": 0, "maxdisk": 34359738368,
        "netin": 82601058, "netout": 1060469, "diskread": 1455539712,
        "diskwrite": 1072448512, "uptime": 8825, "template": 0, "tags": "prod",
    },
    {
        "type": "qemu", "vmid": 101, "id": "qemu/101", "name": "opnsense",
        "node": "pve1", "status": "stopped", "cpu": 0, "maxcpu": 2,
        "mem": 0, "maxmem": 4294967296, "disk": 0, "maxdisk": 21474836480,
        "netin": 0, "netout": 0, "diskread": 0, "diskwrite": 0,
        "uptime": 0, "template": 0,
    },
    {
        "type": "qemu", "vmid": 900, "id": "qemu/900", "name": "debian-template",
        "node": "pve1", "status": "stopped", "template": 1, "maxcpu": 1,
        "maxmem": 2147483648, "maxdisk": 10737418240, "uptime": 0,
    },
    {
        "type": "lxc", "vmid": 200, "id": "lxc/200", "name": "paperless",
        "node": "pve1", "status": "running", "cpu": 0.015, "maxcpu": 2,
        "mem": 1073741824, "maxmem": 4294967296, "disk": 5368709120,
        "maxdisk": 21474836480, "netin": 500000, "netout": 250000,
        "diskread": 100, "diskwrite": 200, "uptime": 43200, "template": 0,
    },
    {
        "type": "storage", "id": "storage/pve1/local", "storage": "local",
        "node": "pve1", "status": "available", "disk": 10737418240,
        "maxdisk": 107374182400, "plugintype": "dir", "content": "iso,vztmpl",
        "shared": 0,
    },
    {
        "type": "storage", "id": "storage/pve1/nas", "storage": "nas",
        "node": "pve1", "status": "unavailable", "disk": 0, "maxdisk": 0,
        "plugintype": "nfs", "shared": 1,
    },
    {"type": "sdn", "id": "sdn/zone1", "status": "ok"},
]

NODE_STATUS = {
    "pve1": {
        "uptime": 864000,
        "loadavg": ["0.52", "0.61", "0.58"],
        "wait": 0.0031,
        "cpuinfo": {"cpus": 8, "model": "Intel Xeon"},
        "memory": {"used": 12884901888, "total": 33554432000, "free": 20669530112},
        "swap": {"used": 268435456, "total": 8589934592, "free": 8321499136},
        "rootfs": {"used": 45155565568, "total": 67799756800},
        "kversion": "Linux 6.8.12-4-pve",
        "pveversion": "pve-manager/8.3.2",
    },
}

TASKS = [
    {"node": "pve1", "type": "vzdump", "user": "root@pam", "status": "OK",
     "starttime": NOW - 3600, "endtime": NOW - 3500},
    {"node": "pve1", "type": "qmstart", "user": "root@pam",
     "status": "command failed", "starttime": NOW - 7200, "endtime": NOW - 7100},
    {"node": "pve1", "type": "vzdump", "user": "root@pam", "status": "error",
     "starttime": NOW - 200000, "endtime": NOW - 199000},
    {"node": "pve1", "type": "qmstop", "user": "root@pam", "status": None,
     "starttime": NOW - 60},
]

CALLS = []


FAIL_MODE = None


class FakeEndpoint:
    def __init__(self, path):
        self.path = path

    def __call__(self, arg):
        return FakeEndpoint(f"{self.path}/{arg}")

    def __getattr__(self, name):
        if name in ("get", "post", "put", "delete"):
            def method(*a, **kw):
                CALLS.append(f"{name.upper()} {self.path}")
                return self._resolve()
            return method
        return FakeEndpoint(f"{self.path}/{name}")

    def _resolve(self):
        if FAIL_MODE is not None:
            raise ResourceException(FAIL_MODE, "injected", "test failure")
        p = self.path
        if p == "/version":
            return {"version": "8.3.2", "release": "8.3", "repoid": "abc123"}
        if p == "/cluster/resources":
            return RESOURCES
        if p == "/cluster/tasks":
            return TASKS
        if p.startswith("/nodes/") and p.endswith("/status"):
            node = p.split("/")[2]
            if node in NODE_STATUS:
                return NODE_STATUS[node]
            raise ResourceException(500, "offline", "node offline")
        return None


class AuthenticationError(Exception):
    pass


class ResourceException(Exception):
    def __init__(self, status_code, status_message, content):
        self.status_code = status_code
        super().__init__(f"{status_code} {status_message}: {content}")


class FakeProxmoxAPI(FakeEndpoint):
    def __init__(self, host, **kwargs):
        super().__init__("")
        self.host = host
        self.kwargs = kwargs


fake_proxmoxer = types.ModuleType("proxmoxer")
fake_proxmoxer.ProxmoxAPI = FakeProxmoxAPI
fake_core = types.ModuleType("proxmoxer.core")
fake_core.AuthenticationError = AuthenticationError
fake_core.ResourceException = ResourceException
fake_proxmoxer.core = fake_core
sys.modules["proxmoxer"] = fake_proxmoxer
sys.modules["proxmoxer.core"] = fake_core

# --- Tests -----------------------------------------------------------------

FAILURES = []


def check(label, condition, detail=""):
    if condition:
        print(f"  OK   {label}")
    else:
        print(f"  FAIL {label} {detail}")
        FAILURES.append(label)


print("\n=== 1. Importe aller Module ===")
from lutarym_proxmox import api as px_api  # noqa: E402
from lutarym_proxmox import const  # noqa: E402

import lutarym_proxmox  # noqa: E402
import lutarym_proxmox.coordinator  # noqa: E402
import lutarym_proxmox.entity  # noqa: E402
import lutarym_proxmox.sensor  # noqa: E402
import lutarym_proxmox.binary_sensor  # noqa: E402
import lutarym_proxmox.button  # noqa: E402
import lutarym_proxmox.config_flow  # noqa: E402
import lutarym_proxmox.diagnostics  # noqa: E402

check("alle Module importierbar", True)

print("\n=== 2. Client-Aufbau und Auth-Parameter ===")
client = px_api.ProxmoxClient(
    host="192.168.1.10", port=8006, user="hass", realm="pve",
    verify_ssl=False, token_id="ha", token_secret="secret",
)
api = client.connect()
check("Benutzer inkl. Realm", client.user == "hass@pve", client.user)
check("token_name gesetzt", api.kwargs.get("token_name") == "ha", api.kwargs)
check("token_value gesetzt", api.kwargs.get("token_value") == "secret")
check("port als kwarg", api.kwargs.get("port") == 8006)
check("Standard-Timeout gesetzt",
      api.kwargs.get("timeout") == const.DEFAULT_TIMEOUT, api.kwargs.get("timeout"))
custom = px_api.ProxmoxClient(host="h", port=8006, user="u", realm="pam",
                              verify_ssl=True, token_id="t", token_secret="s",
                              timeout=90)
check("eigenes Timeout wird durchgereicht",
      custom.connect().kwargs.get("timeout") == 90)
check("kein password bei Token", "password" not in api.kwargs)

client_pw = px_api.ProxmoxClient(
    host="h", port=8006, user="root@pam", realm="pam",
    verify_ssl=True, password="pw",
)
api_pw = client_pw.connect()
check("Realm nicht doppelt angehaengt", client_pw.user == "root@pam", client_pw.user)
check("password bei Passwort-Auth", api_pw.kwargs.get("password") == "pw")

print("\n=== 3. Rohdaten-Abruf ===")
CALLS.clear()
version = client.get_version()
check("Version gelesen", version.get("version") == "8.3.2", version)
resources = client.get_resources()
check("Ressourcen gelesen", len(resources) == 9, len(resources))
check("nur 2 API-Calls", len(CALLS) == 2, CALLS)

print("\n=== 4. Discover fuer den Config Flow ===")
disc = client.discover()
check("2 Nodes gefunden", len(disc["node"]) == 2, disc["node"])
check("3 VMs gefunden", len(disc["qemu"]) == 3, disc["qemu"])
check("1 Container gefunden", len(disc["lxc"]) == 1, disc["lxc"])
check("2 Storages gefunden", len(disc["storage"]) == 2, disc["storage"])
check("sdn ignoriert", "sdn" not in disc)
check("Label lesbar", disc["qemu"]["100"] == "100 - homeassistant (pve1)", disc["qemu"]["100"])

print("\n=== 5. Fehlgeschlagene Tasks im 24h-Fenster ===")
failed = client.count_failed_tasks(TASKS, 24)
check("genau 1 Fehler in 24h", failed == 1, f"gezaehlt: {failed}")
check("groesseres Fenster findet mehr",
      client.count_failed_tasks(TASKS, 72) == 2,
      client.count_failed_tasks(TASKS, 72))
check("kleines Fenster findet weniger",
      client.count_failed_tasks(TASKS, 1) == 0,
      client.count_failed_tasks(TASKS, 1))

print("\n=== 6. Coordinator-Datenaufbereitung (ohne Filter) ===")


class FakeEntry:
    entry_id = "testentry"
    data = {"host": "192.168.1.10", "port": 8006}
    options = {}


TYPES = ("node", "qemu", "lxc", "storage")


def make_coordinator(auto_add=True, include=None, exclude=None):
    """Coordinator ohne Home-Assistant-Kern aufbauen."""
    coord = lutarym_proxmox.coordinator.ProxmoxCoordinator.__new__(
        lutarym_proxmox.coordinator.ProxmoxCoordinator
    )
    coord.entry = FakeEntry()
    coord.client = client
    coord.auto_add = auto_add
    coord.node_details = True
    coord.include_templates = True
    coord.task_window = 24
    coord.last_update_success = True
    coord.data = None
    coord._include = {t: set((include or {}).get(t, [])) for t in TYPES}
    coord._exclude = {t: set((exclude or {}).get(t, [])) for t in TYPES}
    return coord


coord = make_coordinator()

CALLS.clear()
data = coord._fetch()
check("2 Nodes", len(data["nodes"]) == 2, list(data["nodes"]))
check("3 VMs", len(data["qemu"]) == 3, list(data["qemu"]))
check("1 Container", len(data["lxc"]) == 1)
check("2 Storages", len(data["storage"]) == 2)
check("failed_tasks korrekt", data["failed_tasks"] == 1)
check("Node-Detail vorhanden", "detail" in data["nodes"]["pve1"])
check("loadavg im Detail", data["nodes"]["pve1"]["detail"]["loadavg"][0] == "0.52")
check(
    "offline-Node ohne Detail bricht nicht ab",
    "detail" not in data["nodes"]["pve2"],
)
check(
    "Call-Anzahl 1+1+2+1",
    len(CALLS) == 5,
    f"{len(CALLS)}: {CALLS}",
)

print("\n=== 7. Auswahlfilter wird wirklich angewendet ===")
strict = make_coordinator(
    auto_add=False,
    include={"node": ["pve1"], "qemu": ["100"],
             "storage": ["storage/pve1/local"]},
)
data_f = strict._fetch()
check("nur 1 Node", list(data_f["nodes"]) == ["pve1"], list(data_f["nodes"]))
check("nur VM 100", list(data_f["qemu"]) == ["100"], list(data_f["qemu"]))
check("leere Einschlussliste heisst alles", len(data_f["lxc"]) == 1)
check("nur 1 Storage", list(data_f["storage"]) == ["storage/pve1/local"])

excl = make_coordinator(auto_add=True, exclude={"qemu": ["101", "900"]})
data_e = excl._fetch()
excl.data = data_e  # setzt im Betrieb der DataUpdateCoordinator
check("Ausschluss greift", sorted(data_e["qemu"]) == ["100"], list(data_e["qemu"]))
check("nicht ausgeschlossene Typen bleiben vollstaendig",
      len(data_e["nodes"]) == 2 and len(data_e["lxc"]) == 1)

check("current_keys deckt alle Typen ab",
      excl.current_keys() >= {("node", "pve1"), ("qemu", "100"),
                              ("lxc", "200"), ("storage", "storage/pve1/local")},
      excl.current_keys())
check("valid_device_ids enthaelt Cluster",
      "testentry_cluster" in excl.valid_device_ids())
check("ausgeschlossene VM nicht in valid_device_ids",
      "testentry_qemu_101" not in excl.valid_device_ids())

print("\n=== 8. Sensorwerte ===")
sensor_mod = lutarym_proxmox.sensor
node = data["nodes"]["pve1"]
vm = data["qemu"]["100"]
stopped = data["qemu"]["101"]
storage_ok = data["storage"]["storage/pve1/local"]
storage_bad = data["storage"]["storage/pve1/nas"]

by_key = {d.key: d for d in sensor_mod.NODE_SENSORS}
check("Node CPU 8.47%", round(by_key["cpu"].value_fn(node), 2) == 8.47, by_key["cpu"].value_fn(node))
check("Node RAM 38.4%", round(by_key["memory_percent"].value_fn(node), 1) == 38.4,
      by_key["memory_percent"].value_fn(node))
check("Node Disk 66.6%", round(by_key["disk_percent"].value_fn(node), 1) == 66.6,
      by_key["disk_percent"].value_fn(node))
check("Load 1", by_key["load_1"].value_fn(node) == 0.52)
check("Load 5", by_key["load_5"].value_fn(node) == 0.61)
check("Load 15", by_key["load_15"].value_fn(node) == 0.58)
check("IO wait 0.31%", round(by_key["io_wait"].value_fn(node), 2) == 0.31)
check("Swap 3.1%", round(by_key["swap_percent"].value_fn(node), 1) == 3.1,
      by_key["swap_percent"].value_fn(node))
check("Kernel", by_key["kernel_version"].value_fn(node) == "Linux 6.8.12-4-pve")
check("PVE Version", by_key["pve_version"].value_fn(node) == "pve-manager/8.3.2")

node2 = data["nodes"]["pve2"]
check("offline-Node CPU 0", by_key["cpu"].value_fn(node2) == 0.0)
check("offline-Node Disk None statt Absturz",
      by_key["disk_percent"].value_fn(node2) is None)
check("offline-Node Load None", by_key["load_1"].value_fn(node2) is None)
check("offline-Node Swap None", by_key["swap_percent"].value_fn(node2) is None)
check("offline-Node Kernel None", by_key["kernel_version"].value_fn(node2) is None)

g_key = {d.key: d for d in sensor_mod.GUEST_SENSORS}
check("VM CPU 2.02%", round(g_key["cpu"].value_fn(vm), 2) == 2.02, g_key["cpu"].value_fn(vm))
check("VM RAM 60.3%", round(g_key["memory_percent"].value_fn(vm), 1) == 60.3,
      g_key["memory_percent"].value_fn(vm))
check("VM netin roh", g_key["network_in"].value_fn(vm) == 82601058.0)
check("VM Status", g_key["status_text"].value_fn(vm) == "running")
check("gestoppte VM Status", g_key["status_text"].value_fn(stopped) == "stopped")
check("VM disk=0 ergibt 0% (Proxmox meldet fuer QEMU keine Belegung)", g_key["disk_percent"].value_fn(vm) == 0.0, g_key["disk_percent"].value_fn(vm))

tmpl = data["qemu"]["900"]
check("Template ohne cpu-Feld gibt None", g_key["cpu"].value_fn(tmpl) is None)
check("Template netin fehlt gibt None", g_key["network_in"].value_fn(tmpl) is None)

s_key = {d.key: d for d in sensor_mod.STORAGE_SENSORS}
check("Storage 10%", round(s_key["disk_percent"].value_fn(storage_ok), 1) == 10.0)
check("Storage frei", s_key["disk_free"].value_fn(storage_ok) == 96636764160.0)
check("Storage maxdisk 0 gibt None",
      s_key["disk_percent"].value_fn(storage_bad) is None)

print("\n=== 9. netin/netout als Zaehler, nicht als Rate ===")
from homeassistant.components.sensor import SensorStateClass, SensorDeviceClass  # noqa: E402
check("network_in TOTAL_INCREASING",
      g_key["network_in"].state_class == SensorStateClass.TOTAL_INCREASING,
      g_key["network_in"].state_class)
check("network_in DATA_SIZE",
      g_key["network_in"].device_class == SensorDeviceClass.DATA_SIZE)
check("memory MEASUREMENT",
      g_key["memory_used"].state_class == SensorStateClass.MEASUREMENT)

print("\n=== 10. Eindeutige IDs ===")
ids = set()
dupes = []
for rtype, keys, descs in (
    ("node", data["nodes"], sensor_mod.NODE_SENSORS),
    ("qemu", data["qemu"], sensor_mod.GUEST_SENSORS),
    ("lxc", data["lxc"], sensor_mod.GUEST_SENSORS),
    ("storage", data["storage"], sensor_mod.STORAGE_SENSORS),
):
    for rkey in keys:
        for d in descs:
            uid = f"testentry_{rtype}_{str(rkey).replace('/', '_')}_{d.key}"
            if uid in ids:
                dupes.append(uid)
            ids.add(uid)
check("keine doppelten unique_id", not dupes, dupes)
check("entry_id im Praefix", all(i.startswith("testentry_") for i in ids))
check("keine Slashes in ID", not any("/" in i for i in ids))

print("\n=== 11. Buttons ===")
btn = lutarym_proxmox.button
check("7 QEMU-Buttons", len(btn.QEMU_BUTTONS) == 7)
check("4 LXC-Buttons", len(btn.LXC_BUTTONS) == 4)
start = [b for b in btn.QEMU_BUTTONS if b.key == "start"][0]
stop = [b for b in btn.QEMU_BUTTONS if b.key == "stop"][0]
check("Start braucht kein running", start.requires_running is False)
check("Stop braucht running", stop.requires_running is True)
check("Start ohne RESTART-Klasse", start.device_class is None, start.device_class)

CALLS.clear()
client.guest_command("pve1", "qemu", 100, "reboot")
check("Reboot-Endpunkt korrekt",
      CALLS == ["POST /nodes/pve1/qemu/100/status/reboot"], CALLS)
CALLS.clear()
client.guest_command("pve1", "lxc", 200, "shutdown")
check("LXC-Endpunkt korrekt",
      CALLS == ["POST /nodes/pve1/lxc/200/status/shutdown"], CALLS)

print("\n=== 12. Fehlerbehandlung ===")


FAIL_MODE = 401
bad = px_api.ProxmoxClient(host="h", port=8006, user="u", realm="pam",
                           verify_ssl=True, token_id="t", token_secret="s")
try:
    bad.get_version()
    check("401 wird zu ProxmoxAuthError", False, "keine Exception")
except px_api.ProxmoxAuthError:
    check("401 wird zu ProxmoxAuthError", True)
except Exception as e:
    check("401 wird zu ProxmoxAuthError", False, type(e).__name__)

FAIL_MODE = 403
bad403 = px_api.ProxmoxClient(host="h", port=8006, user="u", realm="pam",
                              verify_ssl=True, token_id="t", token_secret="s")
try:
    bad403.get_version()
    check("403 wird zu ProxmoxAuthError", False, "keine Exception")
except px_api.ProxmoxAuthError:
    check("403 wird zu ProxmoxAuthError", True)
except Exception as e:
    check("403 wird zu ProxmoxAuthError", False, type(e).__name__)

FAIL_MODE = 500
bad2 = px_api.ProxmoxClient(host="h", port=8006, user="u", realm="pam",
                            verify_ssl=True, token_id="t", token_secret="s")
try:
    bad2.get_version()
    check("500 wird zu ConnectionError", False, "keine Exception")
except px_api.ProxmoxConnectionError:
    check("500 wird zu ConnectionError", True)
except Exception as e:
    check("500 wird zu ConnectionError", False, type(e).__name__)

# Tasks duerfen den ganzen Abruf nicht kippen
tasks_client = px_api.ProxmoxClient(host="h", port=8006, user="u", realm="pam",
                                    verify_ssl=True, token_id="t", token_secret="s")
check("Tasks-Fehler gibt leere Liste", tasks_client.get_tasks() == [])

FAIL_MODE = None

print("\n=== 13. Uebersetzungsschluessel vollstaendig ===")
import json  # noqa: E402

for lang in ("en", "de"):
    with open(
        os.path.join(BASE, "translations", f"{lang}.json")
    ) as fh:
        tr = json.load(fh)
    sensor_tr = tr["entity"]["sensor"]
    bs_tr = tr["entity"]["binary_sensor"]
    btn_tr = tr["entity"]["button"]

    needed_sensor = {
        d.translation_key
        for d in (
            sensor_mod.NODE_SENSORS
            + sensor_mod.GUEST_SENSORS
            + sensor_mod.STORAGE_SENSORS
        )
    } | {"failed_tasks"}
    missing = needed_sensor - set(sensor_tr)
    check(f"{lang}: alle Sensor-Keys uebersetzt", not missing, missing)

    needed_btn = {d.translation_key for d in btn.QEMU_BUTTONS + btn.LXC_BUTTONS}
    missing_b = needed_btn - set(btn_tr)
    check(f"{lang}: alle Button-Keys uebersetzt", not missing_b, missing_b)

    missing_bs = {"node_online", "guest_running", "storage_problem"} - set(bs_tr)
    check(f"{lang}: alle Binary-Keys uebersetzt", not missing_bs, missing_bs)

    states = set(sensor_tr["status_text"]["state"])
    opts = set(g_key["status_text"].options)
    check(f"{lang}: Status-Optionen uebersetzt", opts <= states, opts - states)

print("\n" + "=" * 60)
if FAILURES:
    print(f"FEHLGESCHLAGEN: {len(FAILURES)}")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("ALLE TESTS BESTANDEN")

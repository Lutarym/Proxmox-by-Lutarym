"""Konstanten für die Lutarym Proxmox VE Integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "lutarym_proxmox"

CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_USER: Final = "user"
CONF_REALM: Final = "realm"
CONF_AUTH_METHOD: Final = "auth_method"
CONF_TOKEN_ID: Final = "token_id"
CONF_TOKEN_SECRET: Final = "token_secret"
CONF_PASSWORD: Final = "password"
CONF_VERIFY_SSL: Final = "verify_ssl"

CONF_NODES: Final = "nodes"
CONF_QEMU: Final = "qemu"
CONF_LXC: Final = "lxc"
CONF_STORAGE: Final = "storage"
CONF_SCAN_INTERVAL: Final = "scan_interval"

CONF_AUTO_ADD: Final = "auto_add"
CONF_EXCLUDE_NODES: Final = "exclude_nodes"
CONF_EXCLUDE_QEMU: Final = "exclude_qemu"
CONF_EXCLUDE_LXC: Final = "exclude_lxc"
CONF_EXCLUDE_STORAGE: Final = "exclude_storage"

CONF_GRACE_PERIOD: Final = "grace_period"
CONF_TIMEOUT: Final = "timeout"
CONF_ENABLE_CONTROLS: Final = "enable_controls"
CONF_NODE_DETAILS: Final = "node_details"
CONF_INCLUDE_TEMPLATES: Final = "include_templates"
CONF_TASK_WINDOW: Final = "task_window"

DEFAULT_AUTO_ADD: Final = True
DEFAULT_GRACE_PERIOD: Final = 14
MIN_GRACE_PERIOD: Final = 0
MAX_GRACE_PERIOD: Final = 365

DEFAULT_TIMEOUT: Final = 20
MIN_TIMEOUT: Final = 1
MAX_TIMEOUT: Final = 300

DEFAULT_ENABLE_CONTROLS: Final = True
DEFAULT_NODE_DETAILS: Final = True
DEFAULT_INCLUDE_TEMPLATES: Final = False

DEFAULT_TASK_WINDOW: Final = 24
MIN_TASK_WINDOW: Final = 1
MAX_TASK_WINDOW: Final = 720

MAX_TASKS: Final = 20
SECONDS_PER_HOUR: Final = 3600

STORAGE_VERSION: Final = 1
STORAGE_SAVE_DELAY: Final = 10

SIGNAL_RESOURCE_REMOVED: Final = "lutarym_proxmox_resource_removed_{}"

INCLUDE_KEYS: Final = {
    "node": CONF_NODES,
    "qemu": CONF_QEMU,
    "lxc": CONF_LXC,
    "storage": CONF_STORAGE,
}

EXCLUDE_KEYS: Final = {
    "node": CONF_EXCLUDE_NODES,
    "qemu": CONF_EXCLUDE_QEMU,
    "lxc": CONF_EXCLUDE_LXC,
    "storage": CONF_EXCLUDE_STORAGE,
}

AUTH_TOKEN: Final = "token"
AUTH_PASSWORD: Final = "password"

DEFAULT_PORT: Final = 8006
DEFAULT_REALM: Final = "pam"
DEFAULT_VERIFY_SSL: Final = True
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 5
MAX_SCAN_INTERVAL: Final = 3600

TYPE_NODE: Final = "node"
TYPE_QEMU: Final = "qemu"
TYPE_LXC: Final = "lxc"
TYPE_STORAGE: Final = "storage"

MANUFACTURER: Final = "Proxmox"


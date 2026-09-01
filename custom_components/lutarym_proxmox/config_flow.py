"""Config Flow fuer Proxmox VE."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import ProxmoxAuthError, ProxmoxClient, ProxmoxConnectionError
from .const import (
    AUTH_PASSWORD,
    AUTH_TOKEN,
    CONF_AUTH_METHOD,
    CONF_AUTO_ADD,
    CONF_ENABLE_CONTROLS,
    CONF_GRACE_PERIOD,
    CONF_HOST,
    CONF_INCLUDE_TEMPLATES,
    CONF_NODE_DETAILS,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_REALM,
    CONF_SCAN_INTERVAL,
    CONF_TASK_WINDOW,
    CONF_TIMEOUT,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    CONF_USER,
    CONF_VERIFY_SSL,
    DEFAULT_AUTO_ADD,
    DEFAULT_ENABLE_CONTROLS,
    DEFAULT_GRACE_PERIOD,
    DEFAULT_INCLUDE_TEMPLATES,
    DEFAULT_NODE_DETAILS,
    DEFAULT_PORT,
    DEFAULT_REALM,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TASK_WINDOW,
    DEFAULT_TIMEOUT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    EXCLUDE_KEYS,
    INCLUDE_KEYS,
    MAX_GRACE_PERIOD,
    MAX_SCAN_INTERVAL,
    MAX_TASK_WINDOW,
    MAX_TIMEOUT,
    MIN_GRACE_PERIOD,
    MIN_SCAN_INTERVAL,
    MIN_TASK_WINDOW,
    MIN_TIMEOUT,
    TYPE_LXC,
    TYPE_NODE,
    TYPE_QEMU,
    TYPE_STORAGE,
)

_LOGGER = logging.getLogger(__name__)

REALMS = ["pam", "pve"]

RESOURCE_ORDER = (TYPE_NODE, TYPE_QEMU, TYPE_LXC, TYPE_STORAGE)


def _number(minimum: float, maximum: float, unit: str) -> NumberSelector:
    """Zahlenfeld mit Einheit und festen Grenzen."""
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            unit_of_measurement=unit,
            mode=NumberSelectorMode.BOX,
        )
    )


def _client_from_input(data: Mapping[str, Any]) -> ProxmoxClient:
    """ProxmoxClient aus Formulardaten bauen."""
    return ProxmoxClient(
        host=data[CONF_HOST],
        port=data.get(CONF_PORT, DEFAULT_PORT),
        user=data[CONF_USER],
        realm=data.get(CONF_REALM, DEFAULT_REALM),
        verify_ssl=data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        token_id=data.get(CONF_TOKEN_ID) or None,
        token_secret=data.get(CONF_TOKEN_SECRET) or None,
        password=data.get(CONF_PASSWORD) or None,
        timeout=int(data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
    )


async def _test_connection(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> tuple[ProxmoxClient, dict[str, Any]]:
    """Verbindung pruefen und Versionsinfo zurueckgeben."""
    client = _client_from_input(data)
    version = await hass.async_add_executor_job(client.get_version)
    return client, version


def _connection_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """Schritt 1: Verbindungsdaten."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): _number(1, 65535, ""),
            vol.Required(CONF_USER, default=defaults.get(CONF_USER, "")): str,
            vol.Required(
                CONF_REALM, default=defaults.get(CONF_REALM, DEFAULT_REALM)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=r, label=r) for r in REALMS],
                    mode=SelectSelectorMode.DROPDOWN,
                    custom_value=True,
                )
            ),
            vol.Required(
                CONF_AUTH_METHOD, default=defaults.get(CONF_AUTH_METHOD, AUTH_TOKEN)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=AUTH_TOKEN, label="API Token"),
                        SelectOptionDict(value=AUTH_PASSWORD, label="Passwort"),
                    ],
                    mode=SelectSelectorMode.LIST,
                    translation_key="auth_method",
                )
            ),
            vol.Optional(CONF_TOKEN_ID, default=defaults.get(CONF_TOKEN_ID, "")): str,
            vol.Optional(CONF_TOKEN_SECRET, default=""): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_PASSWORD, default=""): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required(
                CONF_VERIFY_SSL,
                default=defaults.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            ): bool,
            vol.Required(
                CONF_TIMEOUT, default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
            ): _number(MIN_TIMEOUT, MAX_TIMEOUT, "s"),
        }
    )


def _validate_credentials(user_input: dict[str, Any]) -> str | None:
    """Pruefen, ob zur gewaehlten Methode auch die Felder gefuellt sind."""
    method = user_input.get(CONF_AUTH_METHOD, AUTH_TOKEN)
    if method == AUTH_TOKEN:
        if not user_input.get(CONF_TOKEN_ID) or not user_input.get(CONF_TOKEN_SECRET):
            return "missing_token"
        user_input[CONF_PASSWORD] = ""
    else:
        if not user_input.get(CONF_PASSWORD):
            return "missing_password"
        user_input[CONF_TOKEN_ID] = ""
        user_input[CONF_TOKEN_SECRET] = ""
    return None


def _current_selection(
    items: dict[str, str],
    resource_type: str,
    defaults: Mapping[str, Any],
    auto_add: bool,
) -> list[str]:
    """Welche Eintraege im Formular vorausgewaehlt erscheinen sollen."""
    if auto_add:
        excluded = set(defaults.get(EXCLUDE_KEYS[resource_type], []) or [])
        return [key for key in items if key not in excluded]

    included = defaults.get(INCLUDE_KEYS[resource_type])
    if included is None:
        return list(items)
    return [key for key in items if key in set(included)]


def _resource_schema(
    discovered: dict[str, dict[str, str]],
    defaults: Mapping[str, Any] | None = None,
) -> vol.Schema:
    """Schritt 2: welche Ressourcen ueberwacht werden."""
    defaults = defaults or {}
    auto_add = bool(defaults.get(CONF_AUTO_ADD, DEFAULT_AUTO_ADD))

    schema: dict[Any, Any] = {}

    for resource_type in RESOURCE_ORDER:
        items = discovered.get(resource_type, {})
        if not items:
            continue
        selected = _current_selection(items, resource_type, defaults, auto_add)
        schema[
            vol.Optional(INCLUDE_KEYS[resource_type], default=selected)
        ] = SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=value, label=label)
                    for value, label in items.items()
                ],
                multiple=True,
                mode=SelectSelectorMode.LIST,
            )
        )

    schema[vol.Required(CONF_AUTO_ADD, default=auto_add)] = bool
    schema[
        vol.Required(
            CONF_INCLUDE_TEMPLATES,
            default=defaults.get(CONF_INCLUDE_TEMPLATES, DEFAULT_INCLUDE_TEMPLATES),
        )
    ] = bool

    return vol.Schema(schema)


def _behaviour_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """Schritt 3: Abfrageverhalten und Aufraeumen."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): _number(MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL, "s"),
            vol.Required(
                CONF_GRACE_PERIOD,
                default=defaults.get(CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD),
            ): _number(MIN_GRACE_PERIOD, MAX_GRACE_PERIOD, "d"),
            vol.Required(
                CONF_ENABLE_CONTROLS,
                default=defaults.get(CONF_ENABLE_CONTROLS, DEFAULT_ENABLE_CONTROLS),
            ): bool,
            vol.Required(
                CONF_NODE_DETAILS,
                default=defaults.get(CONF_NODE_DETAILS, DEFAULT_NODE_DETAILS),
            ): bool,
            vol.Required(
                CONF_TASK_WINDOW,
                default=defaults.get(CONF_TASK_WINDOW, DEFAULT_TASK_WINDOW),
            ): _number(MIN_TASK_WINDOW, MAX_TASK_WINDOW, "h"),
        }
    )


def _resource_options(
    user_input: Mapping[str, Any], discovered: dict[str, dict[str, str]]
) -> dict[str, Any]:
    """Auswahl in Einschluss- und Ausschlusslisten uebersetzen.

    Die Ausschlussliste ergibt sich aus dem, was abgewaehlt wurde. Alles, was
    Proxmox spaeter neu meldet, steht damit nicht darin und kommt bei
    aktivierter Auto-Uebernahme von selbst dazu.
    """
    options: dict[str, Any] = {
        CONF_AUTO_ADD: bool(user_input.get(CONF_AUTO_ADD, DEFAULT_AUTO_ADD)),
        CONF_INCLUDE_TEMPLATES: bool(
            user_input.get(CONF_INCLUDE_TEMPLATES, DEFAULT_INCLUDE_TEMPLATES)
        ),
    }

    for resource_type in RESOURCE_ORDER:
        items = discovered.get(resource_type, {})
        selected = set(user_input.get(INCLUDE_KEYS[resource_type], []) or [])
        options[INCLUDE_KEYS[resource_type]] = sorted(selected)
        options[EXCLUDE_KEYS[resource_type]] = sorted(
            key for key in items if key not in selected
        )

    return options


def _behaviour_options(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Verhaltensfelder in Optionen uebersetzen."""
    return {
        CONF_SCAN_INTERVAL: int(
            user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        ),
        CONF_GRACE_PERIOD: int(
            user_input.get(CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD)
        ),
        CONF_ENABLE_CONTROLS: bool(
            user_input.get(CONF_ENABLE_CONTROLS, DEFAULT_ENABLE_CONTROLS)
        ),
        CONF_NODE_DETAILS: bool(
            user_input.get(CONF_NODE_DETAILS, DEFAULT_NODE_DETAILS)
        ),
        CONF_TASK_WINDOW: int(user_input.get(CONF_TASK_WINDOW, DEFAULT_TASK_WINDOW)),
    }


def _counts(discovered: dict[str, dict[str, str]]) -> dict[str, str]:
    """Platzhalter fuer den Beschreibungstext des Auswahlschritts."""
    return {
        "nodes": str(len(discovered.get(TYPE_NODE, {}))),
        "qemu": str(len(discovered.get(TYPE_QEMU, {}))),
        "lxc": str(len(discovered.get(TYPE_LXC, {}))),
        "storage": str(len(discovered.get(TYPE_STORAGE, {}))),
    }


class ProxmoxConfigFlow(ConfigFlow, domain=DOMAIN):
    """Einrichtung ueber die Oberflaeche."""

    VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}
        self._client: ProxmoxClient | None = None
        self._discovered: dict[str, dict[str, str]] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schritt 1: Verbindungsdaten."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_PORT] = int(user_input[CONF_PORT])
            user_input[CONF_TIMEOUT] = int(user_input[CONF_TIMEOUT])
            error = _validate_credentials(user_input)
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                )
                self._abort_if_unique_id_configured()

                try:
                    client, _version = await _test_connection(self.hass, user_input)
                except ProxmoxAuthError:
                    errors["base"] = "invalid_auth"
                except ProxmoxConnectionError as err:
                    _LOGGER.debug("Verbindungstest fehlgeschlagen: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    self._data = dict(user_input)
                    self._client = client
                    return await self.async_step_resources()

        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(user_input),
            errors=errors,
        )

    async def async_step_resources(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schritt 2: welche Ressourcen ueberwacht werden."""
        assert self._client is not None

        if not self._discovered:
            try:
                self._discovered = await self.hass.async_add_executor_job(
                    self._client.discover
                )
            except ProxmoxAuthError:
                return self.async_abort(reason="invalid_auth")
            except ProxmoxConnectionError:
                return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            self._options = _resource_options(user_input, self._discovered)
            return await self.async_step_behaviour()

        return self.async_show_form(
            step_id="resources",
            data_schema=_resource_schema(self._discovered),
            description_placeholders=_counts(self._discovered),
        )

    async def async_step_behaviour(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Schritt 3: Abfrageverhalten und Aufraeumen."""
        if user_input is not None:
            return self.async_create_entry(
                title=f"Proxmox {self._data[CONF_HOST]}",
                data=self._data,
                options={**self._options, **_behaviour_options(user_input)},
            )

        return self.async_show_form(
            step_id="behaviour",
            data_schema=_behaviour_schema(),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Neuanmeldung anstossen."""
        self._data = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Neue Zugangsdaten erfassen."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            user_input[CONF_PORT] = int(user_input[CONF_PORT])
            user_input[CONF_TIMEOUT] = int(user_input[CONF_TIMEOUT])
            error = _validate_credentials(user_input)
            if error:
                errors["base"] = error
            else:
                try:
                    await _test_connection(self.hass, user_input)
                except ProxmoxAuthError:
                    errors["base"] = "invalid_auth"
                except ProxmoxConnectionError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates=user_input
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_connection_schema(user_input or self._data),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> ProxmoxOptionsFlow:
        """Options Flow bereitstellen."""
        return ProxmoxOptionsFlow()


class ProxmoxOptionsFlow(OptionsFlow):
    """Auswahl und Verhalten nachtraeglich aendern."""

    def __init__(self) -> None:
        self._discovered: dict[str, dict[str, str]] = {}

    @property
    def _defaults(self) -> dict[str, Any]:
        """Aktuelle Werte als Vorbelegung der Formulare."""
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Auswahlmenue anzeigen."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["resources", "behaviour"],
        )

    async def async_step_resources(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ressourcenauswahl aendern."""
        if not self._discovered:
            client = _client_from_input(self.config_entry.data)
            try:
                self._discovered = await self.hass.async_add_executor_job(
                    client.discover
                )
            except (ProxmoxAuthError, ProxmoxConnectionError):
                return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    **_resource_options(user_input, self._discovered),
                }
            )

        return self.async_show_form(
            step_id="resources",
            data_schema=_resource_schema(self._discovered, self._defaults),
            description_placeholders=_counts(self._discovered),
        )

    async def async_step_behaviour(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Abfrageverhalten aendern."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    **_behaviour_options(user_input),
                }
            )

        return self.async_show_form(
            step_id="behaviour",
            data_schema=_behaviour_schema(self._defaults),
        )

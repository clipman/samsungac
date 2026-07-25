"""
Config flow for Samsung AC.

This integration is configured entirely through configuration.yaml platform
entries (``climate:`` / ``sensor:`` - ``platform: samsung_ac``), not through
the Home Assistant UI. This config_flow exists purely as internal plumbing:
recent Home Assistant versions require a real ``ConfigEntry`` before a
device can be created in the device registry
(``device_registry.async_get_or_create`` no longer accepts
``config_entry_id=None``). ``climate.py`` / ``sensor.py`` call
``device.async_get_or_create_config_entry()`` on startup, which drives this
flow's "import" step to get (or reuse) one invisible config entry per
physical AC unit, purely so entities can be grouped under a device.

There is intentionally no user-initiated setup flow.
"""
from homeassistant import config_entries

from . import DOMAIN


class SamsungACConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Import-only config flow; see module docstring."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Samsung AC has no interactive setup; it is configured via YAML."""
        return self.async_abort(reason="yaml_only")

    async def async_step_import(self, import_data):
        """
        Create (or reuse) the invisible config entry backing one AC unit's
        device registry entry.

        ``import_data`` is expected to be
        ``{"unique_id": <device unique id>, "title": <device name>}``.
        """
        await self.async_set_unique_id(import_data["unique_id"])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=import_data.get("title", "Samsung AC"),
            data=import_data,
        )

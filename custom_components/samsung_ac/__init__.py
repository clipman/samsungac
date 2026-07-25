DOMAIN = "samsung_ac"

from .connection_request import ConnectionRequest, ConnectionRequestPrint
from .controller_yaml import YamlController
from .properties import (
    GetJsonStatus,
    ModeOperation,
    NumericOperation,
    SwitchOperation,
    TemperatureOperation,
)


async def async_setup_entry(hass, entry):
    """
    Set up a samsung_ac config entry.

    This integration is configured entirely through configuration.yaml
    (climate: / sensor: - platform: samsung_ac); these entries hold no
    data of their own. They exist purely so that the legacy YAML-configured
    entities in climate.py / sensor.py have a real ConfigEntry to attach a
    device to, since Home Assistant's device registry requires one (see
    device.py for details). There's nothing else to set up here.
    """
    return True


async def async_unload_entry(hass, entry):
    """Unload a samsung_ac config entry (see async_setup_entry)."""
    return True


"""
Platform that exposes auxiliary read-only values (air-quality / filter
sensors) reported by locally controlled Samsung air conditioners as
separate Home Assistant sensor entities.

It reuses the same `YamlController` machinery as `climate.py` (same
`samsung_ac.yaml`, same `/devices` JSON endpoint), so the values come
from the `attributes:` section of the yaml file: `clean_level`,
`odor_level`, `pm10`, `pm2_5`.
"""
import logging
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONF_IP_ADDRESS,
    CONF_TOKEN,
    CONF_UNIQUE_ID,
    PERCENTAGE,
)
from homeassistant.exceptions import PlatformNotReady

from .controller import create_controller
from .yaml_const import (
    CONF_CERT,
    CONF_CONFIG_FILE,
    CONF_CONTROLLER,
    CONF_DEBUG,
    CONF_DEVICE_ID,
    CONFIG_DEVICE_NAME,
    CONFIG_DEVICE_POLL,
    CONFIG_DEVICE_UPDATE_DELAY,
    DEFAULT_CONF_CONFIG_FILE,
)

_LOGGER = logging.getLogger(__package__)

DEFAULT_CONF_CERT_FILE = "ac14k_m.pem"
DEFAULT_CONF_CONTROLLER = "yaml"
DEFAULT_UPDATE_DELAY = 1.5
SCAN_INTERVAL = timedelta(seconds=30)

CONF_SENSORS = "sensors"

# yaml `attributes:` key -> HA sensor metadata
SENSOR_TYPES = {
    "clean_level": {
        "name": "Clean Level",
        "icon": "mdi:air-filter",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "odor_level": {
        "name": "Odor Level",
        "icon": "mdi:scent",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "pm10": {
        "name": "PM10",
        "device_class": SensorDeviceClass.PM10,
        "unit": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "pm2_5": {
        "name": "PM2.5",
        "device_class": SensorDeviceClass.PM25,
        "unit": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "humidity": {
        "name": "Humidity",
        "device_class": SensorDeviceClass.HUMIDITY,
        "unit": PERCENTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_IP_ADDRESS): cv.string,
        vol.Optional(CONF_TOKEN): cv.string,
        vol.Optional(CONFIG_DEVICE_NAME): cv.string,
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_CERT, default=DEFAULT_CONF_CERT_FILE): cv.string,
        vol.Optional(CONF_CONFIG_FILE, default=DEFAULT_CONF_CONFIG_FILE): cv.string,
        vol.Optional(CONF_CONTROLLER, default=DEFAULT_CONF_CONTROLLER): cv.string,
        vol.Optional(CONF_DEBUG, default=False): cv.boolean,
        vol.Optional(CONFIG_DEVICE_POLL, default=""): cv.string,
        vol.Optional(
            CONFIG_DEVICE_UPDATE_DELAY, default=DEFAULT_UPDATE_DELAY
        ): cv.string,
        vol.Optional(CONF_DEVICE_ID, default="032000000"): cv.string,
        vol.Optional(CONF_SENSORS, default=list(SENSOR_TYPES.keys())): vol.All(
            cv.ensure_list, [vol.In(SENSOR_TYPES.keys())]
        ),
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up samsung_ac auxiliary sensors."""
    _LOGGER.setLevel(logging.DEBUG if config.get(CONF_DEBUG, False) else logging.WARNING)
    _LOGGER.info("samsung_ac: async setup sensor platform")

    try:
        device_controller = await create_controller(
            config.get(CONF_CONTROLLER), config, _LOGGER
        )
    except Exception as e:
        _LOGGER.error("samsung_ac sensor: error while creating controller!")
        import traceback

        _LOGGER.error(traceback.format_exc())
        _LOGGER.error(e)
        raise PlatformNotReady from e

    if device_controller is None:
        raise PlatformNotReady

    wanted_keys = config.get(CONF_SENSORS, list(SENSOR_TYPES.keys()))
    # Only create entities for values the device/yaml actually reports,
    # e.g. some units don't expose a Sensors array at all.
    available_keys = [k for k in wanted_keys if k in device_controller.attributes]
    missing = set(wanted_keys) - set(available_keys)
    if missing:
        _LOGGER.info(
            "samsung_ac sensor: skipping %s, not present in controller attributes",
            missing,
        )

    entities = [
        ClimateIpSensor(device_controller, config, key) for key in available_keys
    ]

    # All these sensors share one controller/one HTTP round trip to the hub.
    # Only the first entity actually polls; it then pushes the refreshed
    # state to the rest so we don't hit the local device 4x as often.
    if entities:
        primary, *secondary = entities
        primary.linked_entities = secondary
        for ent in secondary:
            ent.is_secondary = True

    async_add_entities(entities, True)


class ClimateIpSensor(SensorEntity):
    """A single read-only value (air quality / filter status) from the AC."""

    def __init__(self, rac_controller, config, key):
        self.rac = rac_controller
        self._key = key
        self.linked_entities = []
        self.is_secondary = False

        meta = SENSOR_TYPES[key]
        self._attr_icon = meta.get("icon")
        self._attr_device_class = meta.get("device_class")
        self._attr_native_unit_of_measurement = meta.get("unit")
        self._attr_state_class = meta.get("state_class")

        base_name = config.get(CONFIG_DEVICE_NAME) or self.rac.name
        self._attr_name = f"{base_name} {meta['name']}"

        base_unique_id = config.get(CONF_UNIQUE_ID) or (
            "samsung_ac_" + (self.rac.unique_id or base_name)
        )
        self._attr_unique_id = f"{base_unique_id}_{key}"

        self._poll = None
        str_poll = config.get(CONFIG_DEVICE_POLL, "")
        if str_poll.lower() == "true":
            self._poll = True
        elif str_poll.lower() == "false":
            self._poll = False

    @property
    def should_poll(self):
        """Only the primary entity of the group actually polls."""
        if self.is_secondary:
            return False
        if self._poll is not None:
            return self._poll
        return self.rac.poll

    async def async_update(self):
        """Refresh the shared controller, then push state to linked sensors."""
        await self.rac.async_update_state()
        for ent in self.linked_entities:
            ent.async_write_ha_state()

    @property
    def native_value(self):
        return self.rac.get_property(self._key)

    @property
    def available(self):
        return self.native_value is not None

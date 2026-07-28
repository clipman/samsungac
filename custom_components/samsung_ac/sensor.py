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

from .controller import ENTITIES, SAMSUNG_AC_DATA, create_controller
from .device import async_register_device
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
        # NOTE: default is an empty list on purpose. If `sensors:` is omitted
        # from the YAML config, no auxiliary sensor entities are created.
        # Sensors are only created when the user explicitly lists them.
        vol.Optional(CONF_SENSORS, default=[]): vol.All(
            cv.ensure_list, [vol.In(SENSOR_TYPES.keys())]
        ),
    }
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up samsung_ac auxiliary sensors."""
    # _LOGGER는 climate 플랫폼, controller_yaml.py, properties.py 등과
    # 공유되는 싱글턴 로거입니다. 여기서 무조건 setLevel()을 부르면, 이
    # sensor 플랫폼이 climate 플랫폼(혹은 다른 기기)보다 나중에 초기화될
    # 때 이미 debug: true로 올려둔 레벨을 WARNING으로 도로 낮춰버립니다.
    # 그래서 "낮추는 것"은 하지 않고 필요할 때 "올리는 것"만 합니다.
    if config.get(CONF_DEBUG, False):
        _LOGGER.setLevel(logging.DEBUG)
    _LOGGER.info("samsung_ac: async setup sensor platform")

    wanted_keys = config.get(CONF_SENSORS, [])
    if not wanted_keys:
        _LOGGER.info(
            "samsung_ac sensor: no 'sensors:' configured, skipping entity creation"
        )
        return

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
        # Show whole numbers in the UI (e.g. "42 %" instead of "42.3 %").
        # This only affects display/rounding - the underlying value stored
        # in history/long-term statistics is untouched.
        self._attr_suggested_display_precision = 0

        base_name = config.get(CONFIG_DEVICE_NAME) or self.rac.name
        self._attr_name = f"{base_name} {meta['name']}"

        base_unique_id = config.get(CONF_UNIQUE_ID) or (
            "samsung_ac_" + (self.rac.unique_id or base_name)
        )
        self._attr_unique_id = f"{base_unique_id}_{key}"

        # Same value climate.py uses as its own unique_id / device identifier,
        # so this sensor is attached to the same device as the AC's climate
        # entity instead of getting its own separate device.
        self._device_unique_id = base_unique_id
        self._device_name = base_name

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

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        # Register into the same shared registry climate.py entities use,
        # so e.g. the samsung_ac_refresh_humidity service can find this
        # sensor (via its shared `rac` controller) and push it a fresh
        # state right after a refresh, instead of it sitting stale until
        # its own next scheduled poll.
        if SAMSUNG_AC_DATA not in self.hass.data:
            self.hass.data[SAMSUNG_AC_DATA] = {ENTITIES: []}
        self.hass.data[SAMSUNG_AC_DATA][ENTITIES].append(self)

        # Same reasoning as climate.py: this platform is configured via
        # configuration.yaml (no config_entry), so device_info is never read
        # automatically. Attach this sensor to the same device as the AC's
        # climate entity (matched by device_unique_id).
        await async_register_device(
            self.hass,
            self,
            device_unique_id=self._device_unique_id,
            name=self._device_name,
        )

    async def async_will_remove_from_hass(self):
        """Run when entity will be removed from hass."""
        await super().async_will_remove_from_hass()
        if SAMSUNG_AC_DATA in self.hass.data:
            self.hass.data[SAMSUNG_AC_DATA][ENTITIES].remove(self)

    async def async_update(self):
        """Refresh the shared controller, then push state to linked sensors."""
        await self.rac.async_update_state()
        for ent in self.linked_entities:
            # During the initial update_before_add pass, linked entities
            # haven't been registered with hass yet (no entity_id assigned),
            # so writing state would raise NoEntitySpecifiedError. Once they
            # are added, hass/entity_id are set and it's safe to push.
            if ent.hass is not None and ent.entity_id is not None:
                ent.async_write_ha_state()

    @property
    def native_value(self):
        return self.rac.get_property(self._key)

    @property
    def available(self):
        return self.native_value is not None

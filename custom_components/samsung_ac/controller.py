import asyncio

from homeassistant.const import CONF_IP_ADDRESS

from .yaml_const import CONF_CONFIG_FILE, CONF_DEVICE_ID

ATTR_POWER = "power"

CLIMATE_CONTROLLERS = []

# Shared hass.data bucket that climate.py and sensor.py entities register
# themselves into, so services (e.g. samsung_ac_refresh_humidity) can find
# and act on entities from either platform without importing one platform
# module from the other.
SAMSUNG_AC_DATA = "samsung_ac_data"
ENTITIES = "entities"

# Controllers are cached per physical device (see _controller_key below) so
# that climate.py and sensor.py - which are configured as separate
# platforms and each call create_controller() independently - end up
# sharing one connection/poll loop and one set of DeviceProperty objects
# for the same device, instead of each polling the device on its own and
# never seeing the other's fresh reads.
_controller_cache = {}
_controller_cache_lock = asyncio.Lock()


def _controller_key(type, config):
    return (
        str(type),
        config.get(CONF_IP_ADDRESS),
        config.get(CONF_DEVICE_ID),
        config.get(CONF_CONFIG_FILE),
    )



class ClimateController:
    def __init__(self, config, logger):
        pass

    def initialize(self):
        return False

    @property
    def poll(self):
        return None

    @property
    def id(self):
        return None

    @property
    def name(self):
        return None

    @property
    def debug(self):
        return False

    def update_state(self):
        return False

    def set_property(self, property_name, new_value):
        return False

    def get_property(self, property_name):
        return None

    @property
    def state_attributes(self):
        raise NotImplementedError()

    @property
    def temperature_unit(self):
        raise NotImplementedError()

    @property
    def service_schema_map(self):
        return None

    @property
    def operations(self):
        """Return a list of available operations"""
        return []

    @property
    def attributes(self):
        """Return a list of available attributes"""
        return []


def register_controller(controller):
    """Decorate a function to register a controller."""
    CLIMATE_CONTROLLERS.append(controller)
    return controller


async def create_controller(type, config, logger) -> ClimateController:
    """
    Create (or reuse) a controller for the given config.

    Multiple platforms (climate, sensor) can be configured against the
    same physical device. Rather than each platform opening its own
    independent connection/poll loop against that device - duplicating hub
    load and leaving each platform holding its own out-of-sync copy of the
    same properties - controllers are cached and reused per physical
    device, identified by controller type + ip address + device id +
    config file.
    """
    key = _controller_key(type, config)
    async with _controller_cache_lock:
        cached = _controller_cache.get(key)
        if cached is not None:
            logger.info("samsung_ac: reusing existing controller for device %s", key)
            return cached

        for ctrl in CLIMATE_CONTROLLERS:
            if ctrl.match_type(type):
                c = ctrl(config, logger)
                if await c.initialize():
                    _controller_cache[key] = c
                    return c
                else:
                    logger.error(
                        "samsung_ac: error while initializing controller for type {}!".format(
                            type
                        )
                    )
        logger.error("samsung_ac: controller for type {} not found!".format(type))
        return None

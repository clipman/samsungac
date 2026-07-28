import json
import logging

import homeassistant.helpers.config_validation as cv
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNKNOWN, UnitOfTemperature
from homeassistant.util.unit_conversion import TemperatureConverter

from .connection import Connection
from .yaml_const import (
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_TEMPLATE,
    CONFIG_DEVICE_IGNORE_VALUES,
    CONFIG_DEVICE_KEEP_LAST_VALUE,
    CONFIG_DEVICE_OPERATION_NUMBER_MAX,
    CONFIG_DEVICE_OPERATION_NUMBER_MIN,
    CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE,
    CONFIG_DEVICE_OPERATION_VALUE,
    CONFIG_DEVICE_OPERATION_VALUES,
    CONFIG_DEVICE_STATUS_TEMPLATE,
    CONFIG_DEVICE_VALIDATION_TEMPLATE,
    CONFIG_TYPE,
)

CLIMATE_IP_PROPERTIES = []
CLIMATE_IP_STATUS_GETTER = []

_LOGGER = logging.getLogger(__package__)

PROPERTY_TYPE_STRING = "string"
PROPERTY_TYPE_MODE = "modes"
PROPERTY_TYPE_SWITCH = "switch"
PROPERTY_TYPE_NUMBER = "number"
PROPERTY_TYPE_TEMP = "temperature"
STATUS_GETTER_JSON = "json_status"

UNIT_MAP = {
    "C": UnitOfTemperature.CELSIUS,
    "c": UnitOfTemperature.CELSIUS,
    "Celsius": UnitOfTemperature.CELSIUS,
    "F": UnitOfTemperature.FAHRENHEIT,
    "f": UnitOfTemperature.FAHRENHEIT,
    "Fahrenheit": UnitOfTemperature.FAHRENHEIT,
    UnitOfTemperature.CELSIUS: UnitOfTemperature.CELSIUS,
    UnitOfTemperature.FAHRENHEIT: UnitOfTemperature.FAHRENHEIT,
}


def register_property(dev_prop):
    """Decorate a function to register a propery."""
    CLIMATE_IP_PROPERTIES.append(dev_prop)
    return dev_prop


def register_status_getter(getter):
    """Decorate a function to register a status getter."""
    CLIMATE_IP_STATUS_GETTER.append(getter)
    return getter


def create_property(name, node, connection_base):
    for prop in CLIMATE_IP_PROPERTIES:
        if CONFIG_TYPE in node:
            if prop.match_type(node[CONFIG_TYPE]):
                op = prop(name, connection_base)
                if op.load_from_yaml(node):
                    return op
    return None


def create_status_getter(name, node, connection_base):
    for getter in CLIMATE_IP_STATUS_GETTER:
        if CONFIG_TYPE in node:
            if getter.match_type(node[CONFIG_TYPE]):
                g = getter(name, connection_base)
                if g.load_from_yaml(node):
                    return g
    return None


class DeviceProperty:
    def __init__(self, name, connection):
        self._name = name
        self._value = STATE_UNKNOWN
        self._connection = connection
        self._status_template = None
        self._id = name
        self._connection_template = None
        self._validation_template = None
        self._device_state = None
        # When True, a status_template render that comes back empty/None
        # (device simply didn't include this field this cycle, e.g. a
        # humidity sensor Samsung only reports while in Dry mode) keeps the
        # last known good value instead of dropping to unknown/unavailable.
        self._keep_last_value = False
        # Additional rendered values (as strings, after stripping) that
        # should be treated the same as an empty/None render for the
        # purposes of keep_last_value - i.e. "the device did not actually
        # report a fresh value this cycle". Some Samsung units send a
        # literal sentinel (e.g. "0" for humidity when it isn't currently
        # being measured) instead of omitting the field or sending null, so
        # empty/None alone isn't enough to detect a stale/placeholder read.
        self._ignore_values = []
        # True while the property is currently "stuck" on a kept last value
        # because the device is reporting a placeholder. Used so the INFO
        # log below only fires on the transition into/out of that state
        # instead of every single poll cycle.
        self._showing_placeholder = False

    def _is_placeholder_value(self, v):
        """
        Return True if a rendered status_template value should be treated
        as "the device did not report a fresh value this cycle" rather
        than a real reading - i.e. the same case as an empty/None render.
        Only consulted when keep_last_value is enabled.
        Subclasses (e.g. numeric properties) extend this with type-specific
        checks.
        """
        s = str(v).strip()
        return s in ("", "None") or s in self._ignore_values

    @property
    def id(self):
        return self._id

    def is_valid(self, device_state):
        self._device_state = device_state
        if self.validation_template is None or device_state is None:
            return True
        else:
            try:
                v = self.validation_template.render(device_state=device_state)
                return str(v).lower() == "valid"
            except:
                return False

    @property
    def config_validation_type(self):
        return cv.string

    @property
    def status_template(self):
        return self._status_template

    @property
    def value(self):
        return self._value

    @property
    def name(self):
        return self._name

    def get_connection(self, value):
        return self._connection

    @property
    def connection_template(self):
        return self._connection_template

    @property
    def validation_template(self):
        return self._validation_template

    def load_from_yaml(self, node):
        """Load configuration from yaml node dictionary. Return True if successful False otherwise."""
        from jinja2 import Template

        if node is not None:
            if CONFIG_DEVICE_STATUS_TEMPLATE in node:
                self._status_template = Template(node[CONFIG_DEVICE_STATUS_TEMPLATE])
            if CONFIG_DEVICE_CONNECTION_TEMPLATE in node:
                self._connection_template = Template(
                    node[CONFIG_DEVICE_CONNECTION_TEMPLATE]
                )
            if CONFIG_DEVICE_VALIDATION_TEMPLATE in node:
                self._validation_template = Template(
                    node[CONFIG_DEVICE_VALIDATION_TEMPLATE]
                )
            self._keep_last_value = bool(node.get(CONFIG_DEVICE_KEEP_LAST_VALUE, False))
            self._ignore_values = [
                str(v).strip() for v in node.get(CONFIG_DEVICE_IGNORE_VALUES, [])
            ]
            self._connection = self._connection.create_updated(
                node.get(CONFIG_DEVICE_CONNECTION, {})
            )
            return True
        return False

    def convert_dev_to_hass(self, dev_value):
        """Convert device state value to HASS."""
        return dev_value

    async def async_update_state(self, device_state, debug):
        """
        Update property from device state and return current value.
        This method is now async.
        """
        self._device_state = device_state
        v = STATE_UNKNOWN
        if self.status_template is not None and device_state is not None:
            try:
                v = self.status_template.render(device_state=device_state)
            except Exception as e:
                # Previously silently swallowed, which made "the device
                # simply omitted this field" indistinguishable from "our
                # template is broken" in the logs. Surface it (at debug, so
                # it doesn't spam by default when a field is legitimately
                # absent for some device models).
                _LOGGER.debug(
                    "samsung_ac: %s status_template render failed: %s",
                    self._id,
                    e,
                )
                if self._keep_last_value:
                    # A field that's missing entirely from this cycle's
                    # JSON (e.g. some devices only include "Humidity" at
                    # all right after being nudged, and drop the key
                    # outright the rest of the time - not just null/empty)
                    # is functionally the same "no fresh value this cycle"
                    # situation as an empty render. Route it through the
                    # same placeholder bookkeeping/logging below instead of
                    # leaving it here as a silent debug-only dead end - the
                    # INFO transition log is exactly what's needed to
                    # confirm the kept value logic engaged.
                    v = ""
        if v is not STATE_UNKNOWN:
            if self._keep_last_value and self._is_placeholder_value(v):
                # The device omitted/nulled this field this cycle (e.g. some
                # Samsung units only ever populate Humidity while in Dry
                # mode), or reported a known placeholder value (configured
                # via ignore_values, or - for numeric properties - anything
                # that doesn't even parse as a number, like "-"). Rather
                # than flashing to unknown/unavailable - or worse, silently
                # overwriting the last real reading with a bogus one - hang
                # onto the last real value until a genuine new one arrives.
                if not self._showing_placeholder:
                    # Log the transition at INFO so it's visible without
                    # needing debug: true - this is the exact moment
                    # people need visibility into (e.g. right after a
                    # "refresh humidity" nudge, seeing whether the kept
                    # value logic actually engaged).
                    _LOGGER.info(
                        "samsung_ac: %s got placeholder value %r, keeping "
                        "last value %r (further placeholder reads logged "
                        "at debug level until a fresh value arrives)",
                        self._id,
                        v,
                        self._value,
                    )
                    self._showing_placeholder = True
                elif debug:
                    _LOGGER.debug(
                        "samsung_ac: %s still getting placeholder value "
                        "%r, keeping last value %r",
                        self._id,
                        v,
                        self._value,
                    )
                return self.value
            if self._showing_placeholder:
                _LOGGER.info(
                    "samsung_ac: %s got a fresh value %r, no longer using "
                    "kept last value",
                    self._id,
                    v,
                )
                self._showing_placeholder = False
            self._value = self.convert_dev_to_hass(v)
        return self.value

    @property
    def state_attributes(self):
        """Return dictionary with property attributes."""
        return {self.id: self.value}


@register_status_getter
class GetJsonStatus(DeviceProperty):
    def __init__(self, name, connection):
        super(GetJsonStatus, self).__init__(name, connection)
        self._json_status = None
        self._attrs = {}

    @staticmethod
    def match_type(type):
        return type == STATUS_GETTER_JSON

    async def async_update_state(self, device_state, debug):
        """
        Fetches the device state asynchronously.
        """
        self._device_state = device_state
        # The execute method is now async, so we must await it
        device_state_result = await self.get_connection(None).execute(
            self.connection_template, None, device_state
        )
        
        self._value = device_state_result
        self._json_status = device_state_result
        
        if device_state_result is not None:
            self._attrs = {"device_state": json.dumps(device_state_result)}
            if self.status_template is not None:
                try:
                    v = self.status_template.render(device_state=device_state_result)
                    # Handle different potential return types from templates
                    if isinstance(v, str):
                        v = v.replace("'", '"')
                        v = v.replace("True", '"True"')
                        self._value = json.loads(v)
                    else:
                        self._value = v
                except Exception:
                    # Template might not render to JSON, which is fine
                    pass
        else:
            self._attrs = {"device_state": None}

        return self.value

    @property
    def state_attributes(self):
        """Return dictionary with property attributes."""
        return self._attrs


class DeviceOperation(DeviceProperty):
    def __init__(self, name, connection):
        super(DeviceOperation, self).__init__(name, connection)

    async def async_set_value(self, v):
        """
        Set device property value asynchronously.
        """
        resp = await self.get_connection(v).execute(
            self.connection_template, self.convert_hass_to_dev(v), self._device_state
        )
        return resp is not None

    def match_value(self, value):
        """Check if value match to operation. True if value is correct."""
        return False

    def convert_hass_to_dev(self, hass_value):
        """Convert HASS state value to device state."""
        return hass_value


class BasicDeviceOperation(DeviceOperation):
    def __init__(self, name, connection):
        super(BasicDeviceOperation, self).__init__(name, connection)
        self._values_dev_to_ha_map = {}
        self._values_ha_to_dev_map = {}
        self._values = []
        self._value_connections_map = {}

    def get_connection(self, value):
        return self._value_connections_map.get(value, self._connection)

    def load_from_yaml(self, node):
        """Load configuration from yaml node dictionary. Return True if successful False otherwise."""
        if super(BasicDeviceOperation, self).load_from_yaml(node):
            if node is not None:
                node_values = node.get(CONFIG_DEVICE_OPERATION_VALUES, {})
                if len(node_values) == 0:
                    return False

                for ha_value in node_values.keys():
                    node_value = node_values[ha_value]
                    r = self._connection.create_updated(
                        node_value.get(CONFIG_DEVICE_CONNECTION, {})
                    )
                    self._value_connections_map[ha_value] = r
                    self._values.append(ha_value)
                    if CONFIG_DEVICE_OPERATION_VALUE in node_value:
                        dev_value = node_value[CONFIG_DEVICE_OPERATION_VALUE]
                        self._values_dev_to_ha_map[dev_value] = ha_value
                        self._values_ha_to_dev_map[ha_value] = dev_value

                return True
        return False

    @property
    def values(self):
        return self._values

    def match_value(self, value):
        """Check if value match to operation. True if value is correct."""
        return value in self._values_ha_to_dev_map

    def convert_dev_to_hass(self, dev_value):
        """Convert device state value to HASS."""
        return self._values_dev_to_ha_map.get(dev_value, dev_value)

    def convert_hass_to_dev(self, ha_value):
        """Convert HASS state value to device state."""
        return self._values_ha_to_dev_map.get(ha_value, ha_value)


@register_property
class ModeOperation(BasicDeviceOperation):
    def __init__(self, name, connection):
        super(ModeOperation, self).__init__(name, connection)
        self._id = name + "_mode"

    @staticmethod
    def match_type(type):
        return type == PROPERTY_TYPE_MODE

    @property
    def state_attributes(self):
        """Return dictionary with property attributes."""
        data = {}
        data[self.id] = self.value
        data[self.name + "_modes"] = self.values
        return data


@register_property
class UniqueIdProperty(DeviceProperty):
    def __init__(self, name, connection):
        super().__init__(name, connection)

    @staticmethod
    def match_type(type):
        return type == PROPERTY_TYPE_STRING


@register_property
class SwitchOperation(BasicDeviceOperation):
    def __init__(self, name, connection):
        super(SwitchOperation, self).__init__(name, connection)

    @staticmethod
    def match_type(type):
        return type == PROPERTY_TYPE_SWITCH

    def load_from_yaml(self, node):
        """Load configuration from yaml node dictionary. Return True if successful False otherwise."""
        if super(SwitchOperation, self).load_from_yaml(node):
            if STATE_OFF in self._values_ha_to_dev_map:
                self._values_ha_to_dev_map[False] = self._values_ha_to_dev_map[
                    STATE_OFF
                ]
            if STATE_ON in self._values_ha_to_dev_map:
                self._values_ha_to_dev_map[True] = self._values_ha_to_dev_map[STATE_ON]
            return True

        return False


class BasicNumericOperation(DeviceOperation):
    def __init__(self, name, connection):
        super(BasicNumericOperation, self).__init__(name, connection)
        self._min = None
        self._max = None
        self._value = 0.0

    @property
    def value(self):
        try:
            return float(self._value)
        except (ValueError, TypeError):
            return None

    def _is_placeholder_value(self, v):
        """
        In addition to the base empty/None/ignore_values checks, treat any
        render that doesn't even parse as a number as a placeholder. Some
        devices signal "not currently measured" with a non-numeric marker
        (e.g. "-", matching what the vendor app itself shows in that state)
        rather than an empty string, null, or a numeric sentinel - those
        specific markers still need keep_last_value on to take effect, but
        we don't need to know the exact marker text ahead of time.
        """
        if super()._is_placeholder_value(v):
            return True
        try:
            parsed = float(str(v).strip())
        except (TypeError, ValueError):
            return True

        # The base class's ignore_values check only catches an exact string
        # match (e.g. configured ignore_values: ["0"] against a rendered
        # "0"). But numeric device fields commonly come back through Jinja
        # as e.g. "0.0" for a Python float 0.0, which never equals the
        # string "0" - silently defeating the sentinel entirely and letting
        # the placeholder overwrite a real kept value (observed: Humidity
        # current comes back as 0.0, not 0). Compare numerically as well so
        # "0", "0.0", "0.00" etc. all match the same configured sentinel.
        for ignored in self._ignore_values:
            try:
                if float(ignored) == parsed:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    @property
    def config_validation_type(self):
        return cv.positive_int

    def match_value(self, value):
        """Check if value match to operation. True if value is correct."""
        try:
            return self.convert_hass_to_dev(float(value)) == value
        except ValueError:
            return False

    def load_from_yaml(self, node):
        """Load configuration from yaml node dictionary. Return True if successful False otherwise."""
        if not super(BasicNumericOperation, self).load_from_yaml(node):
            return False

        if node is not None:
            self._min = node.get(CONFIG_DEVICE_OPERATION_NUMBER_MIN, None)
            self._max = node.get(CONFIG_DEVICE_OPERATION_NUMBER_MAX, None)
            return True

        return False

    def convert_hass_to_dev(self, hass_value):
        """Convert HASS state value to device state."""
        if self._min is not None and hass_value < self._min:
            return self._min
        if self._max is not None and hass_value > self._max:
            return self._max

        return hass_value


@register_property
class NumericOperation(BasicNumericOperation):
    def __init__(self, name, connection):
        super(NumericOperation, self).__init__(name, connection)

    @staticmethod
    def match_type(type):
        return type == PROPERTY_TYPE_NUMBER


@register_property
class TemperatureOperation(BasicNumericOperation):
    def __init__(self, name, connection):
        super(TemperatureOperation, self).__init__(name, connection)
        self._unit_template = None
        self._unit = UnitOfTemperature.CELSIUS

    @staticmethod
    def match_type(type):
        return type == PROPERTY_TYPE_TEMP

    def load_from_yaml(self, node):
        from jinja2 import Template

        if not super(TemperatureOperation, self).load_from_yaml(node):
            return False

        if node is not None and CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE in node:
            self._unit_template = Template(
                node[CONFIG_DEVICE_OPERATION_TEMP_UNIT_TEMPLATE]
            )
        return True

    async def async_update_state(self, device_state, debug):
        if self._unit_template is not None and device_state is not None:
            try:
                unit = self._unit_template.render(device_state=device_state)
                if unit in UNIT_MAP:
                    self._unit = UNIT_MAP[unit]
            except:
                pass

        return await super().async_update_state(device_state, debug)

    def convert_dev_to_hass(self, dev_value):
        """Convert device state value to HASS."""
        return TemperatureConverter.convert(
            float(dev_value), self._unit, UnitOfTemperature.CELSIUS
        )

    def convert_hass_to_dev(self, hass_value):
        v = hass_value
        if self._min is not None and hass_value < self._min:
            v = self._min
        if self._max is not None and hass_value > self._max:
            v = self._max

        return TemperatureConverter.convert(
            float(v), UnitOfTemperature.CELSIUS, self._unit
        )

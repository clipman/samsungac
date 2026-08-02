import asyncio
import concurrent.futures
import json
import logging
import os
import ssl
import time
import traceback

from homeassistant.const import CONF_IP_ADDRESS, CONF_MAC, CONF_PORT, CONF_TOKEN
from requests.adapters import HTTPAdapter

from .connection import Connection, register_connection
from .yaml_const import (
    CONF_CERT,
    CONFIG_DEVICE_CONDITION_TEMPLATE,
    CONFIG_DEVICE_CONNECTION,
    CONFIG_DEVICE_CONNECTION_PARAMS,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

CONNECTION_TYPE_REQUEST = "request"
CONNECTION_TYPE_REQUEST_PRINT = "request_print"

# ---------------------------------------------------------------------------
# Shared GET-response cache.
#
# The hub's status endpoint (GET /devices) returns the state of *every*
# physical device in one response, and its URL does not depend on
# device_id. When multiple platform instances are configured for
# different devices on the same hub (e.g. "안방 에어컨" and "거실 에어컨"
# climate entities, or a climate + sensor pair for the same unit), they
# each poll independently but end up requesting the exact same URL within
# milliseconds of each other. Caching that response for a few seconds lets
# the second/third caller reuse it instead of hitting the local hub again.
#
# This intentionally only applies to GET requests: PUT commands have side
# effects and must never be deduplicated/cached.
# ---------------------------------------------------------------------------
_GET_CACHE_TTL_SECONDS = 5.0
_GET_RESPONSE_CACHE = {}  # url -> (fetched_at, (json, ok, code))


def _redact_params(params):
    """Return a copy of the request params with the auth token masked, for logging."""
    safe = dict(params)
    headers = safe.get("headers")
    if isinstance(headers, dict) and "Authorization" in headers:
        headers = dict(headers)
        headers["Authorization"] = "Bearer ***redacted***"
        safe["headers"] = headers
    return safe


class SamsungHTTPAdapter(HTTPAdapter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
        ssl_context.set_ciphers("ALL:@SECLEVEL=0")
        kwargs["ssl_context"] = ssl_context
        return super().init_poolmanager(*args, **kwargs)


class ConnectionRequestBase(Connection):
    def __init__(self, hass_config, logger):
        super(ConnectionRequestBase, self).__init__(hass_config, logger)
        self._params = {"timeout": 5}
        self._embedded_command = None
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
        self.update_configuration_from_hass(hass_config)
        self._condition_template = None
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def __del__(self):
        self._thread_pool.shutdown(wait=False)

    @property
    def embedded_command(self):
        return self._embedded_command

    @property
    def condition_template(self):
        return self._condition_template

    def update_configuration_from_hass(self, hass_config):
        if hass_config is not None:
            cert_file = hass_config.get(CONF_CERT, None)
            if cert_file is not None:
                if cert_file.find("\\") == -1 and cert_file.find("/") == -1:
                    cert_file = os.path.join(os.path.dirname(__file__), cert_file)

            self._params[CONF_CERT] = cert_file

    def load_from_yaml(self, node, connection_base):
        from jinja2 import Template

        if connection_base:
            self._params.update(connection_base._params.copy())
            self._condition_template = connection_base._condition_template

        if node:
            self._params.update(node.get(CONFIG_DEVICE_CONNECTION_PARAMS, {}))
            if CONFIG_DEVICE_CONNECTION in node:
                self._embedded_command = self.create_updated(
                    node[CONFIG_DEVICE_CONNECTION]
                )
            if CONFIG_DEVICE_CONDITION_TEMPLATE in node:
                self._condition_template = Template(
                    node[CONFIG_DEVICE_CONDITION_TEMPLATE]
                )

        return True

    def check_execute_condition(self, device_state):
        do_execute = True
        self.logger.debug("Checking execute condition")
        if self.condition_template is not None:
            self.logger.debug("Execute condition found, evaluating")
            try:
                rendered_condition = self.condition_template.render(
                    device_state=device_state
                )
                self.logger.debug(
                    "Execute condition evaluated: {0}".format(rendered_condition)
                )
                do_execute = rendered_condition == "1"
            except:
                self.logger.error(
                    "Execute condition found, error while evaluating, executing command"
                )
                do_execute = True
        else:
            self.logger.debug("Execute condition not found, executing")

        return do_execute

    async def execute_internal(self, template, value, device_state) -> (json, bool, int):
        import warnings

        import requests
        from requests.packages.urllib3.exceptions import InsecureRequestWarning

        # IMPORTANT: copy, don't alias, self._params. self._params is shared
        # state on this Connection object, which can be reused across
        # multiple concurrent async_set_property calls for the same
        # operation (e.g. a user double-tapping the same control quickly).
        # The actual HTTP call happens later, inside do_request(), on a
        # background thread - if that closure read self._params directly
        # (as it used to) instead of this local snapshot, a second
        # concurrent call could overwrite self._params with its own body
        # before the first call's request actually goes out, sending the
        # wrong payload for one of the two calls.
        params = dict(self._params)
        if template is not None:
            params.update(
                json.loads(template.render(value=value, device_state=device_state))
            )

        # Only idempotent status GETs are cache-eligible; PUT commands always execute.
        cache_key = params.get("url") if params.get("method") == "GET" else None
        if cache_key is not None:
            cached = _GET_RESPONSE_CACHE.get(cache_key)
            if cached is not None and (time.time() - cached[0]) < _GET_CACHE_TTL_SECONDS:
                self.logger.debug(
                    "Reusing cached GET response for %s (%.1fs old) instead of "
                    "hitting the hub again - another configured device most "
                    "likely just fetched the same status endpoint.",
                    cache_key,
                    time.time() - cached[0],
                )
                return cached[1]

        def do_request():
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=InsecureRequestWarning)
                with requests.sessions.Session() as session:
                    self.logger.debug("Setting up HTTP Adapter and ssl context")

                    _LOGGER.debug(f"execute_internal - self: {self} - params: {_redact_params(params)} - template: {template} - value: {value} - device_state: {device_state}")

                    session.mount("https://", SamsungHTTPAdapter())
                    self.logger.debug(_redact_params(params))

                    return session.request(**params)

        loop = asyncio.get_running_loop()
        try:
            resp = await loop.run_in_executor(self._thread_pool, do_request)
        except Exception as ex:
            # something goes wrong, log the full callstack through the HA
            # logger (traceback.print_exc() only writes to stderr, which
            # doesn't show up in the HA log viewer) and return None.
            self.logger.error(
                "Request execution failed (%s: %s). Stack trace:\n%s",
                type(ex).__name__,
                ex,
                traceback.format_exc(),
            )
            return (None, False, 0)

        self.logger.debug(
            "Command executed with code: {}, text: {}".format(
                resp.status_code, resp.text[:300]
            )
        )

        result = (None, False, 0)
        if resp and resp.ok:
            if resp.status_code == 200:
                try:
                    j = resp.json()
                    result = (j, True, resp.status_code)
                except:
                    self.logger.warning("Parsing response json failed!")
            else:
                result = ({}, True, resp.status_code)

        elif resp:
            self.logger.error(
                "Execution failed, status code: {}, text: {}".format(
                    resp.status_code, resp.text
                )
            )
            result = (None, False, resp.status_code)
        else:
            self.logger.error("Execution failed, unknown error")

        if cache_key is not None and result[1]:
            _GET_RESPONSE_CACHE[cache_key] = (time.time(), result)

        return result

    async def execute(self, template, value, device_state):
        if self.embedded_command:
            self.logger.debug("Embedded command found, executing...")
            await self.embedded_command.execute(template, value, device_state)

        if not self.check_execute_condition(device_state):
            self.logger.debug("Execute condition not met, skipping command")
            return ({}, True, 200)

        self.logger.debug("Executing command...")
        j, ok, code = await self.execute_internal(template, value, device_state)
        if not j and (code == 0 or 500 <= code < 505):
            # server error or connection-level failure (timeout, refused,
            # DNS, etc. - code 0), try again once
            self.logger.debug(
                "First attempt failed (code=%s), retrying once in 1s", code
            )
            await asyncio.sleep(1.0)
            j = (await self.execute_internal(template, value, device_state))[0]

        return j


@register_connection
class ConnectionRequest(ConnectionRequestBase):
    def __init__(self, hass_config, logger):
        super(ConnectionRequest, self).__init__(hass_config, logger)

    @staticmethod
    def match_type(type):
        return type == CONNECTION_TYPE_REQUEST

    def create_updated(self, node):
        c = ConnectionRequest(None, self.logger)
        c.load_from_yaml(node, self)
        return c


test_json = {
    "Devices": [
        {
            "Alarms": [
                {
                    "alarmType": "Device",
                    "code": "FilterAlarm",
                    "id": "0",
                    "triggeredTime": "2019-02-25T08:46:01",
                }
            ],
            "ConfigurationLink": {"href": "/devices/0/configuration"},
            "Diagnosis": {"diagnosisStart": "Ready"},
            "EnergyConsumption": {"saveLocation": "/files/usage.db"},
            "InformationLink": {"href": "/devices/0/information"},
            "Mode": {
                "modes": ["Auto"],
                "options": [
                    "Comode_Off",
                    "Sleep_0",
                    "Autoclean_Off",
                    "Spi_Off",
                    "FilterCleanAlarm_0",
                    "OutdoorTemp_63",
                    "CoolCapa_35",
                    "WarmCapa_40",
                    "UsagesDB_254",
                    "FilterTime_10000",
                    "OptionCode_54458",
                    "UpdateAllow_0",
                    "FilterAlarmTime_500",
                    "Function_15",
                    "Volume_100",
                ],
                "supportedModes": ["Cool", "Dry", "Wind", "Auto"],
            },
            "Operation": {"power": "Off"},
            "Temperatures": [
                {
                    "current": 22.0,
                    "desired": 25.0,
                    "id": "0",
                    "maximum": 30,
                    "minimum": 16,
                    "unit": "Celsius",
                }
            ],
            "Wind": {"direction": "Fix", "maxSpeedLevel": 4, "speedLevel": 0},
            "connected": True,
            "description": "TP6X_RAC_16K",
            "id": "0",
            "name": "RAC",
            "resources": [
                "Alarms",
                "Configuration",
                "Diagnosis",
                "EnergyConsumption",
                "Information",
                "Mode",
                "Operation",
                "Temperatures",
                "Wind",
            ],
            "type": "Air_Conditioner",
            "uuid": "00000000-0000-0000-0000-000000000000",
        }
    ]
}


@register_connection
class ConnectionRequestPrint(ConnectionRequestBase):
    def __init__(self, hass_config, logger):
        super(ConnectionRequestPrint, self).__init__(hass_config, logger)

    @staticmethod
    def match_type(type):
        return type == CONNECTION_TYPE_REQUEST_PRINT

    def create_updated(self, node):
        c = ConnectionRequestPrint(None, self.logger)
        c.load_from_yaml(node, self)
        return c

    async def execute_internal(self, template, value, device_state) -> (json, bool, int):
        self.logger.info(
            "ConnectionRequestPrint, execute with params: {}".format(self._params)
        )
        return (test_json, True, 200)

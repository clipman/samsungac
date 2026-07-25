"""
Helpers for grouping this integration's entities under a Home Assistant
"device" (Settings > Devices & Services > Devices), even though this
integration has no user-facing config_flow / ConfigEntry.

Background
----------
Home Assistant normally creates a device automatically from an entity's
``device_info`` property, but *only* when the entity was added through a
ConfigEntry (see
https://developers.home-assistant.io/docs/device_registry_index/ :
"Entity device info is only read if the entity is loaded via a config
entry"). This integration is configured entirely through
``configuration.yaml`` via ``async_setup_platform``, so there is no
ConfigEntry behind ``climate.py`` / ``sensor.py`` entities and
``device_info`` would silently be ignored.

On top of that, current Home Assistant versions require
``device_registry.async_get_or_create`` to be given a *real*
``config_entry_id`` - passing ``None`` now raises
``HomeAssistantError("Can't link device to unknown config entry None")``
instead of creating an "orphan" device the way older versions allowed.

So, to still get a single device that groups the climate entity and its
associated sensors:

1. We drive ``config_flow.SamsungACConfigFlow``'s import step to get (or
   reuse) one invisible ``ConfigEntry`` per physical AC unit
   (``async_get_or_create_config_entry``). This entry holds no data of its
   own; see ``__init__.async_setup_entry``.
2. We create the device in the device registry under that entry's id, and
   manually attach the entity to it via the entity registry
   (``async_register_device``). This must be done from the entity's
   ``async_added_to_hass``, once it actually has an ``entity_id`` and a
   registry entry (i.e. a ``unique_id`` was set).
"""
import logging

from homeassistant import config_entries
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from . import DOMAIN

_LOGGER = logging.getLogger(__package__)


async def async_get_or_create_config_entry(hass, unique_id, title):
    """
    Find (or, on first run, create via an internal import flow) the
    samsung_ac ConfigEntry for a given device ``unique_id``.

    The entry is invisible/empty; it exists solely so
    ``device_registry.async_get_or_create`` has something valid to point
    at. Once created it persists across restarts (matched by
    ``unique_id``), so this only actually creates a new entry once per
    configured AC unit.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.unique_id == unique_id:
            return entry

    await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_IMPORT},
        data={"unique_id": unique_id, "title": title},
    )

    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.unique_id == unique_id:
            return entry

    _LOGGER.warning(
        "samsung_ac: could not create/find config entry for device '%s'; "
        "entities will not be grouped under a device",
        unique_id,
    )
    return None


async def async_register_device(
    hass,
    entity,
    device_unique_id,
    name,
    manufacturer="Samsung",
    model="Air Conditioner",
    sw_version=None,
):
    """
    Create (or fetch) the device identified by ``device_unique_id`` and
    attach ``entity`` to it.

    Call this from the entity's ``async_added_to_hass``, *after*
    ``await super().async_added_to_hass()`` has already run.

    - ``device_unique_id`` should be the same value for every entity that
      belongs to the same physical AC unit (climate entity + its sensors),
      so they all resolve to a single device entry.
    - ``entity`` must have a ``unique_id`` set, otherwise Home Assistant
      never created an entity registry entry for it and there is nothing
      to attach.
    """
    if device_unique_id is None:
        _LOGGER.debug(
            "samsung_ac: cannot register device for %s, no unique_id available",
            getattr(entity, "entity_id", entity),
        )
        return None

    config_entry = await async_get_or_create_config_entry(
        hass, device_unique_id, name
    )
    if config_entry is None:
        return None

    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, device_unique_id)},
        name=name,
        manufacturer=manufacturer,
        model=model,
        sw_version=sw_version,
    )

    entity_registry = er.async_get(hass)
    if entity.entity_id is not None:
        registry_entry = entity_registry.async_get(entity.entity_id)
        if registry_entry is not None and registry_entry.device_id != device_entry.id:
            entity_registry.async_update_entity(
                entity.entity_id, device_id=device_entry.id
            )

    return device_entry

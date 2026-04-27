"""SL Busslinje – realtids-GPS via Trafiklab GTFS-RT."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, DEFAULT_LINE
from .coordinator import SLBusCoordinator

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["device_tracker"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    line = entry.options.get("line", entry.data.get("line", DEFAULT_LINE))

    coordinator = SLBusCoordinator(
        hass,
        rt_key=entry.data["rt_key"],
        static_key=entry.data["static_key"],
        line=line,
    )

    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ta bort alla gamla entiteter och ladda om när linjen byts."""
    _LOGGER.info("Linje ändrad – rensar gamla entiteter och laddar om")

    # Ta bort alla entiteter som tillhör den här config entry
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    for entity in entities:
        registry.async_remove(entity.entity_id)
        _LOGGER.debug("Tog bort entitet %s", entity.entity_id)

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        coordinator.async_unload()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

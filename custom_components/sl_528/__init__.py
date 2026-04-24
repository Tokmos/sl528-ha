"""SL Busslinje – realtids-GPS via Trafiklab GTFS-RT."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

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

    # Lyssna på options-ändringar (när användaren byter linje)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ladda om integrationen när linjen byts."""
    _LOGGER.info("Linje ändrad – laddar om integrationen")
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        coordinator.async_unload()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

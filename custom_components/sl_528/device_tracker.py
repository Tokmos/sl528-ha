"""Device tracker – en entitet per buss på linje 528."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SL528Coordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SL528Coordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _handle_coordinator_update() -> None:
        new_entities = []
        for vehicle_id in coordinator.data:
            if vehicle_id not in known:
                known.add(vehicle_id)
                new_entities.append(BusTracker(coordinator, vehicle_id))
        if new_entities:
            async_add_entities(new_entities)

        gone = known - set(coordinator.data.keys())
        if gone:
            registry = er.async_get(hass)
            for vehicle_id in gone:
                known.discard(vehicle_id)
                unique_id = f"sl_528_{vehicle_id}"
                entity_id = registry.async_get_entity_id("device_tracker", DOMAIN, unique_id)
                if entity_id:
                    registry.async_remove(entity_id)
                    _LOGGER.debug("Tog bort fordon %s", vehicle_id)

    coordinator.async_add_listener(_handle_coordinator_update)
    _handle_coordinator_update()


class BusTracker(CoordinatorEntity[SL528Coordinator], TrackerEntity):
    """Representerar ett enskilt fordon på linje 528."""

    _attr_icon = "mdi:bus"
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: SL528Coordinator, vehicle_id: str) -> None:
        super().__init__(coordinator)
        self._vehicle_id = vehicle_id
        self._attr_unique_id = f"sl_528_{vehicle_id}"

    @property
    def _data(self) -> dict | None:
        return self.coordinator.data.get(self._vehicle_id)

    @property
    def name(self) -> str:
        d = self._data
        if d:
            return f"528 {d.get('destination', '')}"
        return "528"

    @property
    def available(self) -> bool:
        return self._data is not None

    @property
    def latitude(self) -> float | None:
        d = self._data
        return d["latitude"] if d else None

    @property
    def longitude(self) -> float | None:
        d = self._data
        return d["longitude"] if d else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._data or {}
        speed_ms = d.get("speed_ms")
        return {
            "linje": "528",
            "destination": d.get("destination"),
            "fordon_id": d.get("vehicle_id"),
            "tur_id": d.get("trip_id"),
            "bearing": d.get("bearing"),
            "hastighet_kmh": round(speed_ms * 3.6, 1) if speed_ms else None,
            "hållplats_nr": d.get("current_stop_sequence"),
            "senast_uppdaterad": d.get("timestamp"),
        }

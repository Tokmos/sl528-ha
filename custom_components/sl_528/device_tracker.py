"""Device tracker – en entitet per buss på linje 528."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
    def _add_new_vehicles() -> None:
        new_entities = []
        for vehicle_id, data in coordinator.data.items():
            if vehicle_id not in known:
                known.add(vehicle_id)
                new_entities.append(BusTracker(coordinator, vehicle_id))
        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(_add_new_vehicles)
    _add_new_vehicles()


class BusTracker(CoordinatorEntity[SL528Coordinator], TrackerEntity):
    """Representerar ett enskilt fordon på linje 528."""

    _attr_icon = "mdi:bus"
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: SL528Coordinator, vehicle_id: str) -> None:
        super().__init__(coordinator)
        self._vehicle_id = vehicle_id
        label = coordinator.data.get(vehicle_id, {}).get("vehicle_label", vehicle_id)
        self._attr_unique_id = f"sl_528_{vehicle_id}"
        self._attr_name = f"Buss 528 – fordon {label}"

    @property
    def _data(self) -> dict | None:
        return self.coordinator.data.get(self._vehicle_id)

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
            "fordon_id": d.get("vehicle_id"),
            "tur_id": d.get("trip_id"),
            "bearing": d.get("bearing"),
            "hastighet_kmh": round(speed_ms * 3.6, 1) if speed_ms else None,
            "hållplats_nr": d.get("current_stop_sequence"),
            "senast_uppdaterad": d.get("timestamp"),
        }

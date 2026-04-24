"""Device tracker – en entitet per buss, tas bort när bussen slutar eller saknar position."""
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
from .coordinator import SLBusCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SLBusCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _handle_update() -> None:
        # Fordon som är aktiva OCH har giltiga koordinater
        active = {
            vid for vid, data in coordinator.data.items()
            if data.get("latitude") and data.get("longitude")
        }

        # Lägg till nya
        new_entities = []
        for vehicle_id in active:
            if vehicle_id not in known:
                known.add(vehicle_id)
                new_entities.append(BusTracker(coordinator, vehicle_id))
        if new_entities:
            async_add_entities(new_entities)

        # Ta bort fordon som försvunnit eller saknar position
        gone = known - active
        if gone:
            registry = er.async_get(hass)
            for vehicle_id in gone:
                known.discard(vehicle_id)
                unique_id = f"sl_bus_{coordinator.line}_{vehicle_id}"
                entity_id = registry.async_get_entity_id("device_tracker", DOMAIN, unique_id)
                if entity_id:
                    registry.async_remove(entity_id)
                    _LOGGER.debug("Tog bort fordon %s (%s)", vehicle_id, entity_id)

    coordinator.async_add_listener(_handle_update)
    _handle_update()


class BusTracker(CoordinatorEntity[SLBusCoordinator], TrackerEntity):
    _attr_icon = "mdi:bus"
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: SLBusCoordinator, vehicle_id: str) -> None:
        super().__init__(coordinator)
        self._vehicle_id = vehicle_id
        self._attr_unique_id = f"sl_bus_{coordinator.line}_{vehicle_id}"

    @property
    def _data(self) -> dict | None:
        d = self.coordinator.data.get(self._vehicle_id)
        # Returnera None om koordinater saknas
        if d and d.get("latitude") and d.get("longitude"):
            return d
        return None

    @property
    def name(self) -> str:
        d = self._data
        line = self.coordinator.line
        if d and d.get("destination"):
            return f"{line} {d['destination']}"
        return f"Linje {line}"

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
            "linje": d.get("line"),
            "destination": d.get("destination"),
            "fordon_id": d.get("vehicle_id"),
            "tur_id": d.get("trip_id"),
            "bearing": d.get("bearing"),
            "hastighet_kmh": round(speed_ms * 3.6, 1) if speed_ms else None,
            "hållplats_nr": d.get("current_stop_sequence"),
            "senast_uppdaterad": d.get("timestamp"),
        }

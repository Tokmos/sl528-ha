"""Device tracker – en entitet per fordon, ikon och namn baserat på linjetyp."""
from __future__ import annotations

import base64
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

def _svg_bus() -> str:
    return (
        '<rect x="7" y="7" width="36" height="20" rx="3" fill="white"/>'
        '<rect x="10" y="10" width="7" height="8" rx="1" fill="#0070BB"/>'
        '<rect x="21" y="10" width="7" height="8" rx="1" fill="#0070BB"/>'
        '<rect x="32" y="10" width="7" height="8" rx="1" fill="#0070BB"/>'
        '<circle cx="15" cy="30" r="5" fill="white"/>'
        '<circle cx="15" cy="30" r="2.5" fill="#0070BB"/>'
        '<circle cx="35" cy="30" r="5" fill="white"/>'
        '<circle cx="35" cy="30" r="2.5" fill="#0070BB"/>'
    )


def _svg_train() -> str:
    return (
        '<rect x="5" y="9" width="40" height="19" rx="3" fill="white"/>'
        # Pantograf
        '<line x1="18" y1="9" x2="16" y2="5" stroke="white" stroke-width="1.5"/>'
        '<line x1="16" y1="5" x2="34" y2="5" stroke="white" stroke-width="1.5"/>'
        '<line x1="34" y1="5" x2="32" y2="9" stroke="white" stroke-width="1.5"/>'
        '<rect x="8" y="12" width="9" height="9" rx="1" fill="#0070BB"/>'
        '<rect x="21" y="12" width="9" height="9" rx="1" fill="#0070BB"/>'
        '<rect x="33" y="12" width="8" height="9" rx="1" fill="#0070BB"/>'
        # Bogier
        '<rect x="9" y="27" width="8" height="4" rx="2" fill="white"/>'
        '<rect x="33" y="27" width="8" height="4" rx="2" fill="white"/>'
    )


def _svg_subway() -> str:
    return (
        # Mer rundad kropp (tunnelbanans karaktär)
        '<rect x="4" y="9" width="42" height="19" rx="8" fill="white"/>'
        '<rect x="8" y="12" width="10" height="10" rx="2" fill="#0070BB"/>'
        '<rect x="21" y="12" width="10" height="10" rx="2" fill="#0070BB"/>'
        '<rect x="34" y="12" width="8" height="10" rx="2" fill="#0070BB"/>'
        '<rect x="9" y="27" width="7" height="4" rx="2" fill="white"/>'
        '<rect x="34" y="27" width="7" height="4" rx="2" fill="white"/>'
    )


def _svg_tram() -> str:
    return (
        # Platt och bred spårvagnskropp
        '<rect x="4" y="10" width="42" height="17" rx="5" fill="white"/>'
        # Pantograf
        '<line x1="17" y1="10" x2="15" y2="6" stroke="white" stroke-width="1.5"/>'
        '<line x1="15" y1="6" x2="35" y2="6" stroke="white" stroke-width="1.5"/>'
        '<line x1="35" y1="6" x2="33" y2="10" stroke="white" stroke-width="1.5"/>'
        '<rect x="7" y="13" width="7" height="8" rx="1" fill="#0070BB"/>'
        '<rect x="17" y="13" width="7" height="8" rx="1" fill="#0070BB"/>'
        '<rect x="27" y="13" width="7" height="8" rx="1" fill="#0070BB"/>'
        '<rect x="37" y="13" width="5" height="8" rx="1" fill="#0070BB"/>'
        '<circle cx="13" cy="30" r="4" fill="white"/>'
        '<circle cx="13" cy="30" r="2" fill="#0070BB"/>'
        '<circle cx="37" cy="30" r="4" fill="white"/>'
        '<circle cx="37" cy="30" r="2" fill="#0070BB"/>'
    )


def _svg_ferry() -> str:
    return (
        # Kajuta
        '<rect x="11" y="7" width="28" height="14" rx="2" fill="white"/>'
        '<rect x="14" y="10" width="6" height="7" rx="1" fill="#0070BB"/>'
        '<rect x="23" y="10" width="6" height="7" rx="1" fill="#0070BB"/>'
        '<rect x="32" y="10" width="4" height="7" rx="1" fill="#0070BB"/>'
        # Mast
        '<rect x="22" y="3" width="3" height="5" fill="white"/>'
        # Skrov
        '<path d="M4,21 L6,29 Q25,35 44,29 L46,21 Z" fill="white"/>'
    )


def _badge_svg(line: str, route_type: str = "700") -> str:
    """Returnerar en base64-kodad SVG med trafikslagsanpassad ikon och linjenummer."""
    font_size = 13 if len(line) <= 3 else 10
    rt = int(route_type) if route_type.isdigit() else 700

    if 100 <= rt < 200:
        vehicle = _svg_train()
    elif 400 <= rt < 500:
        vehicle = _svg_subway()
    elif rt == 900:
        vehicle = _svg_tram()
    elif 1000 <= rt < 1100:
        vehicle = _svg_ferry()
    else:
        vehicle = _svg_bus()

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 50 56">'
        f'<rect x="0" y="0" width="50" height="50" rx="10" fill="#0070BB"/>'
        f'{vehicle}'
        f'<text x="25" y="44" text-anchor="middle" font-size="{font_size}" '
        f'font-family="Arial,sans-serif" font-weight="bold" fill="white">{line}</text>'
        f'</svg>'
    )
    b64 = base64.b64encode(svg.encode()).decode()
    return f"data:image/svg+xml;base64,{b64}"


# GTFS route_type -> MDI-ikon
def _icon_for_route_type(route_type: str) -> str:
    rt = int(route_type) if route_type.isdigit() else 700
    if rt in range(100, 200):   # Tåg
        return "mdi:train"
    if rt in range(200, 300):   # Långväga buss
        return "mdi:bus-articulated-front"
    if rt in range(400, 500):   # Tunnelbana
        return "mdi:subway"
    if rt in range(700, 800):   # Buss
        return "mdi:bus"
    if rt == 900:               # Spårvagn
        return "mdi:tram"
    if rt in range(1000, 1100): # Färja
        return "mdi:ferry"
    return "mdi:bus"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SLBusCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _handle_update() -> None:
        active = {
            vid for vid, data in coordinator.data.items()
            if data.get("latitude") and data.get("longitude")
        }

        new_entities = []
        for vehicle_id in active:
            if vehicle_id not in known:
                known.add(vehicle_id)
                new_entities.append(BusTracker(coordinator, vehicle_id))
        if new_entities:
            async_add_entities(new_entities)

        gone = known - active
        if gone:
            registry = er.async_get(hass)
            for vehicle_id in gone:
                known.discard(vehicle_id)
                unique_id = f"sl_bus_{coordinator.line}_{vehicle_id}"
                entity_id = registry.async_get_entity_id("device_tracker", DOMAIN, unique_id)
                if entity_id:
                    registry.async_remove(entity_id)
                    _LOGGER.debug("Tog bort fordon %s", vehicle_id)

    coordinator.async_add_listener(_handle_update)
    _handle_update()


class BusTracker(CoordinatorEntity[SLBusCoordinator], TrackerEntity):
    _attr_source_type = SourceType.GPS

    def __init__(self, coordinator: SLBusCoordinator, vehicle_id: str) -> None:
        super().__init__(coordinator)
        self._vehicle_id = vehicle_id
        self._attr_unique_id = f"sl_bus_{coordinator.line}_{vehicle_id}"
        self._attr_entity_picture = _badge_svg(coordinator.line, coordinator.route_type)

    @property
    def _data(self) -> dict | None:
        d = self.coordinator.data.get(self._vehicle_id)
        if d and d.get("latitude") and d.get("longitude"):
            return d
        return None

    @property
    def icon(self) -> str:
        return _icon_for_route_type(self.coordinator.route_type)

    @property
    def name(self) -> str:
        """Linjenummer + destination – visas som etikett på kartan."""
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

"""DataUpdateCoordinator – hämtar och avkodar GTFS-RT VehiclePositions för SL."""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from google.transit import gtfs_realtime_pb2

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, GTFS_RT_URL, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

TARGET_LINE = "528"


class SL528Coordinator(DataUpdateCoordinator):
    """Hämtar GPS-positioner för buss 528 från Trafiklab var 15:e sekund."""

    def __init__(self, hass: HomeAssistant, api_key: str) -> None:
        self.api_key = api_key
        self.url = GTFS_RT_URL.format(api_key=api_key)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )

    async def _async_update_data(self) -> dict[str, dict]:
        """Hämta och filtrera fordonspositioner. Returnerar dict keyed på vehicle_id."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 401:
                        raise UpdateFailed("Ogiltig API-nyckel (401)")
                    if resp.status != 200:
                        raise UpdateFailed(f"HTTP {resp.status} från Trafiklab")
                    raw = await resp.read()
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Nätverksfel: {err}") from err

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(raw)

        vehicles: dict[str, dict] = {}
        for entity in feed.entity:
            if not entity.HasField("vehicle"):
                continue
            vp = entity.vehicle

            # Filtrera på linje 528
            route_id = vp.trip.route_id if vp.HasField("trip") else ""
            short_name = vp.trip.route_id  # GTFS-RT för SL har route_id = linjenummer
            descriptor_label = ""
            if hasattr(vp, "trip") and vp.trip.route_id:
                descriptor_label = vp.trip.route_id

            # SL:s GTFS route_id är vanligtvis på formatet "1:528" eller bara "528"
            if TARGET_LINE not in descriptor_label:
                continue

            if not (vp.position.latitude and vp.position.longitude):
                continue

            vehicle_id = vp.vehicle.id or vp.vehicle.label or entity.id
            trip_id = vp.trip.trip_id if vp.HasField("trip") else ""

            vehicles[vehicle_id] = {
                "latitude": vp.position.latitude,
                "longitude": vp.position.longitude,
                "bearing": vp.position.bearing if vp.position.bearing else None,
                "speed_ms": vp.position.speed if vp.position.speed else None,
                "vehicle_id": vehicle_id,
                "vehicle_label": vp.vehicle.label or vehicle_id,
                "trip_id": trip_id,
                "route_id": descriptor_label,
                "current_stop_sequence": vp.current_stop_sequence or None,
                "timestamp": vp.timestamp or None,
            }

        _LOGGER.debug("Hittade %d fordon på linje 528", len(vehicles))
        return vehicles

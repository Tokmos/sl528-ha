"""DataUpdateCoordinator – hämtar GTFS-RT VehiclePositions för SL linje 528."""
from __future__ import annotations

import io
import csv
import logging
import zipfile
from datetime import timedelta

import aiohttp
from google.transit import gtfs_realtime_pb2

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, GTFS_RT_URL, GTFS_STATIC_URL, ROUTE_ID_528, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

DIRECTION_NAMES = {
    "0": "→ Sollentuna station",
    "1": "→ Helenelunds station",
}


class SL528Coordinator(DataUpdateCoordinator):
    """Hämtar GPS-positioner för buss 528 från Trafiklab var 15:e sekund."""

    def __init__(self, hass: HomeAssistant, rt_key: str, static_key: str) -> None:
        self.rt_key = rt_key
        self.static_key = static_key
        self.rt_url = GTFS_RT_URL.format(rt_key=rt_key)
        self.static_url = GTFS_STATIC_URL.format(static_key=static_key)
        self._trip_ids_528: dict[str, str] = {}  # trip_id -> direction_id
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )

    async def async_load_trip_ids(self) -> None:
        """Ladda trips.txt och bygg dict med trip_id -> direction_id för linje 528."""
        _LOGGER.debug("Hämtar GTFS statisk data...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.static_url, timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status != 200:
                        raise UpdateFailed(f"HTTP {resp.status} vid hämtning av statisk data")
                    raw = await resp.read()

            def parse_trips(data: bytes) -> dict[str, str]:
                trips = {}
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    with z.open("trips.txt") as f:
                        reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
                        for row in reader:
                            if row.get("route_id") == ROUTE_ID_528:
                                trips[row["trip_id"]] = row.get("direction_id", "0")
                return trips

            self._trip_ids_528 = await self.hass.async_add_executor_job(parse_trips, raw)
            _LOGGER.info("Hittade %d trip_ids för linje 528", len(self._trip_ids_528))

        except Exception as err:
            _LOGGER.error("Fel vid hämtning av GTFS statisk data: %s", err)
            raise UpdateFailed(f"Kunde inte ladda trip_ids: {err}") from err

    async def _async_update_data(self) -> dict[str, dict]:
        """Hämta och filtrera fordonspositioner."""
        if not self._trip_ids_528:
            await self.async_load_trip_ids()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.rt_url, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 401:
                        raise UpdateFailed("Ogiltig realtids-API-nyckel (401)")
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
            trip_id = vp.trip.trip_id if vp.HasField("trip") else ""

            if trip_id not in self._trip_ids_528:
                continue
            if not (vp.position.latitude and vp.position.longitude):
                continue

            vehicle_id = vp.vehicle.id or entity.id
            direction_id = self._trip_ids_528[trip_id]
            destination = DIRECTION_NAMES.get(direction_id, "Linje 528")
            speed_ms = vp.position.speed if vp.position.speed else None

            vehicles[vehicle_id] = {
                "latitude": vp.position.latitude,
                "longitude": vp.position.longitude,
                "bearing": vp.position.bearing or None,
                "speed_ms": speed_ms,
                "vehicle_id": vehicle_id,
                "vehicle_label": vp.vehicle.label or vehicle_id,
                "trip_id": trip_id,
                "direction_id": direction_id,
                "destination": destination,
                "current_stop_sequence": vp.current_stop_sequence or None,
                "timestamp": vp.timestamp or None,
            }

        _LOGGER.debug("Hittade %d fordon på linje 528", len(vehicles))
        return vehicles

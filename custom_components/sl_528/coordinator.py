"""DataUpdateCoordinator för SL-bussar med dynamisk linjekonfiguration."""
from __future__ import annotations

import io
import csv
import logging
import zipfile
from datetime import datetime, timedelta

import aiohttp
from google.transit import gtfs_realtime_pb2

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_track_time_change

from .const import (
    DOMAIN,
    GTFS_RT_URL,
    GTFS_STATIC_URL,
    SL_TRANSPORT_API,
    SCAN_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


class SLBusCoordinator(DataUpdateCoordinator):
    """Hämtar GPS-positioner för en valfri SL-busslinje."""

    def __init__(self, hass: HomeAssistant, rt_key: str, static_key: str, line: str) -> None:
        self.rt_key = rt_key
        self.static_key = static_key
        self.line = line
        self.rt_url = GTFS_RT_URL.format(rt_key=rt_key)
        self.static_url = GTFS_STATIC_URL.format(static_key=static_key)

        # Cache
        self._route_id: str | None = None
        self._trip_ids: dict[str, str] = {}   # trip_id -> direction_id
        self._direction_names: dict[str, str] = {}  # direction_id -> destination name
        self._trips_loaded_at: datetime | None = None
        self._cancel_nightly: callable | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{line}",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )

    async def async_setup(self) -> None:
        """Ladda initial data och schemalägg nattlig uppdatering."""
        await self._load_all_static_data()

        # Uppdatera trips.txt varje natt kl 03:00
        self._cancel_nightly = async_track_time_change(
            self.hass,
            self._nightly_refresh,
            hour=3, minute=0, second=0
        )

    async def _nightly_refresh(self, now) -> None:
        _LOGGER.info("Nattlig uppdatering av GTFS-data för linje %s", self.line)
        await self._load_all_static_data()

    def async_unload(self) -> None:
        if self._cancel_nightly:
            self._cancel_nightly()

    async def _load_all_static_data(self) -> None:
        """Hämta route_id, trip_ids och ändstationer."""
        try:
            await self._load_route_id()
            if self._route_id:
                await self._load_trips()
                await self._load_direction_names()
        except Exception as err:
            _LOGGER.error("Fel vid laddning av statisk data: %s", err)

    async def _load_route_id(self) -> None:
        """Slå upp route_id för linjen via Transport API."""
        url = f"{SL_TRANSPORT_API}/lines?transport_authority_id=1"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("Kunde inte hämta linjer: HTTP %s", resp.status)
                        return
                    lines = await resp.json()

            for line in lines:
                if str(line.get("designation", "")) == self.line or str(line.get("name", "")) == self.line:
                    # Transport API ger inte route_id direkt – bygg det från GTFS-format
                    # Faller tillbaka på trips.txt för kopplingen
                    self._route_id = str(line.get("id", ""))
                    _LOGGER.debug("Hittade linje %s med id %s", self.line, self._route_id)
                    return

            _LOGGER.warning("Hittade inte linje %s i Transport API", self.line)
        except Exception as err:
            _LOGGER.error("Fel vid hämtning av route_id: %s", err)

    async def _load_trips(self) -> None:
        """Ladda trips.txt och bygg trip_id -> direction_id för aktuell linje."""
        _LOGGER.debug("Hämtar GTFS statisk data (trips.txt)...")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.static_url, timeout=aiohttp.ClientTimeout(total=120)
                ) as resp:
                    if resp.status != 200:
                        raise UpdateFailed(f"HTTP {resp.status} vid hämtning av statisk data")
                    raw = await resp.read()

            line_number = self.line

            def parse(data: bytes) -> dict[str, str]:
                trips = {}
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    # Läs routes.txt för att hitta route_id baserat på linjenummer
                    route_id = None
                    with z.open("routes.txt") as f:
                        for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
                            name = row.get("route_short_name", "") or row.get("route_long_name", "")
                            if name == line_number:
                                route_id = row["route_id"]
                                break

                    if not route_id:
                        _LOGGER.warning("Hittade ingen route_id för linje %s i routes.txt", line_number)
                        return {}

                    _LOGGER.debug("route_id för linje %s: %s", line_number, route_id)

                    # Läs trips.txt
                    with z.open("trips.txt") as f:
                        for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
                            if row.get("route_id") == route_id:
                                trips[row["trip_id"]] = row.get("direction_id", "0")

                return trips

            self._trip_ids = await self.hass.async_add_executor_job(parse, raw)
            self._trips_loaded_at = datetime.now()
            _LOGGER.info("Laddade %d trip_ids för linje %s", len(self._trip_ids), self.line)

        except Exception as err:
            _LOGGER.error("Fel vid laddning av trips: %s", err)

    async def _load_direction_names(self) -> None:
        """Hämta ändstationer per riktning via Transport API."""
        try:
            # Hitta line_id via Transport API
            url = f"{SL_TRANSPORT_API}/lines?transport_authority_id=1"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return
                    lines = await resp.json()

            line_id = None
            for line in lines:
                if str(line.get("designation", "")) == self.line:
                    line_id = line.get("id")
                    break

            if not line_id:
                self._direction_names = {"0": f"Linje {self.line}", "1": f"Linje {self.line}"}
                return

            # Hämta hållplatser för linjen
            url = f"{SL_TRANSPORT_API}/lines/{line_id}/stop-points"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return
                    stop_points = await resp.json()

            # Gruppera per direction och ta första/sista
            stops_by_dir: dict[str, list] = {}
            for sp in stop_points:
                d = str(sp.get("direction_id", sp.get("direction", "0")))
                stops_by_dir.setdefault(d, []).append(sp)

            direction_names = {}
            for direction, stops in stops_by_dir.items():
                if stops:
                    last = stops[-1]
                    name = last.get("name") or last.get("stop_area_name") or f"Linje {self.line}"
                    direction_names[direction] = f"→ {name}"

            if direction_names:
                self._direction_names = direction_names
                _LOGGER.debug("Ändstationer för linje %s: %s", self.line, direction_names)
            else:
                self._direction_names = {"0": f"Linje {self.line}", "1": f"Linje {self.line}"}

        except Exception as err:
            _LOGGER.warning("Kunde inte hämta ändstationer: %s", err)
            self._direction_names = {"0": f"Linje {self.line}", "1": f"Linje {self.line}"}

    async def _async_update_data(self) -> dict[str, dict]:
        """Hämta och filtrera fordonspositioner."""
        if not self._trip_ids:
            await self._load_trips()
            await self._load_direction_names()

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

            if trip_id not in self._trip_ids:
                continue
            if not (vp.position.latitude and vp.position.longitude):
                continue

            vehicle_id = vp.vehicle.id or entity.id
            direction_id = self._trip_ids[trip_id]
            destination = self._direction_names.get(direction_id, f"Linje {self.line}")
            speed_ms = vp.position.speed if vp.position.speed else None

            vehicles[vehicle_id] = {
                "latitude": vp.position.latitude,
                "longitude": vp.position.longitude,
                "bearing": vp.position.bearing or None,
                "speed_ms": speed_ms,
                "vehicle_id": vehicle_id,
                "trip_id": trip_id,
                "direction_id": direction_id,
                "destination": destination,
                "line": self.line,
                "current_stop_sequence": vp.current_stop_sequence or None,
                "timestamp": vp.timestamp or None,
            }

        _LOGGER.debug("Hittade %d fordon på linje %s", len(vehicles), self.line)
        return vehicles

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

SLEEP_INTERVAL = timedelta(minutes=5)   # Ingen trafik – kolla igen om 5 min
ACTIVE_INTERVAL = timedelta(seconds=SCAN_INTERVAL_SECONDS)  # Trafik – kolla var 15:e sek
NO_TRAFFIC_WINDOW = 60  # Minuter utan avgångar = ingen trafik


class SLBusCoordinator(DataUpdateCoordinator):
    """Hämtar GPS-positioner för en valfri SL-busslinje."""

    def __init__(self, hass: HomeAssistant, rt_key: str, static_key: str, line: str) -> None:
        self.rt_key = rt_key
        self.static_key = static_key
        self.line = line
        self.rt_url = GTFS_RT_URL.format(rt_key=rt_key)
        self.static_url = GTFS_STATIC_URL.format(static_key=static_key)

        self._route_id: str | None = None
        self._trip_ids: dict[str, str] = {}
        self._direction_names: dict[str, str] = {}
        self._trips_loaded_at: datetime | None = None
        self._cancel_nightly: callable | None = None
        self._traffic_active: bool = True
        self._sample_site_id: int | None = None  # En hållplats på linjen för trafikcheck

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{line}",
            update_interval=ACTIVE_INTERVAL,
        )

    async def async_setup(self) -> None:
        await self._load_all_static_data()
        self._cancel_nightly = async_track_time_change(
            self.hass, self._nightly_refresh, hour=3, minute=0, second=0
        )

    async def _nightly_refresh(self, now) -> None:
        _LOGGER.info("Nattlig uppdatering av GTFS-data för linje %s", self.line)
        await self._load_all_static_data()

    def async_unload(self) -> None:
        if self._cancel_nightly:
            self._cancel_nightly()

    async def _load_all_static_data(self) -> None:
        try:
            await self._load_trips()
            await self._load_direction_names()
        except Exception as err:
            _LOGGER.error("Fel vid laddning av statisk data: %s", err)

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
                    route_id = None
                    with z.open("routes.txt") as f:
                        for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
                            name = row.get("route_short_name", "") or row.get("route_long_name", "")
                            if name == line_number:
                                route_id = row["route_id"]
                                break

                    if not route_id:
                        _LOGGER.warning("Hittade ingen route_id för linje %s", line_number)
                        return {}

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
        """Hämta ändstationer och en sample-hållplats via Transport API."""
        try:
            url = f"{SL_TRANSPORT_API}/lines?transport_authority_id=1"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return
                    lines = await resp.json()

            line_id = None
            for line in lines:
                if not isinstance(line, dict):
                    continue
                if str(line.get("designation", "")) == self.line:
                    line_id = line.get("id")
                    break

            if not line_id:
                self._direction_names = {"0": f"Linje {self.line}", "1": f"Linje {self.line}"}
                return

            url = f"{SL_TRANSPORT_API}/lines/{line_id}/stop-points"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return
                    stop_points = await resp.json()

            stops_by_dir: dict[str, list] = {}
            for sp in stop_points:
                if not isinstance(sp, dict):
                    continue
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
            else:
                self._direction_names = {"0": f"Linje {self.line}", "1": f"Linje {self.line}"}

            # Spara en hållplats att använda för trafikcheck
            all_stops = [sp for stops in stops_by_dir.values() for sp in stops]
            mid = all_stops[len(all_stops) // 2] if all_stops else None
            if mid and isinstance(mid, dict):
                self._sample_site_id = mid.get("site_id") or mid.get("id")
                _LOGGER.debug("Sample-hållplats för trafikcheck: %s", self._sample_site_id)

        except Exception as err:
            _LOGGER.warning("Kunde inte hämta ändstationer: %s", err)
            self._direction_names = {"0": f"Linje {self.line}", "1": f"Linje {self.line}"}

    async def _is_traffic_active(self) -> bool:
        """Kolla om det finns avgångar för linjen inom de närmaste 60 minuterna."""
        if not self._sample_site_id:
            return True  # Vet inte – anta att trafik pågår

        try:
            url = f"{SL_TRANSPORT_API}/sites/{self._sample_site_id}/departures"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return True
                    data = await resp.json()

            departures = data.get("departures", data) if isinstance(data, dict) else data
            now = datetime.now().astimezone()

            for dep in departures:
                if not isinstance(dep, dict):
                    continue
                line = dep.get("line", {})
                if not isinstance(line, dict):
                    continue
                if str(line.get("designation", "")) != self.line:
                    continue

                # Kolla om avgången är inom 60 minuter
                time_str = dep.get("expected") or dep.get("scheduled")
                if not time_str:
                    return True
                try:
                    from datetime import timezone
                    dep_time = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                    diff_minutes = (dep_time - now).total_seconds() / 60
                    if -5 <= diff_minutes <= NO_TRAFFIC_WINDOW:
                        return True
                except Exception:
                    return True

            return False

        except Exception as err:
            _LOGGER.debug("Kunde inte kolla trafik: %s", err)
            return True  # Vid fel – anta trafik pågår

    async def _async_update_data(self) -> dict[str, dict]:
        """Hämta fordonspositioner om trafik är aktiv, annars sov."""
        if not self._trip_ids:
            await self._load_trips()
            await self._load_direction_names()

        # Kolla om trafik pågår
        traffic_active = await self._is_traffic_active()

        if not traffic_active:
            if self._traffic_active:
                _LOGGER.info("Linje %s: ingen trafik – minskar pollingsfrekvens", self.line)
            self._traffic_active = False
            self.update_interval = SLEEP_INTERVAL
            return {}

        if not self._traffic_active:
            _LOGGER.info("Linje %s: trafik återupptagen – ökar pollingsfrekvens", self.line)
        self._traffic_active = True
        self.update_interval = ACTIVE_INTERVAL

        # Hämta realtidsdata
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

"""Config flow + Options flow för SL-busslinje integration."""
from __future__ import annotations

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, GTFS_RT_URL, DEFAULT_LINE, CONF_MAP_LAT, CONF_MAP_LON, CONF_MAP_ZOOM, DEFAULT_MAP_ZOOM

STEP_SCHEMA = vol.Schema({
    vol.Required("rt_key"): str,
    vol.Required("static_key"): str,
    vol.Required("line", default=DEFAULT_LINE): str,
})


async def _validate_rt_key(hass: HomeAssistant, rt_key: str) -> str | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GTFS_RT_URL.format(rt_key=rt_key),
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 401:
                    return "invalid_auth"
                if resp.status not in (200, 304):
                    return "cannot_connect"
    except aiohttp.ClientError:
        return "cannot_connect"
    return None


class SLBusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Konfigureringsflöde för SL-busslinje."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            error = await _validate_rt_key(self.hass, user_input["rt_key"])
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"SL Busslinje {user_input['line']}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SLBusOptionsFlow()


class SLBusOptionsFlow(config_entries.OptionsFlow):
    """Options flow – byt linje och kartinställningar utan att installera om."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title=f"SL Busslinje {user_input['line']}",
                data=user_input,
            )

        opts = self.config_entry.options
        data = self.config_entry.data

        current_line = opts.get("line", data.get("line", DEFAULT_LINE))
        current_lat  = opts.get(CONF_MAP_LAT,  data.get(CONF_MAP_LAT,  self._get_home_lat()))
        current_lon  = opts.get(CONF_MAP_LON,  data.get(CONF_MAP_LON,  self._get_home_lon()))
        current_zoom = opts.get(CONF_MAP_ZOOM, data.get(CONF_MAP_ZOOM, DEFAULT_MAP_ZOOM))

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("line", default=current_line): str,
                vol.Optional(CONF_MAP_LAT,  default=current_lat):  vol.Coerce(float),
                vol.Optional(CONF_MAP_LON,  default=current_lon):  vol.Coerce(float),
                vol.Optional(CONF_MAP_ZOOM, default=current_zoom): vol.All(int, vol.Range(min=1, max=20)),
            }),
        )

    def _get_home_lat(self) -> float:
        return self.hass.config.latitude or 59.3293

    def _get_home_lon(self) -> float:
        return self.hass.config.longitude or 18.0686

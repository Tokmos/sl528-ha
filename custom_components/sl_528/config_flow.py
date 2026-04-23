"""Config flow – lägg till SL 528 via UI."""
from __future__ import annotations

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .const import DOMAIN, GTFS_RT_URL, GTFS_STATIC_URL

STEP_SCHEMA = vol.Schema({
    vol.Required("rt_key"): str,
    vol.Required("static_key"): str,
})


async def _validate_keys(hass: HomeAssistant, rt_key: str, static_key: str) -> str | None:
    """Returnerar None om OK, annars en error-sträng."""
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


class SL528ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()

            error = await _validate_keys(
                self.hass,
                user_input["rt_key"],
                user_input["static_key"]
            )
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title="SL Busslinje 528 GPS",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_SCHEMA,
            errors=errors,
        )

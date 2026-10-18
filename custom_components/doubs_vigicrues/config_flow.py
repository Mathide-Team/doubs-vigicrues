"""Configuration : choix d'une station Vigicrues."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DoubsVigicruesApiError, DoubsVigicruesStationError, HubeauClient
from .const import CONF_STATION, DEFAULT_STATION, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_STATION, default=DEFAULT_STATION): str,
    }
)


class DoubsVigicruesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Étapes de configuration : une entrée par station."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Demande le code de la station et le valide auprès du référentiel."""
        erreurs: dict[str, str] = {}
        if user_input is not None:
            code = user_input[CONF_STATION].strip()
            await self.async_set_unique_id(code)
            self._abort_if_unique_id_configured()
            try:
                client = HubeauClient(async_get_clientsession(self.hass))
                station = await client.async_get_station(code)
            except DoubsVigicruesStationError:
                erreurs[CONF_STATION] = "station_inconnue"
            except DoubsVigicruesApiError:
                erreurs["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=station.libelle, data={CONF_STATION: code})
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=erreurs,
        )

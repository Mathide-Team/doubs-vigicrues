"""Intégration « Niveau du Doubs (Vigicrues) » : hauteur et débit d'une station."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HubeauClient
from .coordinator import DoubsVigicruesCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type DoubsVigicruesConfigEntry = ConfigEntry[DoubsVigicruesCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: DoubsVigicruesConfigEntry) -> bool:
    """Prépare le coordinateur et les entités de la station.

    Un échec de la première mise à jour laisse Home Assistant retenter
    plus tard : l'entrée reste en « configuration non terminée ».
    """
    client = HubeauClient(async_get_clientsession(hass))
    coordinator = DoubsVigicruesCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DoubsVigicruesConfigEntry) -> bool:
    """Décharge les entités de l'entrée."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

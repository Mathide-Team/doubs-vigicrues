"""Coordonnateur : une station, sa hauteur et son débit."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DoubsVigicruesApiError, DoubsVigicruesError, Observation, Station
from .const import GRANDEUR_DEBIT, GRANDEUR_HAUTEUR, LOGGER, UPDATE_INTERVAL_MIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .api import HubeauClient


class StationData:
    """Données consolidées d'une station à une mise à jour donnée."""

    def __init__(
        self,
        station: Station,
        hauteur: Observation | None,
        debit: Observation | None,
    ) -> None:
        self.station = station
        self.hauteur = hauteur
        self.debit = debit


class DoubsVigicruesCoordinator(DataUpdateCoordinator[StationData]):
    """Interroge Hub'Eau toutes les 15 minutes.

    La hauteur et le débit sont récupérés séparément : une grandeur
    absente (pas de capteur de débit sur la station) laisse l'autre
    disponible.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: HubeauClient,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=entry.title,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MIN),
        )
        self._client = client
        self._code = entry.data["station"]

    @property
    def code(self) -> str:
        """Code de la station suivie."""
        return self._code

    async def _async_update_data(self) -> StationData:
        """Récupère la station puis ses dernières observations.

        La hauteur et le débit sont indépendants : un échec du débit
        (grandeur facultative) n'empêche pas la mise à jour de la
        hauteur — l'erreur est journalisée et le capteur reste sans
        valeur.
        """
        try:
            station = await self._client.async_get_station(self._code)
            hauteur = await self._client.async_get_observation(self._code, GRANDEUR_HAUTEUR)
        except DoubsVigicruesApiError as erreur:
            msg = f"Mise à jour impossible : {erreur}"
            raise UpdateFailed(msg) from erreur
        except DoubsVigicruesError as erreur:  # pragma: no cover - station supprimée
            msg = f"Station {self._code} devenue introuvable : {erreur}"
            raise UpdateFailed(msg) from erreur
        try:
            debit = await self._client.async_get_observation(self._code, GRANDEUR_DEBIT)
        except DoubsVigicruesError as erreur:
            LOGGER.warning("Débit indisponible pour %s : %s", self._code, erreur)
            debit = None
        return StationData(station=station, hauteur=hauteur, debit=debit)

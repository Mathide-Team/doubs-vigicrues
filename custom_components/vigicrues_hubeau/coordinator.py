"""Coordonnateur : une station, sa hauteur et son débit."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import Observation, Station, VigicruesError
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


class VigicruesCoordinator(DataUpdateCoordinator[StationData]):
    """Interroge Hub'Eau toutes les 15 minutes pour une station.

    Chaque station suivie possède son coordinateur : l'échec d'une
    station ne rend pas les autres indisponibles. La hauteur et le débit
    sont récupérés séparément : une grandeur absente (pas de capteur de
    débit sur la station) laisse l'autre disponible.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: HubeauClient,
        station: Station,
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=station.libelle,
            config_entry=entry,
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MIN),
        )
        self._client = client
        self.station = station

    @property
    def code(self) -> str:
        """Code de la station suivie."""
        return self.station.code

    async def _async_update_data(self) -> StationData:
        """Récupère les dernières observations de la station.

        Les métadonnées (libellé, commune, coordonnées) sont lues à la
        configuration et ne sont pas re-téléchargées à chaque cycle.

        La hauteur et le débit sont indépendants et symétriques : une
        grandeur en échec (ou absente de la station) laisse l'autre
        disponible, avec un avertissement. L'échec des deux seules
        fait échouer la mise à jour de la station.
        """
        hauteur: Observation | None = None
        debit: Observation | None = None
        erreur_hauteur: VigicruesError | None = None
        erreur_debit: VigicruesError | None = None
        try:
            hauteur = await self._client.async_get_observation(self.code, GRANDEUR_HAUTEUR)
        except VigicruesError as erreur:
            erreur_hauteur = erreur
        try:
            debit = await self._client.async_get_observation(self.code, GRANDEUR_DEBIT)
        except VigicruesError as erreur:
            erreur_debit = erreur
        if erreur_hauteur is not None and erreur_debit is not None:
            msg = f"Mise à jour impossible : {erreur_hauteur}"
            raise UpdateFailed(msg) from erreur_hauteur
        if erreur_hauteur is not None:
            LOGGER.warning("Hauteur indisponible pour %s : %s", self.code, erreur_hauteur)
        if erreur_debit is not None:
            LOGGER.warning("Débit indisponible pour %s : %s", self.code, erreur_debit)
        return StationData(station=self.station, hauteur=hauteur, debit=debit)

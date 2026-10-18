"""Client de l'API Hub'Eau (hydrométrie Vigicrues).

Contrat vérifié sur l'API v2 (https://hubeau.eaufrance.fr/page/api-hydrometrie) :
- ``referentiel/stations?code_station=...`` : métadonnées d'une station ;
- ``observations_tr?code_entite=...&grandeur_hydro=H|Q&sort=desc&size=1`` :
  dernière observation temps réel. ``resultat_obs`` est exprimé en
  millimètres pour la hauteur (H) et en litres par seconde pour le débit
  (Q) — division par 1000 pour obtenir des mètres et des m³/s ;
- ``date_obs`` est en UTC (suffixe ``Z``) ;
- le tri par défaut est décroissant sur ``date_obs``.

Une valeur nulle (absence de mesure) n'est pas un zéro : ``None`` est
retourné. Inversement, zéro ou une valeur négative est une mesure valable
et est conservée telle quelle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

BASE_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie"


class DoubsVigicruesError(Exception):
    """Erreur de base de l'intégration."""


class DoubsVigicruesApiError(DoubsVigicruesError):
    """L'API Hub'Eau est injoignable ou a renvoyé une réponse invalide."""


class DoubsVigicruesStationError(DoubsVigicruesError):
    """La station demandée est introuvable dans le référentiel."""


@dataclass(frozen=True)
class Station:
    """Métadonnées d'une station hydrométrique (référentiel Hub'Eau)."""

    code: str
    libelle: str
    commune: str | None
    departement: str | None
    cours_eau: str | None
    altitude: float | None
    longitude: float | None
    latitude: float | None


@dataclass(frozen=True)
class Observation:
    """Dernière observation temps réel d'une grandeur (H ou Q)."""

    code_station: str
    grandeur: str
    date_obs: datetime  # UTC
    resultat: float  # mm pour H, l/s pour Q
    continuite: str | None


def _parse_station(enregistrement: dict[str, Any]) -> Station:
    """Construit une Station depuis le référentiel Hub'Eau."""
    return Station(
        code=enregistrement["code_station"],
        libelle=enregistrement["libelle_station"],
        commune=enregistrement.get("libelle_commune"),
        departement=enregistrement.get("libelle_departement"),
        cours_eau=enregistrement.get("libelle_cours_eau"),
        altitude=enregistrement.get("altitude_ref_alti_station"),
        longitude=enregistrement.get("longitude_station"),
        latitude=enregistrement.get("latitude_station"),
    )


def _parse_observation(enregistrement: dict[str, Any], grandeur: str) -> Observation | None:
    """Construit une Observation depuis observations_tr.

    ``date_obs`` arrive en UTC (suffixe ``Z``) et est conservée en UTC :
    la conversion vers l'heure locale se fait à l'affichage. Un
    enregistrement sans valeur (``resultat_obs`` nul) n'est pas une
    mesure : ``None`` est retourné.
    """
    if enregistrement.get("resultat_obs") is None:
        return None
    try:
        date_obs = datetime.fromisoformat(enregistrement["date_obs"])
    except (KeyError, ValueError) as erreur:
        msg = "Horodatage illisible dans la réponse Hub'Eau"
        raise DoubsVigicruesApiError(msg) from erreur
    if date_obs.tzinfo is None:
        date_obs = date_obs.replace(tzinfo=UTC)
    return Observation(
        code_station=enregistrement["code_station"],
        grandeur=grandeur,
        date_obs=date_obs,
        resultat=float(enregistrement["resultat_obs"]),
        continuite=enregistrement.get("libelle_continuite"),
    )


class HubeauClient:
    """Client en lecture seule de l'API Hub'Eau (URL injectable pour les tests)."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str | None = None,
    ) -> None:
        self._session = session
        # Lue à l'instanciation : les tests peuvent surcharger api.BASE_URL.
        self._base_url = (base_url or BASE_URL).rstrip("/")

    async def _async_get_json(self, chemin: str, params: dict[str, str]) -> Any:
        """GET protégé : réseau, HTTP et JSON validés."""
        url = f"{self._base_url}/{chemin}"
        try:
            async with self._session.get(url, params=params) as response:
                response.raise_for_status()
                return await response.json()
        except ClientResponseError as erreur:
            msg = f"Hub'Eau a répondu {erreur.status} pour {chemin}"
            raise DoubsVigicruesApiError(msg) from erreur
        except (ClientError, TimeoutError) as erreur:
            msg = f"Hub'Eau est injoignable ({chemin})"
            raise DoubsVigicruesApiError(msg) from erreur
        except ValueError as erreur:
            msg = f"Réponse illisible de Hub'Eau ({chemin})"
            raise DoubsVigicruesApiError(msg) from erreur

    async def async_get_station(self, code: str) -> Station:
        """Métadonnées d'une station ; erreur dédiée si introuvable.

        Le référentiel accepte des motifs de recherche : si la réponse
        ne désigne pas exactement le code demandé, la saisie est
        ambiguë plutôt que de prendre la première station trouvée.
        """
        donnees = await self._async_get_json("referentiel/stations", {"code_station": code, "format": "json"})
        enregistrements = donnees.get("data") or []
        if not enregistrements:
            msg = f"Station {code} introuvable dans le référentiel Hub'Eau"
            raise DoubsVigicruesStationError(msg)
        if enregistrements[0].get("code_station") != code:
            msg = f"Le code {code} correspond à plusieurs stations : indiquez un code exact"
            raise DoubsVigicruesStationError(msg)
        return _parse_station(enregistrements[0])

    async def async_get_observation(self, code: str, grandeur: str) -> Observation | None:
        """Dernière observation d'une grandeur, ou None si aucune mesure.

        La requête demande le tri décroissant et une seule valeur : la
        première réponse est la plus récente. Une absence de mesure
        n'est pas une erreur.
        """
        donnees = await self._async_get_json(
            "observations_tr",
            {
                "code_entite": code,
                "grandeur_hydro": grandeur,
                "sort": "desc",
                "size": "1",
                "format": "json",
            },
        )
        enregistrements = donnees.get("data") or []
        if not enregistrements:
            return None
        return _parse_observation(enregistrements[0], grandeur)

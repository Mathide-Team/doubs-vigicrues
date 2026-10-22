"""Client de l'API Hub'Eau (hydrométrie Vigicrues).

Contrat vérifié sur l'API v2 (https://hubeau.eaufrance.fr/page/api-hydrometrie) :
- ``referentiel/stations`` : métadonnées de stations. Le paramètre
  ``code_station`` accepte plusieurs codes (paramètre répété) et des
  motifs de recherche — un code exact désigne une seule station. La
  recherche libre se fait par ``libelle_cours_eau`` (nom du cours
  d'eau, partiel accepté) ou ``code_commune_station`` (code INSEE) ;
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

from aiohttp import ClientError, ClientResponseError, ClientSession, ContentTypeError

from .const import LOGGER

BASE_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie"

# Bornes raisonnables pour une recherche interactive.
TAILLE_RECHERCHE_MAX = 50


class VigicruesError(Exception):
    """Erreur de base de l'intégration."""


class VigicruesApiError(VigicruesError):
    """L'API Hub'Eau est injoignable ou a renvoyé une réponse invalide."""


class VigicruesStationError(VigicruesError):
    """Une ou plusieurs stations demandées sont introuvables ou ambiguës."""


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
    LOGGER.debug(
        "_parse_observation() appelée | code=%s grandeur=%s",
        enregistrement.get("code_station"),
        grandeur,
    )
    if enregistrement.get("resultat_obs") is None:
        LOGGER.debug("_parse_observation() retourne None (aucune mesure)")
        return None
    try:
        date_obs = datetime.fromisoformat(enregistrement["date_obs"])
    except (KeyError, ValueError) as erreur:
        msg = "Horodatage illisible dans la réponse Hub'Eau"
        LOGGER.debug("horodatage illisible dans la réponse Hub'Eau : %s", erreur)
        raise VigicruesApiError(msg) from erreur
    if date_obs.tzinfo is None:
        date_obs = date_obs.replace(tzinfo=UTC)
    LOGGER.debug("_parse_observation() retourne une observation (%s)", grandeur)
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
        LOGGER.debug("HubeauClient.__init__() appelé | url=%s", base_url or BASE_URL)
        self._session = session
        # Lue à l'instanciation : les tests peuvent surcharger api.BASE_URL.
        self._base_url = (base_url or BASE_URL).rstrip("/")
        LOGGER.debug("HubeauClient.__init__() retourne")

    async def _async_get_json(self, chemin: str, params: dict[str, Any]) -> Any:
        """GET protégé : réseau, HTTP et JSON validés."""
        LOGGER.debug("_async_get_json() appelé | chemin=%s", chemin)
        url = f"{self._base_url}/{chemin}"
        try:
            async with self._session.get(url, params=params) as response:
                response.raise_for_status()
                LOGGER.debug("_async_get_json() retourne la réponse (%s)", chemin)
                return await response.json()
        except ContentTypeError as erreur:
            # Sous-classe de ClientResponseError : une réponse 200 qui n'est pas
            # du JSON est illisible, pas une erreur HTTP « 200 ».
            msg = f"Réponse illisible de Hub'Eau ({chemin})"
            raise VigicruesApiError(msg) from erreur
        except ClientResponseError as erreur:
            msg = f"Hub'Eau a répondu {erreur.status} pour {chemin}"
            LOGGER.debug("Hub'Eau a répondu %s pour %s", erreur.status, chemin)
            raise VigicruesApiError(msg) from erreur
        except (ClientError, TimeoutError) as erreur:
            msg = f"Hub'Eau est injoignable ({chemin})"
            LOGGER.debug("Hub'Eau injoignable (%s) : %s", chemin, erreur)
            raise VigicruesApiError(msg) from erreur
        except ValueError as erreur:
            msg = f"Réponse illisible de Hub'Eau ({chemin})"
            LOGGER.debug("réponse illisible de Hub'Eau (%s) : %s", chemin, erreur)
            raise VigicruesApiError(msg) from erreur

    async def async_get_stations(self, codes: list[str]) -> list[Station]:
        """Métadonnées de stations exactes ; erreur dédiée sinon.

        Le référentiel accepte des motifs de recherche : la réponse doit
        désigner exactement les codes demandés, chacun une seule fois —
        un code absent ou ambigu (motif) est refusé plutôt que de
        prendre la première station trouvée.
        """
        LOGGER.debug("async_get_stations() appelé | %s code(s)", len(codes))
        if not codes:
            LOGGER.debug("async_get_stations() retourne [] (aucun code)")
            return []
        params: dict[str, Any] = {
            "code_station": codes,
            "format": "json",
            "size": str(len(codes)),
        }
        donnees = await self._async_get_json("referentiel/stations", params)
        enregistrements = donnees.get("data") or []
        par_code: dict[str, dict[str, Any]] = {}
        for enregistrement in enregistrements:
            code = enregistrement.get("code_station")
            if code not in codes:
                msg = f"Codes ambigus : la réponse désigne {code} qui n'est pas un code exact demandé"
                LOGGER.debug("code ambigu refusé : %s", code)
                raise VigicruesStationError(msg)
            if code in par_code:
                msg = f"Le code {code} correspond à plusieurs stations : indiquez un code exact"
                LOGGER.debug("code %s ambigu (plusieurs stations)", code)
                raise VigicruesStationError(msg)
            par_code[code] = enregistrement
        manquants = sorted(set(codes) - set(par_code))
        if manquants:
            msg = f"Stations introuvables dans le référentiel Hub'Eau : {', '.join(manquants)}"
            LOGGER.debug("stations introuvables : %s", ", ".join(manquants))
            raise VigicruesStationError(msg)
        LOGGER.debug("async_get_stations() retourne %s station(s)", len(codes))
        return [_parse_station(par_code[code]) for code in codes]

    async def async_get_station(self, code: str) -> Station:
        """Métadonnées d'une station exacte."""
        return (await self.async_get_stations([code]))[0]

    async def async_rechercher_stations(
        self,
        cours_eau: str | None = None,
        code_commune: str | None = None,
    ) -> list[Station]:
        """Recherche des stations par cours d'eau (nom partiel) ou commune (code INSEE)."""
        LOGGER.debug("async_rechercher_stations() appelé")
        params: dict[str, Any] = {
            "format": "json",
            "size": str(TAILLE_RECHERCHE_MAX),
        }
        if cours_eau:
            params["libelle_cours_eau"] = cours_eau
        if code_commune:
            params["code_commune_station"] = code_commune
        donnees = await self._async_get_json("referentiel/stations", params)
        stations = [_parse_station(e) for e in donnees.get("data") or []]
        LOGGER.debug("async_rechercher_stations() retourne %s station(s)", len(stations))
        return stations

    async def async_get_observation(self, code: str, grandeur: str) -> Observation | None:
        """Dernière observation d'une grandeur, ou None si aucune mesure.

        La requête demande le tri décroissant et une seule valeur : la
        première réponse est la plus récente. Une absence de mesure
        n'est pas une erreur.
        """
        LOGGER.debug("async_get_observation() appelé | code=%s grandeur=%s", code, grandeur)
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
            LOGGER.debug("async_get_observation() retourne None (aucune mesure)")
            return None
        LOGGER.debug("async_get_observation() retourne la dernière mesure")
        return _parse_observation(enregistrements[0], grandeur)

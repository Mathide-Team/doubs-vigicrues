"""Configuration : suivi d'une ou plusieurs stations Vigicrues."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HubeauClient, Station, VigicruesApiError, VigicruesStationError
from .const import DEFAULT_STATION, DOMAIN, LOGGER

# Codes séparés par des virgules ou des espaces.
_MOTIF_CODES = re.compile(r"[,\s]+")


def _extraire_codes(saisie: str) -> list[str]:
    """Découpe une saisie libre en codes de station uniques."""
    LOGGER.debug("_extraire_codes() appelé")
    vus: list[str] = []
    for morceau in _MOTIF_CODES.split(saisie or ""):
        if morceau and morceau not in vus:
            vus.append(morceau)
    LOGGER.debug("_extraire_codes() retourne %s code(s)", len(vus))
    return vus


def _unique_id(codes: list[str]) -> str:
    """Identifiant stable de l'entrée : ensemble trié des codes."""
    return ",".join(sorted(codes))


def _codes_suivis_par(entry: Any) -> set[str]:
    """Codes suivis par une entrée, en schéma v1 ou v2.

    Une entrée 0.1.0 jamais migrée (désactivée, non chargée) garde
    ``data = {"station": code}`` : ses stations comptent aussi dans les
    contrôles de doublons.
    """
    LOGGER.debug("_codes_suivis_par() appelé")
    codes = set(entry.data.get("stations") or [])
    ancien = entry.data.get("station")
    if ancien:
        codes.add(str(ancien))
    LOGGER.debug("_codes_suivis_par() retourne %s code(s)", len(codes))
    return codes


def _titre(stations: list[Station]) -> str:
    """Titre de l'entrée : libellé seul ou résumé."""
    LOGGER.debug("_titre() appelé | %s station(s)", len(stations))
    if len(stations) == 1:
        LOGGER.debug("_titre() retourne le libellé seul")
        return stations[0].libelle
    LOGGER.debug("_titre() retourne un résumé")
    return f"{len(stations)} stations hydrométriques"


def _client(hass: Any) -> HubeauClient:
    return HubeauClient(async_get_clientsession(hass))


class VigicruesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Étapes de configuration : une entrée suit plusieurs stations."""

    VERSION = 2

    def __init__(self) -> None:
        LOGGER.debug("VigicruesConfigFlow.__init__() appelé")
        self._resultats: list[Station] = []
        LOGGER.debug("VigicruesConfigFlow.__init__() retourne")

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Codes de stations, ou recherche par cours d'eau / commune."""
        LOGGER.debug("async_step_user() appelé | saisie=%s", user_input is not None)
        erreurs: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("chercher"):
                LOGGER.debug("async_step_user() bascule vers la recherche")
                return await self.async_step_recherche()
            codes = _extraire_codes(str(user_input.get("stations") or ""))
            if not codes:
                LOGGER.debug("async_step_user() : codes vides")
                erreurs["stations"] = "codes_vides"
            else:
                # L'interruption standard précède la vérification de
                # conflit : un ensemble identique déjà configuré interrompt
                # le flux plutôt que d'afficher une erreur.
                await self.async_set_unique_id(_unique_id(codes))
                self._abort_if_unique_id_configured()
                try:
                    stations = await _client(self.hass).async_get_stations(codes)
                except VigicruesStationError as erreur:
                    LOGGER.debug("station inconnue au flux utilisateur : %s", erreur)
                    erreurs["stations"] = "station_inconnue"
                except VigicruesApiError as erreur:
                    LOGGER.debug("API injoignable au flux utilisateur : %s", erreur)
                    erreurs["base"] = "cannot_connect"
                else:
                    conflit = self._conflit_stations(codes)
                    if conflit:
                        LOGGER.debug("conflit de stations au flux utilisateur")
                        erreurs["base"] = "deja_suivie"
                    else:
                        LOGGER.debug("async_step_user() crée l'entrée")
                        return await self._creer(stations)
        LOGGER.debug("async_step_user() affiche le formulaire (erreurs=%s)", erreurs)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("stations", default=DEFAULT_STATION): str,
                    vol.Optional("chercher", default=False): bool,
                }
            ),
            errors=erreurs,
        )

    async def async_step_recherche(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Recherche par nom de cours d'eau ou code INSEE de commune."""
        LOGGER.debug("async_step_recherche() appelé | saisie=%s", user_input is not None)
        erreurs: dict[str, str] = {}
        if user_input is not None:
            cours_eau = str(user_input.get("cours_eau") or "").strip()
            code_commune = str(user_input.get("code_commune") or "").strip()
            if not cours_eau and not code_commune:
                LOGGER.debug("async_step_recherche() : aucun critère")
                erreurs["base"] = "au_moins_un_critere"
            else:
                try:
                    resultats = await _client(self.hass).async_rechercher_stations(
                        cours_eau=cours_eau or None,
                        code_commune=code_commune or None,
                    )
                except VigicruesApiError as erreur:
                    LOGGER.debug("API injoignable à la recherche : %s", erreur)
                    erreurs["base"] = "cannot_connect"
                else:
                    if not resultats:
                        LOGGER.debug("async_step_recherche() : aucune station trouvée")
                        erreurs["base"] = "aucune_trouvee"
                    else:
                        self._resultats = resultats
                        LOGGER.debug("async_step_recherche() passe aux résultats (%s)", len(resultats))
                        return await self.async_step_resultats()
        LOGGER.debug("async_step_recherche() affiche le formulaire (erreurs=%s)", erreurs)
        return self.async_show_form(
            step_id="recherche",
            data_schema=vol.Schema(
                {
                    vol.Optional("cours_eau"): str,
                    vol.Optional("code_commune"): str,
                }
            ),
            errors=erreurs,
        )

    async def async_step_resultats(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Sélection parmi les stations trouvées."""
        LOGGER.debug("async_step_resultats() appelé | saisie=%s", user_input is not None)
        erreurs: dict[str, str] = {}
        if user_input is not None:
            codes = list(user_input.get("stations") or [])
            if not codes:
                LOGGER.debug("async_step_resultats() : codes vides")
                erreurs["stations"] = "codes_vides"
            elif self._conflit_stations(codes):
                LOGGER.debug("async_step_resultats() : déjà suivie")
                erreurs["base"] = "deja_suivie"
            else:
                par_code = {s.code: s for s in self._resultats}
                LOGGER.debug("async_step_resultats() crée l'entrée")
                return await self._creer([par_code[c] for c in codes])
        LOGGER.debug("async_step_resultats() affiche le formulaire (erreurs=%s)", erreurs)
        return self.async_show_form(
            step_id="resultats",
            data_schema=vol.Schema(
                {
                    vol.Required("stations"): cv.multi_select(
                        {s.code: f"{s.libelle} ({s.code})" for s in self._resultats}
                    )
                }
            ),
            errors=erreurs,
        )

    def _conflit_stations(self, codes: list[str]) -> bool:
        """Une station demandée est-elle déjà suivie par une autre entrée ?"""
        LOGGER.debug("_conflit_stations() appelé | %s code(s)", len(codes))
        suivis: set[str] = set()
        for entry in self._async_current_entries():
            suivis.update(_codes_suivis_par(entry))
        conflit = bool(set(codes) & suivis)
        LOGGER.debug("_conflit_stations() retourne %s", conflit)
        return conflit

    async def _creer(self, stations: list[Station]) -> ConfigFlowResult:
        """Crée l'entrée ; le titre résume les stations suivies."""
        LOGGER.debug("_creer() appelé | %s station(s)", len(stations))
        codes = [s.code for s in stations]
        await self.async_set_unique_id(_unique_id(codes))
        self._abort_if_unique_id_configured()
        LOGGER.debug("_creer() crée l'entrée")
        return self.async_create_entry(
            title=_titre(stations),
            data={"stations": codes},
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: Any) -> VigicruesOptionsFlow:
        """Options : gérer la liste des stations suivies."""
        return VigicruesOptionsFlow()


class VigicruesOptionsFlow(OptionsFlow):
    """Ajout et retrait de stations dans l'entrée existante."""

    def __init__(self) -> None:
        LOGGER.debug("VigicruesOptionsFlow.__init__() appelé")
        self._resultats: list[Station] = []
        self._conservees: list[str] = []
        LOGGER.debug("VigicruesOptionsFlow.__init__() retourne")

    @property
    def _stations_actuelles(self) -> list[str]:
        """Stations suivies, en schéma v1 ou v2 (entrée non migrée)."""
        return sorted(_codes_suivis_par(self.config_entry))

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Retrait par désélection, puis ajout éventuel."""
        LOGGER.debug("async_step_init() appelé | saisie=%s", user_input is not None)
        erreurs: dict[str, str] = {}
        if user_input is not None:
            conservees = list(user_input.get("stations") or [])
            if user_input.get("ajouter"):
                self._conservees = conservees
                LOGGER.debug("async_step_init() bascule vers l'ajout")
                return await self.async_step_ajout(None)
            if not conservees:
                LOGGER.debug("async_step_init() : aucune station conservée")
                erreurs["stations"] = "au_moins_une_station"
            else:
                LOGGER.debug("async_step_init() enregistre %s code(s)", len(conservees))
                return await self._enregistrer(conservees)
        actuelles = self._stations_actuelles
        LOGGER.debug("async_step_init() affiche le formulaire (erreurs=%s)", erreurs)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("stations", default=actuelles): cv.multi_select({c: c for c in actuelles}),
                    vol.Optional("ajouter", default=False): bool,
                }
            ),
            errors=erreurs,
        )

    async def async_step_ajout(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Codes à ajouter, ou recherche par cours d'eau / commune."""
        LOGGER.debug("async_step_ajout() appelé | saisie=%s", user_input is not None)
        erreurs: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("chercher"):
                LOGGER.debug("async_step_ajout() bascule vers la recherche")
                return await self.async_step_recherche()
            codes = _extraire_codes(str(user_input.get("stations") or ""))
            if not codes:
                LOGGER.debug("async_step_ajout() : codes vides")
                erreurs["stations"] = "codes_vides"
            else:
                try:
                    await _client(self.hass).async_get_stations(codes)
                except VigicruesStationError as erreur:
                    LOGGER.debug("station inconnue à l'ajout : %s", erreur)
                    erreurs["stations"] = "station_inconnue"
                except VigicruesApiError as erreur:
                    LOGGER.debug("API injoignable à l'ajout : %s", erreur)
                    erreurs["base"] = "cannot_connect"
                else:
                    LOGGER.debug("async_step_ajout() enregistre %s code(s)", len(codes))
                    return await self._enregistrer(self._conservees + codes)
        LOGGER.debug("async_step_ajout() affiche le formulaire (erreurs=%s)", erreurs)
        return self.async_show_form(
            step_id="ajout",
            data_schema=vol.Schema(
                {
                    vol.Required("stations"): str,
                    vol.Optional("chercher", default=False): bool,
                }
            ),
            errors=erreurs,
        )

    async def async_step_recherche(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Recherche de stations à ajouter."""
        LOGGER.debug("async_step_recherche() (options) appelé | saisie=%s", user_input is not None)
        erreurs: dict[str, str] = {}
        if user_input is not None:
            cours_eau = str(user_input.get("cours_eau") or "").strip()
            code_commune = str(user_input.get("code_commune") or "").strip()
            if not cours_eau and not code_commune:
                LOGGER.debug("async_step_recherche() (options) : aucun critère")
                erreurs["base"] = "au_moins_un_critere"
            else:
                try:
                    resultats = await _client(self.hass).async_rechercher_stations(
                        cours_eau=cours_eau or None,
                        code_commune=code_commune or None,
                    )
                except VigicruesApiError as erreur:
                    LOGGER.debug("API injoignable à la recherche (options) : %s", erreur)
                    erreurs["base"] = "cannot_connect"
                else:
                    if not resultats:
                        LOGGER.debug("async_step_recherche() (options) : aucune station trouvée")
                        erreurs["base"] = "aucune_trouvee"
                    else:
                        self._resultats = resultats
                        LOGGER.debug(
                            "async_step_recherche() (options) passe aux résultats (%s)", len(resultats)
                        )
                        return await self.async_step_resultats()
        LOGGER.debug("async_step_recherche() (options) affiche le formulaire (erreurs=%s)", erreurs)
        return self.async_show_form(
            step_id="recherche",
            data_schema=vol.Schema(
                {
                    vol.Optional("cours_eau"): str,
                    vol.Optional("code_commune"): str,
                }
            ),
            errors=erreurs,
        )

    async def async_step_resultats(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Sélection de stations trouvées à ajouter."""
        LOGGER.debug("async_step_resultats() (options) appelé | saisie=%s", user_input is not None)
        erreurs: dict[str, str] = {}
        if user_input is not None:
            codes = list(user_input.get("stations") or [])
            if not codes:
                LOGGER.debug("async_step_resultats() (options) : codes vides")
                erreurs["stations"] = "codes_vides"
            else:
                LOGGER.debug("async_step_resultats() (options) enregistre %s code(s)", len(codes))
                return await self._enregistrer(self._conservees + codes)
        LOGGER.debug("async_step_resultats() (options) affiche le formulaire (erreurs=%s)", erreurs)
        return self.async_show_form(
            step_id="resultats",
            data_schema=vol.Schema(
                {
                    vol.Required("stations"): cv.multi_select(
                        {s.code: f"{s.libelle} ({s.code})" for s in self._resultats}
                    )
                }
            ),
            errors=erreurs,
        )

    async def _enregistrer(self, codes: list[str]) -> ConfigFlowResult:
        """Met à jour la liste des stations, sans doublon ni conflit."""
        LOGGER.debug("_enregistrer() appelé | %s code(s)", len(codes))
        uniques: list[str] = []
        for code in codes:
            if code not in uniques:
                uniques.append(code)
        if not uniques:
            LOGGER.debug("_enregistrer() : rien à enregistrer")
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Required("stations", default=[]): cv.multi_select({}),
                        vol.Optional("ajouter", default=True): bool,
                    }
                ),
                errors={"stations": "au_moins_une_station"},
            )
        entry = self.config_entry
        autres: set[str] = set()
        for e in self.hass.config_entries.async_entries(DOMAIN):
            if e.entry_id != entry.entry_id:
                autres.update(_codes_suivis_par(e))
        if set(uniques) & autres:
            LOGGER.debug("_enregistrer() : station déjà suivie par une autre entrée")
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Required("stations", default=self._stations_actuelles): cv.multi_select(
                            {c: c for c in self._stations_actuelles}
                        ),
                        vol.Optional("ajouter", default=False): bool,
                    }
                ),
                errors={"base": "deja_suivie"},
            )
        self.hass.config_entries.async_update_entry(
            entry,
            data={"stations": uniques},
            unique_id=_unique_id(uniques),
        )
        LOGGER.debug("_enregistrer() retourne l'entrée mise à jour")
        return self.async_create_entry(title="", data={})

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
from .const import DEFAULT_STATION, DOMAIN

# Codes séparés par des virgules ou des espaces.
_MOTIF_CODES = re.compile(r"[,\s]+")


def _extraire_codes(saisie: str) -> list[str]:
    """Découpe une saisie libre en codes de station uniques."""
    vus: list[str] = []
    for morceau in _MOTIF_CODES.split(saisie or ""):
        if morceau and morceau not in vus:
            vus.append(morceau)
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
    codes = set(entry.data.get("stations") or [])
    ancien = entry.data.get("station")
    if ancien:
        codes.add(str(ancien))
    return codes


def _titre(stations: list[Station]) -> str:
    """Titre de l'entrée : libellé seul ou résumé."""
    if len(stations) == 1:
        return stations[0].libelle
    return f"{len(stations)} stations hydrométriques"


def _client(hass: Any) -> HubeauClient:
    return HubeauClient(async_get_clientsession(hass))


class VigicruesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Étapes de configuration : une entrée suit plusieurs stations."""

    VERSION = 2

    def __init__(self) -> None:
        self._resultats: list[Station] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Codes de stations, ou recherche par cours d'eau / commune."""
        erreurs: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("chercher"):
                return await self.async_step_recherche()
            codes = _extraire_codes(str(user_input.get("stations") or ""))
            if not codes:
                erreurs["stations"] = "codes_vides"
            else:
                # L'interruption standard précède la vérification de
                # conflit : un ensemble identique déjà configuré interrompt
                # le flux plutôt que d'afficher une erreur.
                await self.async_set_unique_id(_unique_id(codes))
                self._abort_if_unique_id_configured()
                try:
                    stations = await _client(self.hass).async_get_stations(codes)
                except VigicruesStationError:
                    erreurs["stations"] = "station_inconnue"
                except VigicruesApiError:
                    erreurs["base"] = "cannot_connect"
                else:
                    conflit = self._conflit_stations(codes)
                    if conflit:
                        erreurs["base"] = "deja_suivie"
                    else:
                        return await self._creer(stations)
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
        erreurs: dict[str, str] = {}
        if user_input is not None:
            cours_eau = str(user_input.get("cours_eau") or "").strip()
            code_commune = str(user_input.get("code_commune") or "").strip()
            if not cours_eau and not code_commune:
                erreurs["base"] = "au_moins_un_critere"
            else:
                try:
                    resultats = await _client(self.hass).async_rechercher_stations(
                        cours_eau=cours_eau or None,
                        code_commune=code_commune or None,
                    )
                except VigicruesApiError:
                    erreurs["base"] = "cannot_connect"
                else:
                    if not resultats:
                        erreurs["base"] = "aucune_trouvee"
                    else:
                        self._resultats = resultats
                        return await self.async_step_resultats()
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
        erreurs: dict[str, str] = {}
        if user_input is not None:
            codes = list(user_input.get("stations") or [])
            if not codes:
                erreurs["stations"] = "codes_vides"
            elif self._conflit_stations(codes):
                erreurs["base"] = "deja_suivie"
            else:
                par_code = {s.code: s for s in self._resultats}
                return await self._creer([par_code[c] for c in codes])
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
        suivis: set[str] = set()
        for entry in self._async_current_entries():
            suivis.update(_codes_suivis_par(entry))
        return bool(set(codes) & suivis)

    async def _creer(self, stations: list[Station]) -> ConfigFlowResult:
        """Crée l'entrée ; le titre résume les stations suivies."""
        codes = [s.code for s in stations]
        await self.async_set_unique_id(_unique_id(codes))
        self._abort_if_unique_id_configured()
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
        self._resultats: list[Station] = []
        self._conservees: list[str] = []

    @property
    def _stations_actuelles(self) -> list[str]:
        """Stations suivies, en schéma v1 ou v2 (entrée non migrée)."""
        return sorted(_codes_suivis_par(self.config_entry))

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Retrait par désélection, puis ajout éventuel."""
        erreurs: dict[str, str] = {}
        if user_input is not None:
            conservees = list(user_input.get("stations") or [])
            if user_input.get("ajouter"):
                self._conservees = conservees
                return await self.async_step_ajout(None)
            if not conservees:
                erreurs["stations"] = "au_moins_une_station"
            else:
                return await self._enregistrer(conservees)
        actuelles = self._stations_actuelles
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
        erreurs: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("chercher"):
                return await self.async_step_recherche()
            codes = _extraire_codes(str(user_input.get("stations") or ""))
            if not codes:
                erreurs["stations"] = "codes_vides"
            else:
                try:
                    await _client(self.hass).async_get_stations(codes)
                except VigicruesStationError:
                    erreurs["stations"] = "station_inconnue"
                except VigicruesApiError:
                    erreurs["base"] = "cannot_connect"
                else:
                    return await self._enregistrer(self._conservees + codes)
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
        erreurs: dict[str, str] = {}
        if user_input is not None:
            cours_eau = str(user_input.get("cours_eau") or "").strip()
            code_commune = str(user_input.get("code_commune") or "").strip()
            if not cours_eau and not code_commune:
                erreurs["base"] = "au_moins_un_critere"
            else:
                try:
                    resultats = await _client(self.hass).async_rechercher_stations(
                        cours_eau=cours_eau or None,
                        code_commune=code_commune or None,
                    )
                except VigicruesApiError:
                    erreurs["base"] = "cannot_connect"
                else:
                    if not resultats:
                        erreurs["base"] = "aucune_trouvee"
                    else:
                        self._resultats = resultats
                        return await self.async_step_resultats()
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
        erreurs: dict[str, str] = {}
        if user_input is not None:
            codes = list(user_input.get("stations") or [])
            if not codes:
                erreurs["stations"] = "codes_vides"
            else:
                return await self._enregistrer(self._conservees + codes)
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
        uniques: list[str] = []
        for code in codes:
            if code not in uniques:
                uniques.append(code)
        if not uniques:
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
        return self.async_create_entry(title="", data={})

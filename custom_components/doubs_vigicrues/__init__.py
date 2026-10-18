"""Intégration « Niveau du Doubs (Vigicrues) » : stations hydrométriques."""

from __future__ import annotations

from typing import cast

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later

from .api import DoubsVigicruesError, HubeauClient, Station
from .const import CONF_STATION, CONF_STATIONS, DOMAIN, LOGGER
from .coordinator import DoubsVigicruesCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type DoubsVigicruesConfigEntry = ConfigEntry[dict[str, DoubsVigicruesCoordinator]]

VERSION_ACTUELLE = 2

# Nouvelle tentative de résolution des stations en attente (référentiel
# momentanément indisponible au démarrage).
DELAI_REESSAI_S = 60


async def async_migrate_entry(hass: HomeAssistant, entry: DoubsVigicruesConfigEntry) -> bool:
    """Fait évoluer les entrées anciennes sans casser les entités.

    v1 : une entrée par station, ``data = {"station": code}`` ;
    v2 : une entrée suit une liste, ``data = {"stations": [codes]}``.
    Les identifiants uniques des capteurs (``code_hauteur``) et des
    appareils (``code``) ne changent pas : personnalisations et
    historiques sont conservés.
    """
    if entry.version > VERSION_ACTUELLE:
        # Une version inconnue vient d'une installation plus récente :
        # ne pas dégrader silencieusement ses données.
        return False
    if entry.version == 1:
        ancien = cast("str | None", entry.data.get(CONF_STATION))
        if not ancien:
            LOGGER.error("Entrée v1 sans station : migration impossible")
            return False
        hass.config_entries.async_update_entry(
            entry,
            data={CONF_STATIONS: [ancien]},
            version=VERSION_ACTUELLE,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: DoubsVigicruesConfigEntry) -> bool:
    """Prépare un coordinateur par station suivie.

    Les stations sont indépendantes : une station en panne ne bloque
    pas les autres, et l'échec total seul laisse Home Assistant
    retenter plus tard. Une station dont le référentiel est indisponible
    au démarrage est mise en attente et réessayée périodiquement.
    """
    client = HubeauClient(async_get_clientsession(hass))
    codes: list[str] = list(entry.data.get(CONF_STATIONS) or [])
    coordinateurs: dict[str, DoubsVigicruesCoordinator] = {}
    en_attente: list[str] = []
    # Chaque station est résolue individuellement : une erreur sur l'une
    # (API injoignable pour ce code, station disparue du référentiel) ne
    # doit pas bloquer les autres.
    for code in codes:
        try:
            station = await client.async_get_station(code)
        except DoubsVigicruesError as erreur:
            LOGGER.warning("Station %s en attente : %s", code, erreur)
            en_attente.append(code)
            continue
        await _creer_coordinateur(hass, entry, client, station, coordinateurs)
    if codes and not coordinateurs and not en_attente:
        # Aucune station n'a pu être résolue : réessayer plus tard.
        raise ConfigEntryNotReady

    donnees = {
        "client": client,
        "coordinateurs": coordinateurs,
        "en_attente": en_attente,
        "ajouter_entites": None,
        "retenter": None,
    }
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = donnees
    entry.runtime_data = coordinateurs
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    minuteur: dict[str, object | None] = {"annuler": None}

    def _annuler_minuteur() -> None:
        annuler = minuteur["annuler"]
        if annuler is not None:
            cast("object", annuler)()
            minuteur["annuler"] = None

    def _planifier() -> None:
        _annuler_minuteur()
        minuteur["annuler"] = async_call_later(hass, DELAI_REESSAI_S, _retenter)

    def _courante() -> bool:
        """La tentative est-elle encore celle de l'entrée chargée ?

        Après un rechargement (options), une nouvelle instance de ces
        données existe : une tentative antérieure ne doit plus rien
        modifier. L'état est aussi contrôlé APRÈS chaque attente réseau.
        """
        return (
            entry.state is ConfigEntryState.LOADED
            and hass.data.get(DOMAIN, {}).get(entry.entry_id) is donnees
        )

    async def _retenter(_now: object | None = None) -> None:
        """Retente les stations en attente, sans toucher aux autres.

        Une station retirée des options pendant qu'elle était en attente
        n'est pas reprise : seules les stations encore demandées par
        l'entrée sont réessayées, et une tentative rendue obsolète par un
        rechargement s'arrête sans rien modifier.
        """
        if not _courante():
            return
        restants: list[str] = []
        for code in list(donnees["en_attente"]):
            if code not in set(entry.data.get(CONF_STATIONS) or []):
                continue
            try:
                station = await client.async_get_station(code)
            except DoubsVigicruesError as erreur:
                LOGGER.debug("Station %s toujours en attente : %s", code, erreur)
                restants.append(code)
                continue
            # Le rechargement a pu survenir pendant l'attente réseau :
            # ne rien modifier si cette tentative est obsolète.
            if not _courante():
                return
            if code not in set(entry.data.get(CONF_STATIONS) or []):
                continue
            coordinateur = DoubsVigicruesCoordinator(hass, entry, client, station)
            # Hors installation, un simple rafraîchissement (tolérant) :
            # le « premier rafraîchissement » n'est valide qu'à l'installation.
            await coordinateur.async_refresh()
            if not _courante():
                return
            # La station a pu être retirée des options pendant l'attente :
            # ne rien créer pour elle.
            if code not in set(entry.data.get(CONF_STATIONS) or []):
                continue
            coordinateurs[station.code] = coordinateur
            entry.runtime_data = coordinateurs
            if donnees["ajouter_entites"] is not None:
                from .sensor import DoubsVigicruesDebitSensor, DoubsVigicruesHauteurSensor

                donnees["ajouter_entites"](
                    [
                        DoubsVigicruesHauteurSensor(coordinateur),
                        DoubsVigicruesDebitSensor(coordinateur),
                    ]
                )
        if not _courante():
            return
        donnees["en_attente"] = restants
        if restants:
            _planifier()

    donnees["retenter"] = _retenter
    if en_attente:
        _planifier()
    entry.async_on_unload(_annuler_minuteur)
    entry.async_on_unload(entry.add_update_listener(_async_recharger))
    return True


async def _creer_coordinateur(
    hass: HomeAssistant,
    entry: DoubsVigicruesConfigEntry,
    client: HubeauClient,
    station: Station,
    coordinateurs: dict[str, DoubsVigicruesCoordinator],
) -> DoubsVigicruesCoordinator:
    """Crée le coordinateur d'une station, premier rafraîchissement tolérant."""
    coordinateur = DoubsVigicruesCoordinator(hass, entry, client, station)
    try:
        await coordinateur.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        LOGGER.warning("Première mise à jour impossible pour %s", station.code)
    coordinateurs[station.code] = coordinateur
    return coordinateur


async def _async_recharger(hass: HomeAssistant, entry: DoubsVigicruesConfigEntry) -> None:
    """Recharge l'entrée quand la liste des stations change (options).

    Les stations retirées sont détachées proprement : leurs entités sont
    supprimées du registre et leurs appareils retirés, sans toucher aux
    stations conservées (leurs personnalisations survivent).
    """
    anciens: set[str] = set(entry.runtime_data or {})
    nouveaux: set[str] = set(entry.data.get(CONF_STATIONS) or [])
    # Les stations en attente ne figurent pas dans runtime_data : les
    # relire aussi pour ne pas laisser d'entités orphelines.
    donnees = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    anciens |= set(donnees.get("en_attente") or [])
    await hass.config_entries.async_reload(entry.entry_id)
    _detacher_stations(hass, entry, anciens - nouveaux)


def _detacher_stations(hass: HomeAssistant, entry: DoubsVigicruesConfigEntry, codes: set[str]) -> None:
    """Supprime du registre les entités et appareils des stations retirées."""
    if not codes:
        return
    registre_entites = er.async_get(hass)
    registre_appareils = dr.async_get(hass)
    for code in codes:
        for suffixe in ("hauteur", "debit"):
            entite_id = registre_entites.async_get_entity_id("sensor", DOMAIN, f"{code}_{suffixe}")
            if entite_id is not None:
                registre_entites.async_remove(entite_id)
        appareil = registre_appareils.async_get_device(identifiers={(DOMAIN, code)})
        if appareil is not None:
            registre_appareils.async_remove_device(appareil.id)


async def async_unload_entry(hass: HomeAssistant, entry: DoubsVigicruesConfigEntry) -> bool:
    """Décharge les entités de l'entrée."""
    retour = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return retour

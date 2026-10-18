"""Tests du flux de configuration multi-stations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.doubs_vigicrues.const import DEFAULT_STATION, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
STATION = "U259999001"
STATION_2 = "U259999002"
STATION_INCONNUE = "U259999003"
STATION_PANNE = "U500000500"


def _lire(nom: str) -> str:
    return (FIXTURES / nom).read_text()


def _enregistrement_station(code: str) -> dict:
    """Enregistrement de référentiel avec le code demandé."""
    enregistrement = json.loads(_lire("station_referentiel.json"))["data"][0]
    if code == STATION_2:
        enregistrement = json.loads(_lire("station_referentiel_sans_debit.json"))["data"][0]
    enregistrement["code_station"] = code
    return enregistrement


def _build_app() -> web.Application:
    """Serveur factice : stations connues, recherche, inconnues ou en panne."""

    async def referentiel(request: web.Request) -> web.Response:
        codes = request.query.getall("code_station", [])
        if STATION_PANNE in codes:
            return web.Response(status=500)
        cours_eau = request.query.get("libelle_cours_eau", "")
        commune = request.query.get("code_commune_station", "")
        if cours_eau or commune:
            # Recherche : les stations de test, filtrées par critère.
            connues = [STATION, STATION_2]
            if commune and commune != "25056":
                connues = []
            return web.json_response(
                {
                    "count": len(connues),
                    "first": "https://exemple.invalid/",
                    "next": None,
                    "prev": None,
                    "data": [_enregistrement_station(c) for c in connues],
                }
            )
        enregistrements = [_enregistrement_station(c) for c in codes if c in (STATION, STATION_2)]
        return web.json_response(
            {
                "count": len(enregistrements),
                "first": "https://exemple.invalid/",
                "next": None,
                "prev": None,
                "data": enregistrements,
            }
        )

    app = web.Application()
    app.router.add_get("/referentiel/stations", referentiel)
    return app


@pytest.fixture(autouse=True)
def _socket_autorise(socket_enabled):
    """Autorise le serveur HTTP local des tests."""
    yield


@pytest.fixture
async def client():
    server = TestServer(_build_app())
    test_client = TestClient(server)
    await test_client.start_server()
    yield test_client
    await test_client.close()


@pytest.fixture
def api_locale(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Pointe le client Hub'Eau vers le serveur factice pendant tout le test."""
    monkeypatch.setattr(
        "custom_components.doubs_vigicrues.api.BASE_URL",
        str(client.make_url("/")),
    )
    return client


async def test_formulaire_defaut(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Le formulaire propose la station de Besançon par défaut."""
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["step_id"] == "user"
    champ = next(iter(resultat["data_schema"].schema))
    assert champ.schema == "stations"
    # Home Assistant enveloppe les valeurs par défaut dans une fabrique.
    valeur_defaut = champ.default
    if callable(valeur_defaut):
        valeur_defaut = valeur_defaut()
    assert valeur_defaut == DEFAULT_STATION


async def test_configuration_reussie(hass: HomeAssistant, api_locale: TestClient) -> None:
    """La station validée crée une entrée au nom réel de la station."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": STATION, "chercher": False}
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert resultat["title"] == "Le Douby à Exempleville - Moulin de Test"
    assert resultat["data"] == {"stations": [STATION]}
    entrees = hass.config_entries.async_entries(DOMAIN)
    assert len(entrees) == 1
    assert entrees[0].unique_id == STATION


async def test_configuration_codes_multiples(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Plusieurs codes (virgules et espaces) créent une entrée multi-stations."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": f" {STATION},  {STATION_2} ", "chercher": False}
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert resultat["data"] == {"stations": [STATION, STATION_2]}
    assert resultat["title"] == "2 stations hydrométriques"
    assert hass.config_entries.async_entries(DOMAIN)[0].unique_id == f"{STATION},{STATION_2}"


async def test_deja_configure(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Un ensemble de stations déjà configuré interrompt le flux."""
    existante = MockConfigEntry(domain=DOMAIN, data={"stations": [STATION]}, unique_id=STATION)
    existante.add_to_hass(hass)
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": STATION, "chercher": False}
    )
    assert resultat["type"] is FlowResultType.ABORT
    assert resultat["reason"] == "already_configured"


async def test_station_inconnue(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Un code absent du référentiel réaffiche le formulaire avec l'erreur."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": STATION_INCONNUE, "chercher": False}
    )
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {"stations": "station_inconnue"}


async def test_api_indisponible(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Une API injoignable réaffiche le formulaire avec l'erreur."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": STATION_PANNE, "chercher": False}
    )
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {"base": "cannot_connect"}


async def test_codes_vides(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Une saisie vide (virgules et espaces) ne crée rien."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": " ,  ", "chercher": False}
    )
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {"stations": "codes_vides"}


async def test_deja_suivie_ailleurs(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Un code déjà suivi par une autre entrée est refusé."""
    hass.config.language = "fr"
    existante = MockConfigEntry(domain=DOMAIN, data={"stations": [STATION_2]}, unique_id=STATION_2)
    existante.add_to_hass(hass)
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": f"{STATION},{STATION_2}", "chercher": False}
    )
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {"base": "deja_suivie"}


async def test_recherche_cours_eau(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Recherche par cours d'eau puis sélection multi-stations."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": "", "chercher": True}
    )
    assert resultat["step_id"] == "recherche"
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"cours_eau": "Le Douby", "code_commune": ""}
    )
    assert resultat["step_id"] == "resultats"
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": [STATION, STATION_2]}
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert resultat["data"] == {"stations": [STATION, STATION_2]}


async def test_recherche_commune(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Recherche par code INSEE de commune."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": "", "chercher": True}
    )
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"cours_eau": "", "code_commune": "25056"}
    )
    assert resultat["step_id"] == "resultats"
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], {"stations": [STATION]})
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert resultat["data"] == {"stations": [STATION]}


async def test_recherche_aucun_critere(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Une recherche sans critère est refusée."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": "", "chercher": True}
    )
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"cours_eau": "", "code_commune": ""}
    )
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {"base": "au_moins_un_critere"}


async def test_recherche_aucune_trouvee(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Une recherche sans résultat est signalée."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": "", "chercher": True}
    )
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"cours_eau": "", "code_commune": "99999"}
    )
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {"base": "aucune_trouvee"}


async def _options_init(hass: HomeAssistant, entry: MockConfigEntry) -> object:
    return await hass.config_entries.options.async_init(entry.entry_id)


async def test_options_retrait_station(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Désélectionner une station la retire de l'entrée."""
    hass.config.language = "fr"
    entry = MockConfigEntry(
        domain=DOMAIN, data={"stations": [STATION, STATION_2]}, unique_id=f"{STATION},{STATION_2}"
    )
    entry.add_to_hass(hass)
    resultat = await _options_init(hass, entry)
    assert resultat["step_id"] == "init"
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"],
        {"stations": [STATION], "ajouter": False},
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data == {"stations": [STATION]}
    assert entry.unique_id == STATION


async def test_options_ajout_codes(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Ajouter une station par code passe par l'étape d'ajout."""
    hass.config.language = "fr"
    entry = MockConfigEntry(domain=DOMAIN, data={"stations": [STATION]}, unique_id=STATION)
    entry.add_to_hass(hass)
    resultat = await _options_init(hass, entry)
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"],
        {"stations": [STATION], "ajouter": True},
    )
    assert resultat["step_id"] == "ajout"
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"], {"stations": STATION_2, "chercher": False}
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data == {"stations": [STATION, STATION_2]}
    assert entry.unique_id == f"{STATION},{STATION_2}"


async def test_options_ajout_recherche(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Ajouter une station via la recherche et la sélection."""
    hass.config.language = "fr"
    entry = MockConfigEntry(domain=DOMAIN, data={"stations": [STATION]}, unique_id=STATION)
    entry.add_to_hass(hass)
    resultat = await _options_init(hass, entry)
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"],
        {"stations": [STATION], "ajouter": True},
    )
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"], {"stations": "", "chercher": True}
    )
    assert resultat["step_id"] == "recherche"
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"], {"cours_eau": "Le Douby", "code_commune": ""}
    )
    assert resultat["step_id"] == "resultats"
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"], {"stations": [STATION_2]}
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data == {"stations": [STATION, STATION_2]}


async def test_options_au_moins_une_station(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Tout désélectionner sans ajout est refusé."""
    hass.config.language = "fr"
    entry = MockConfigEntry(domain=DOMAIN, data={"stations": [STATION]}, unique_id=STATION)
    entry.add_to_hass(hass)
    resultat = await _options_init(hass, entry)
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"],
        {"stations": [], "ajouter": False},
    )
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {"stations": "au_moins_une_station"}


async def test_options_deja_suivie_ailleurs(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Ajouter une station suivie par une autre entrée est refusé."""
    hass.config.language = "fr"
    autre = MockConfigEntry(domain=DOMAIN, data={"stations": [STATION_2]}, unique_id=STATION_2)
    autre.add_to_hass(hass)
    entry = MockConfigEntry(domain=DOMAIN, data={"stations": [STATION]}, unique_id=STATION)
    entry.add_to_hass(hass)
    resultat = await _options_init(hass, entry)
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"],
        {"stations": [STATION], "ajouter": True},
    )
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"], {"stations": STATION_2, "chercher": False}
    )
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {"base": "deja_suivie"}


async def test_deja_suivie_entree_v1(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Une station suivie par une entrée 0.1.0 non migrée compte aussi.

    Une entrée désactivée ou jamais rechargée garde
    ``data = {"station": code}`` : le contrôle de doublons doit la lire.
    """
    hass.config.language = "fr"
    ancienne = MockConfigEntry(domain=DOMAIN, data={"station": STATION_2}, unique_id=STATION_2, version=1)
    ancienne.add_to_hass(hass)
    # Ensemble différent : pas d'interruption par unique_id, mais la
    # station suivie par l'entrée v1 doit être refusée.
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {"stations": f"{STATION},{STATION_2}", "chercher": False}
    )
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {"base": "deja_suivie"}

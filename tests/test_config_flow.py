"""Tests du flux de configuration."""

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

from custom_components.doubs_vigicrues.const import CONF_STATION, DEFAULT_STATION, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
STATION = "U259999001"


def _lire(nom: str) -> str:
    return (FIXTURES / nom).read_text()


def _build_app() -> web.Application:
    """Serveur factice : station connue, inconnue ou en panne."""

    async def referentiel(request: web.Request) -> web.Response:
        code = request.query.get("code_station", "")
        if code == "U500000500":
            return web.Response(status=500)
        if code == STATION:
            return web.json_response(json.loads(_lire("station_referentiel.json")))
        return web.json_response(json.loads(_lire("station_inexistante.json")))

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
    assert champ.schema == CONF_STATION
    # Home Assistant enveloppe les valeurs par défaut dans une fabrique.
    valeur_defaut = champ.default
    if callable(valeur_defaut):
        valeur_defaut = valeur_defaut()
    assert valeur_defaut == DEFAULT_STATION


async def test_configuration_reussie(hass: HomeAssistant, api_locale: TestClient) -> None:
    """La station validée crée une entrée au nom réel de la station."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], {CONF_STATION: STATION})
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert resultat["title"] == "Le Douby à Exempleville - Moulin de Test"
    assert resultat["data"] == {CONF_STATION: STATION}
    entrees = hass.config_entries.async_entries(DOMAIN)
    assert len(entrees) == 1
    assert entrees[0].unique_id == STATION


async def test_deja_configure(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Une station déjà configurée interrompt le flux."""
    existante = MockConfigEntry(domain=DOMAIN, data={CONF_STATION: STATION}, unique_id=STATION)
    existante.add_to_hass(hass)
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(resultat["flow_id"], {CONF_STATION: STATION})
    assert resultat["type"] is FlowResultType.ABORT
    assert resultat["reason"] == "already_configured"


async def test_station_inconnue(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Un code absent du référentiel réaffiche le formulaire avec l'erreur."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {CONF_STATION: "U259999003"}
    )
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {CONF_STATION: "station_inconnue"}


async def test_api_indisponible(hass: HomeAssistant, api_locale: TestClient) -> None:
    """Une API injoignable réaffiche le formulaire avec l'erreur."""
    hass.config.language = "fr"
    resultat = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    resultat = await hass.config_entries.flow.async_configure(
        resultat["flow_id"], {CONF_STATION: "U500000500"}
    )
    assert resultat["type"] is FlowResultType.FORM
    assert resultat["errors"] == {"base": "cannot_connect"}

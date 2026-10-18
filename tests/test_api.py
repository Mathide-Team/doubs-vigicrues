"""Tests du client Hub'Eau (fixtures entièrement fictives)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from custom_components.doubs_vigicrues.api import (
    DoubsVigicruesApiError,
    DoubsVigicruesStationError,
    HubeauClient,
)

FIXTURES = Path(__file__).parent / "fixtures"
STATION = "U259999001"
STATION_SANS_DEBIT = "U259999002"
STATION_PANNE = "U500000500"
STATION_MAUVAIS_JSON = "BADJSON"


def _lire(nom: str) -> str:
    return (FIXTURES / nom).read_text()


def _build_app() -> web.Application:
    """Serveur factice reproduisant les routes Hub'Eau."""

    async def referentiel(request: web.Request) -> web.Response:
        code = request.query.get("code_station", "")
        if code == STATION_PANNE:
            return web.Response(status=500)
        if code == STATION_MAUVAIS_JSON:
            return web.Response(text="pas du tout du json", content_type="text/plain")
        if code == STATION:
            return web.json_response(json.loads(_lire("station_referentiel.json")))
        if code == STATION_SANS_DEBIT:
            return web.json_response(json.loads(_lire("station_referentiel_sans_debit.json")))
        return web.json_response(json.loads(_lire("station_inexistante.json")))

    async def observations(request: web.Request) -> web.Response:
        code = request.query.get("code_entite", "")
        grandeur = request.query.get("grandeur_hydro", "")
        if code == STATION and grandeur == "H":
            return web.json_response(json.loads(_lire("observations_h.json")))
        if code == STATION and grandeur == "Q":
            return web.json_response(json.loads(_lire("observations_q.json")))
        if code == STATION_SANS_DEBIT:
            if grandeur == "H":
                return web.json_response(json.loads(_lire("observations_h.json")))
            return web.json_response(json.loads(_lire("observations_vides.json")))
        return web.json_response(json.loads(_lire("observations_vides.json")))

    app = web.Application()
    app.router.add_get("/referentiel/stations", referentiel)
    app.router.add_get("/observations_tr", observations)
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


def _hubeau(client: TestClient) -> HubeauClient:
    return HubeauClient(client.session, base_url=str(client.make_url("/")))


async def test_station(client: TestClient) -> None:
    """Les métadonnées du référentiel sont lues."""
    station = await _hubeau(client).async_get_station(STATION)
    assert station.code == STATION
    assert station.libelle == "Le Douby à Exempleville - Moulin de Test"
    assert station.commune == "EXEMPLEVILLE"
    assert station.departement == "DOUBS"
    assert station.cours_eau == "Le Douby"
    assert station.altitude == 250.0


async def test_station_inconnue(client: TestClient) -> None:
    """Une station absente du référentiel lève une erreur dédiée."""
    with pytest.raises(DoubsVigicruesStationError):
        await _hubeau(client).async_get_station("U259999003")


async def test_observation_hauteur(client: TestClient) -> None:
    """La dernière hauteur est la plus récente, en UTC, en millimètres."""
    observation = await _hubeau(client).async_get_observation(STATION, "H")
    assert observation is not None
    assert observation.resultat == 1234.0  # mm, à diviser par 1000 pour des m
    assert observation.date_obs.isoformat() == "2026-10-18T15:00:00+00:00"
    assert observation.date_obs.tzinfo is not None  # UTC conservé
    assert observation.continuite == "Continue"


async def test_observation_debit(client: TestClient) -> None:
    """Le débit est en litres par seconde, à diviser par 1000 pour des m³/s."""
    observation = await _hubeau(client).async_get_observation(STATION, "Q")
    assert observation is not None
    assert observation.resultat == 5678.0
    assert observation.grandeur == "Q"


async def test_observation_absente(client: TestClient) -> None:
    """Une grandeur sans mesure renvoie None, pas une erreur ni un zéro."""
    observation = await _hubeau(client).async_get_observation(STATION_SANS_DEBIT, "Q")
    assert observation is None


async def test_valeur_zero(client: TestClient) -> None:
    """Un zéro est une mesure valable, conservée telle quelle."""
    serveur = TestClient(TestServer(_app_extremes()))
    await serveur.start_server()
    try:
        hubeau = HubeauClient(serveur.session, base_url=str(serveur.make_url("/")))
        observation = await hubeau.async_get_observation(STATION, "H")
        assert observation is not None
        assert observation.resultat == 0.0
    finally:
        await serveur.close()


def _app_extremes() -> web.Application:
    """Serveur renvoyant une hauteur nulle puis une hauteur négative."""

    async def referentiel(request: web.Request) -> web.Response:
        return web.json_response(json.loads(_lire("station_referentiel.json")))

    async def observations(request: web.Request) -> web.Response:
        grandeur = request.query.get("grandeur_hydro", "")
        if grandeur == "Q":
            return web.json_response(json.loads(_lire("observations_h_negative.json")))
        return web.json_response(json.loads(_lire("observations_h_zero.json")))

    app = web.Application()
    app.router.add_get("/referentiel/stations", referentiel)
    app.router.add_get("/observations_tr", observations)
    return app


async def test_valeur_negative(client: TestClient) -> None:
    """Une valeur négative (étalonnage) est conservée, pas rejetée."""
    serveur = TestClient(TestServer(_app_extremes()))
    await serveur.start_server()
    try:
        hubeau = HubeauClient(serveur.session, base_url=str(serveur.make_url("/")))
        observation = await hubeau.async_get_observation(STATION, "Q")
        assert observation is not None
        assert observation.resultat == -12.0
    finally:
        await serveur.close()


async def test_erreur_http(client: TestClient) -> None:
    """Une erreur HTTP devient DoubsVigicruesApiError."""
    with pytest.raises(DoubsVigicruesApiError):
        await _hubeau(client).async_get_station(STATION_PANNE)


async def test_json_invalide(client: TestClient) -> None:
    """Une réponse illisible devient DoubsVigicruesApiError."""
    with pytest.raises(DoubsVigicruesApiError):
        await _hubeau(client).async_get_station(STATION_MAUVAIS_JSON)


async def test_erreur_reseau(client: TestClient) -> None:
    """Un serveur injoignable devient DoubsVigicruesApiError."""
    hubeau = HubeauClient(client.session, base_url="http://127.0.0.1:1")
    with pytest.raises(DoubsVigicruesApiError):
        await hubeau.async_get_station(STATION)

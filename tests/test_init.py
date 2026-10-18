"""Tests de l'installation : capteurs de hauteur et de débit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.doubs_vigicrues.const import CONF_STATION, DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
STATION = "U259999001"
STATION_SANS_DEBIT = "U259999002"


def _lire(nom: str) -> str:
    return (FIXTURES / nom).read_text()


def _build_app() -> web.Application:
    """Serveur factice reproduisant les routes Hub'Eau."""

    async def referentiel(request: web.Request) -> web.Response:
        code = request.query.get("code_station", "")
        if code == STATION_SANS_DEBIT:
            return web.json_response(json.loads(_lire("station_referentiel_sans_debit.json")))
        # Le serveur factice reflète le code demandé (la vraie API
        # renvoie la station exacte, jamais une autre pour un code exact).
        enregistrement = json.loads(_lire("station_referentiel.json"))
        enregistrement["data"][0]["code_station"] = code
        return web.json_response(enregistrement)

    async def observations(request: web.Request) -> web.Response:
        code = request.query.get("code_entite", "")
        grandeur = request.query.get("grandeur_hydro", "")
        if code == "PANNEQ" and grandeur == "Q":
            return web.Response(status=500)
        if code == "ANCIENNE" and grandeur == "H":
            return web.json_response(json.loads(_lire("observations_h_ancienne.json")))
        if grandeur == "H":
            return web.json_response(json.loads(_lire("observations_h.json")))
        if code == STATION:
            return web.json_response(json.loads(_lire("observations_q.json")))
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


async def _demarrer(hass: HomeAssistant, client: TestClient, station: str) -> None:
    """Charge l'intégration en pointant Hub'Eau vers le serveur factice."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "custom_components.doubs_vigicrues.api.BASE_URL",
            str(client.make_url("/")),
        )
        entry = MockConfigEntry(domain=DOMAIN, data={CONF_STATION: station}, unique_id=station)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _etat(hass: HomeAssistant, cle: str):
    """Cherche un capteur par la fin de son entity_id."""
    for entity_id in hass.states.async_entity_ids("sensor"):
        if entity_id.endswith(cle):
            return hass.states.get(entity_id)
    return None


async def test_capteurs(hass: HomeAssistant, client: TestClient) -> None:
    """Hauteur en m, débit en m³/s, attributs de fraîcheur."""
    hass.config.language = "fr"
    await _demarrer(hass, client, STATION)
    hauteur = _etat(hass, "_hauteur")
    assert hauteur is not None
    assert float(hauteur.state) == 1.234  # 1234 mm
    assert hauteur.attributes["date_observation"] == "2026-10-18T15:00:00+00:00"
    assert hauteur.attributes["continuite"] == "Continue"
    assert hauteur.attributes["commune"] == "EXEMPLEVILLE"
    assert hauteur.attributes["altitude_reference_m"] == 250.0
    debit = _etat(hass, "_debit")
    assert debit is not None
    assert float(debit.state) == 5.678  # 5678 l/s
    assert debit.attributes["date_observation"] == "2026-10-18T15:00:00+00:00"


async def test_capteurs_sans_debit(hass: HomeAssistant, client: TestClient) -> None:
    """Sans débit mesuré, la hauteur reste disponible."""
    hass.config.language = "fr"
    await _demarrer(hass, client, STATION_SANS_DEBIT)
    hauteur = _etat(hass, "_hauteur")
    assert hauteur is not None
    assert float(hauteur.state) == 1.234
    debit = _etat(hass, "_debit")
    assert debit is not None
    assert debit.state == "unknown"  # station sans capteur de débit : pas de valeur


async def test_erreur_debit_independante(hass: HomeAssistant, client: TestClient) -> None:
    """Une erreur sur le débit n'empêche pas la hauteur."""
    hass.config.language = "fr"
    await _demarrer(hass, client, "PANNEQ")
    hauteur = _etat(hass, "_hauteur")
    assert hauteur is not None
    assert float(hauteur.state) == 1.234
    debit = _etat(hass, "_debit")
    assert debit is not None
    assert debit.state == "unknown"


async def test_observation_ancienne_conservee(hass: HomeAssistant, client: TestClient) -> None:
    """Une réponse réussie mais ancienne garde son horodatage d'origine."""
    hass.config.language = "fr"
    await _demarrer(hass, client, "ANCIENNE")
    hauteur = _etat(hass, "_hauteur")
    assert hauteur is not None
    assert float(hauteur.state) == 1.1
    # Pas de rajeunissement : la date d'origine est exposée telle quelle.
    assert hauteur.attributes["date_observation"] == "2026-09-01T06:00:00+00:00"

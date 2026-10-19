"""Le tableau de bord d'exemple (exemples/tableau-de-bord.yaml) se rend sans erreur (issue #11)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from aiohttp.test_utils import TestClient, TestServer
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from tests.test_init import STATION, STATION_SANS_DEBIT, _build_app, _demarrer

VUE = yaml.safe_load((Path(__file__).parents[1] / "exemples" / "tableau-de-bord.yaml").read_text())
MARKDOWN = {c.get("title", ""): c["content"] for c in VUE["cards"] if c["type"] == "markdown"}


@pytest.fixture(autouse=True)
def _socket_autorise(socket_enabled):
    """Autorise le serveur HTTP local des tests."""
    yield


@pytest.fixture
async def client():
    test_client = TestClient(TestServer(_build_app()))
    await test_client.start_server()
    yield test_client
    await test_client.close()


def _rendre(hass: HomeAssistant, gabarit: str) -> str:
    return Template(gabarit, hass).async_render(parse_result=False)


async def test_rendu_deux_stations(hass: HomeAssistant, client: TestClient) -> None:
    hass.config.language = "fr"
    await _demarrer(hass, client, [STATION, STATION_SANS_DEBIT])
    niveaux = _rendre(hass, MARKDOWN["Niveaux des stations"])
    assert "**1.23 m**" in niveaux
    assert "5.7 m³/s" in niveaux
    lignes = [ligne for ligne in niveaux.splitlines() if ligne.startswith("|")]
    # En-tête, séparateur, puis une ligne par station : tableau Markdown valide.
    assert len(lignes) == 4
    assert all(ligne.count("|") == 6 for ligne in lignes)
    # Station sans débit : tiret à la place.
    assert lignes[3].split("|")[4].strip() == "—"
    fraicheur = _rendre(hass, MARKDOWN["Fraîcheur des mesures"])
    assert "mdi:" in fraicheur


async def test_rendu_sans_station(hass: HomeAssistant) -> None:
    assert "Aucune station suivie" in _rendre(hass, MARKDOWN["Niveaux des stations"])
    assert "Toutes les stations" in _rendre(hass, MARKDOWN["Fraîcheur des mesures"])


def test_cartes_integrees_uniquement() -> None:
    """Aucune carte personnalisée (custom:…) : rien à installer."""
    assert all(not c["type"].startswith("custom:") for c in VUE["cards"])

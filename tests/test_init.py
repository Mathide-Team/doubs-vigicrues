"""Tests de l'installation : capteurs, migration et indépendance des stations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vigicrues_hubeau.const import DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"
STATION = "U259999001"
STATION_SANS_DEBIT = "U259999002"
STATION_PANNE_H = "PANNEH"


def _lire(nom: str) -> str:
    return (FIXTURES / nom).read_text()


def _enregistrement_station(code: str) -> dict:
    """Enregistrement de référentiel avec le code demandé.

    Les codes de test inconnus reçoivent le code en suffixe du libellé :
    deux stations fictives doivent avoir des noms d'appareil distincts.
    """
    if code == STATION_SANS_DEBIT:
        enregistrement = json.loads(_lire("station_referentiel_sans_debit.json"))["data"][0]
    else:
        enregistrement = json.loads(_lire("station_referentiel.json"))["data"][0]
    enregistrement["code_station"] = code
    if code not in (STATION, STATION_SANS_DEBIT):
        enregistrement["libelle_station"] = f"{enregistrement['libelle_station']} [{code}]"
    return enregistrement


def _build_app(
    panne_station: dict | None = None,
    panne_referentiel: dict | None = None,
    blocage_referentiel: dict | None = None,
) -> web.Application:
    """Serveur factice reproduisant les routes Hub'Eau.

    ``panne_station`` (ex. ``{"code": "...", "actif": True}``) fait
    échouer toutes les requêtes d'observations de cette station tant que
    ``actif`` est vrai : le test peut y mettre fin pour la récupération.
    ``blocage_referentiel`` suspend la réponse du référentiel pour un
    code jusqu'à libération (test de concurrence).
    """

    async def referentiel(request: web.Request) -> web.Response:
        codes = request.query.getall("code_station", [])
        if blocage_referentiel and blocage_referentiel["actif"] and blocage_referentiel["code"] in codes:
            # Réponse suspendue jusqu'à libération : le second événement
            # prouve que le blocage est réellement atteint.
            blocage_referentiel["atteint"].set()
            await blocage_referentiel["evenement"].wait()
            blocage_referentiel["actif"] = False
        if panne_referentiel and panne_referentiel["actif"] and panne_referentiel["code"] in codes:
            return web.Response(status=500)
        enregistrements = [_enregistrement_station(c) for c in codes if c != "FANTOME"]
        return web.json_response(
            {
                "count": len(enregistrements),
                "first": "https://exemple.invalid/",
                "next": None,
                "prev": None,
                "data": enregistrements,
            }
        )

    async def observations(request: web.Request) -> web.Response:
        code = request.query.get("code_entite", "")
        grandeur = request.query.get("grandeur_hydro", "")
        if code == "PANNEQ" and grandeur == "Q":
            return web.Response(status=500)
        if code == "PANNEH2":
            # Hauteur en échec, débit valide : indépendance symétrique.
            if grandeur == "H":
                return web.Response(status=500)
            return web.json_response(json.loads(_lire("observations_q.json")))
        if code == "VIDEH":
            # Aucune hauteur mesurée, débit valide.
            if grandeur == "H":
                return web.json_response(json.loads(_lire("observations_vides.json")))
            return web.json_response(json.loads(_lire("observations_q.json")))
        if panne_station and code == panne_station["code"] and panne_station["actif"]:
            return web.Response(status=500)
        if code == "ANCIENNE" and grandeur == "H":
            return web.json_response(json.loads(_lire("observations_h_ancienne.json")))
        if code == STATION_SANS_DEBIT and grandeur == "H":
            return web.json_response(json.loads(_lire("observations_h_2.json")))
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


async def _demarrer(
    hass: HomeAssistant,
    client: TestClient,
    stations: list[str],
    version: int = 2,
    donnees: dict | None = None,
) -> MockConfigEntry:
    """Charge l'intégration en pointant Hub'Eau vers le serveur factice."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "custom_components.vigicrues_hubeau.api.BASE_URL",
            str(client.make_url("/")),
        )
        if donnees is None:
            donnees = {"stations": stations}
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=donnees,
            unique_id=",".join(sorted(stations)) if version >= 2 else stations[0],
            version=version,
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry


def _etat(hass: HomeAssistant, cle: str):
    """Cherche un capteur par la fin de son entity_id."""
    for entity_id in hass.states.async_entity_ids("sensor"):
        if entity_id.endswith(cle):
            return hass.states.get(entity_id)
    return None


async def test_capteurs(hass: HomeAssistant, client: TestClient) -> None:
    """Hauteur en m, débit en m³/s, attributs de fraîcheur."""
    hass.config.language = "fr"
    await _demarrer(hass, client, [STATION])
    hauteur = _etat(hass, "moulin_de_test_hauteur")
    assert hauteur is not None
    assert float(hauteur.state) == 1.234  # 1234 mm
    assert hauteur.attributes["date_observation"] == "2026-10-18T15:00:00+00:00"
    assert hauteur.attributes["continuite"] == "Continue"
    assert hauteur.attributes["commune"] == "EXEMPLEVILLE"
    assert hauteur.attributes["altitude_reference_m"] == 250.0
    # Coordonnées exposées pour la carte « map » (marqueur unique).
    assert hauteur.attributes["latitude"] == 47.2
    assert hauteur.attributes["longitude"] == 6.1
    debit = _etat(hass, "moulin_de_test_debit")
    assert debit is not None
    assert float(debit.state) == 5.678  # 5678 l/s
    assert debit.attributes["date_observation"] == "2026-10-18T15:00:00+00:00"
    # Un seul marqueur par station : pas de coordonnées sur le débit.
    assert "latitude" not in debit.attributes


async def test_capteurs_sans_debit(hass: HomeAssistant, client: TestClient) -> None:
    """Sans débit mesuré, la hauteur reste disponible."""
    hass.config.language = "fr"
    await _demarrer(hass, client, [STATION_SANS_DEBIT])
    hauteur = _etat(hass, "passerelle_de_test_hauteur")
    assert hauteur is not None
    assert float(hauteur.state) == 2.5
    debit = _etat(hass, "passerelle_de_test_debit")
    assert debit is not None
    assert debit.state == "unknown"  # station sans capteur de débit : pas de valeur


async def test_erreur_debit_independante(hass: HomeAssistant, client: TestClient) -> None:
    """Une erreur sur le débit n'empêche pas la hauteur."""
    hass.config.language = "fr"
    await _demarrer(hass, client, ["PANNEQ"])
    hauteur = _etat(hass, "moulin_de_test_panneq_hauteur")
    assert hauteur is not None
    assert float(hauteur.state) == 1.234
    debit = _etat(hass, "moulin_de_test_panneq_debit")
    assert debit is not None
    assert debit.state == "unknown"


async def test_observation_ancienne_conservee(hass: HomeAssistant, client: TestClient) -> None:
    """Une réponse réussie mais ancienne garde son horodatage d'origine."""
    hass.config.language = "fr"
    await _demarrer(hass, client, ["ANCIENNE"])
    hauteur = _etat(hass, "moulin_de_test_ancienne_hauteur")
    assert hauteur is not None
    assert float(hauteur.state) == 1.1
    # Pas de rajeunissement : la date d'origine est exposée telle quelle.
    assert hauteur.attributes["date_observation"] == "2026-09-01T06:00:00+00:00"


async def test_deux_stations(hass: HomeAssistant, client: TestClient) -> None:
    """Une entrée suit plusieurs stations : capteurs pour chacune."""
    hass.config.language = "fr"
    await _demarrer(hass, client, [STATION, STATION_SANS_DEBIT])
    moulin = _etat(hass, "moulin_de_test_hauteur")
    passerelle = _etat(hass, "passerelle_de_test_hauteur")
    assert moulin is not None
    assert passerelle is not None
    # Valeurs distinctes, attribuées à la bonne station.
    assert float(moulin.state) == 1.234
    assert float(passerelle.state) == 2.5


async def test_migration_v1(hass: HomeAssistant, client: TestClient) -> None:
    """Une entrée v1 (une station, clé « station ») migre sans casser les entités."""
    hass.config.language = "fr"
    entry = await _demarrer(hass, client, [STATION], version=1, donnees={"station": STATION})
    assert entry.version == 2
    assert entry.data == {"stations": [STATION]}
    hauteur = _etat(hass, "moulin_de_test_hauteur")
    assert hauteur is not None
    assert float(hauteur.state) == 1.234
    # L'appareil et l'identifiant unique sont inchangés.
    assert entry.unique_id == STATION


async def test_panne_station_independante(hass: HomeAssistant, client: TestClient) -> None:
    """La panne d'une station ne rend pas l'autre indisponible.

    La station PANNEH échoue à sa première mise à jour puis récupère :
    ses capteurs repassent disponibles au rafraîchissement suivant.
    """
    hass.config.language = "fr"
    panne = {"code": STATION_PANNE_H, "actif": True}
    serveur = TestClient(TestServer(_build_app(panne_station=panne)))
    await serveur.start_server()
    try:
        # Le patch de BASE_URL doit rester actif pour le rafraîchissement
        # de récupération : il englobe donc toute la suite du test.
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "custom_components.vigicrues_hubeau.api.BASE_URL",
                str(serveur.make_url("/")),
            )
            entry = MockConfigEntry(
                domain=DOMAIN,
                data={"stations": [STATION, STATION_PANNE_H]},
                unique_id=f"{STATION_PANNE_H},{STATION}",
                version=2,
            )
            entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            # La station saine expose ses valeurs…
            hauteur_saine = _etat(hass, "moulin_de_test_hauteur")
            assert hauteur_saine is not None
            assert float(hauteur_saine.state) == 1.234
            # … la station en panne reste indisponible, sans bloquer l'autre.
            hauteur_panne = _etat(hass, "moulin_de_test_panneh_hauteur")
            assert hauteur_panne is not None
            assert hauteur_panne.state == "unavailable"
            # La mise à jour suivante rétablit la station en panne.
            panne["actif"] = False
            coordinateur = entry.runtime_data[STATION_PANNE_H]
            await coordinateur.async_refresh()
            await hass.async_block_till_done()
            hauteur_panne = _etat(hass, "moulin_de_test_panneh_hauteur")
            assert hauteur_panne is not None
            assert float(hauteur_panne.state) == 1.234
    finally:
        await serveur.close()


async def test_station_disparue(hass: HomeAssistant, client: TestClient) -> None:
    """Une station disparue du référentiel ne bloque pas les autres."""
    hass.config.language = "fr"
    await _demarrer(hass, client, [STATION, "FANTOME"])
    hauteur = _etat(hass, "moulin_de_test_hauteur")
    assert hauteur is not None
    assert float(hauteur.state) == 1.234
    # Rien pour la station disparue.
    assert _etat(hass, "fantome_hauteur") is None


async def test_erreur_hauteur_independante(hass: HomeAssistant, client: TestClient) -> None:
    """Une erreur sur la hauteur n'empêche pas le débit (symétrie)."""
    hass.config.language = "fr"
    await _demarrer(hass, client, ["PANNEH2"])
    hauteur = _etat(hass, "moulin_de_test_panneh2_hauteur")
    assert hauteur is not None
    assert hauteur.state == "unknown"
    debit = _etat(hass, "moulin_de_test_panneh2_debit")
    assert debit is not None
    assert float(debit.state) == 5.678


async def test_position_sans_hauteur(hass: HomeAssistant, client: TestClient) -> None:
    """Sans mesure de hauteur, la position reste exposée pour la carte."""
    hass.config.language = "fr"
    await _demarrer(hass, client, ["VIDEH"])
    hauteur = _etat(hass, "moulin_de_test_videh_hauteur")
    assert hauteur is not None
    assert hauteur.state == "unknown"  # pas de mesure
    # Les coordonnées viennent des métadonnées : elles restent présentes.
    assert hauteur.attributes["latitude"] == 47.2
    assert hauteur.attributes["longitude"] == 6.1
    assert "date_observation" not in hauteur.attributes
    debit = _etat(hass, "moulin_de_test_videh_debit")
    assert debit is not None
    assert float(debit.state) == 5.678


async def test_referentiel_panne_partielle(hass: HomeAssistant, client: TestClient) -> None:
    """Un référentiel en échec pour une station ne bloque pas l'autre."""
    hass.config.language = "fr"
    serveur = TestClient(TestServer(_build_app(panne_referentiel={"code": "PANNEREF", "actif": True})))
    await serveur.start_server()
    try:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "custom_components.vigicrues_hubeau.api.BASE_URL",
                str(serveur.make_url("/")),
            )
            entry = MockConfigEntry(
                domain=DOMAIN,
                data={"stations": [STATION, "PANNEREF"]},
                unique_id=f"PANNEREF,{STATION}",
                version=2,
            )
            entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            hauteur = _etat(hass, "moulin_de_test_hauteur")
            assert hauteur is not None
            assert float(hauteur.state) == 1.234
            # Rien pour la station dont le référentiel a échoué.
            assert _etat(hass, "moulin_de_test_panneref_hauteur") is None
    finally:
        await serveur.close()


async def test_migration_conserve_personnalisation(hass: HomeAssistant, client: TestClient) -> None:
    """La migration v1 conserve les entity_id personnalisés du registre."""
    hass.config.language = "fr"
    from homeassistant.helpers import entity_registry as er

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "custom_components.vigicrues_hubeau.api.BASE_URL",
            str(client.make_url("/")),
        )
        entry = MockConfigEntry(domain=DOMAIN, data={"station": STATION}, unique_id=STATION, version=1)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registre = er.async_get(hass)
        entite = registre.async_get_entity_id("sensor", DOMAIN, f"{STATION}_hauteur")
        assert entite is not None
        # Personnalisation de l'entity_id : elle doit survivre à la
        # migration puis au rechargement.
        entite_id_perso = "sensor.ma_hauteur_perso"
        registre.async_update_entity(entite, new_entity_id=entite_id_perso)
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert registre.async_get_entity_id("sensor", DOMAIN, f"{STATION}_hauteur") == entite_id_perso
        assert hass.states.get(entite_id_perso) is not None
        assert float(hass.states.get(entite_id_perso).state) == 1.234


async def test_options_rechargent_les_capteurs(hass: HomeAssistant, client: TestClient) -> None:
    """Un retrait puis un ajout via les options s'applique aux capteurs.

    Le patch de BASE_URL doit rester actif pendant tout le test : le
    flux d'options valide lui aussi les codes auprès du référentiel.
    """
    hass.config.language = "fr"
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "custom_components.vigicrues_hubeau.api.BASE_URL",
            str(client.make_url("/")),
        )
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={"stations": [STATION, STATION_SANS_DEBIT]},
            unique_id=f"{STATION},{STATION_SANS_DEBIT}",
            version=2,
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        await _verifier_options(hass, entry)


async def _verifier_options(hass: HomeAssistant, entry) -> None:
    """Parcours d'options complet : retrait, purge, puis ajout."""
    from homeassistant.helpers import entity_registry as er

    registre = er.async_get(hass)
    assert _etat(hass, "moulin_de_test_hauteur") is not None
    assert _etat(hass, "passerelle_de_test_hauteur") is not None

    # Personnalisation d'un entity_id conservé : il doit survivre au
    # retrait d'une autre station.
    passerelle_id = registre.async_get_entity_id("sensor", DOMAIN, f"{STATION_SANS_DEBIT}_hauteur")
    assert passerelle_id is not None
    registre.async_update_entity(passerelle_id, new_entity_id="sensor.ma_passerelle")

    # Retrait de la station Moulin via les options.
    resultat = await hass.config_entries.options.async_init(entry.entry_id)
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"],
        {"stations": [STATION_SANS_DEBIT], "ajouter": False},
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    # Capteurs retirés : disparus des états ET du registre, appareil retiré.
    assert _etat(hass, "moulin_de_test_hauteur") is None
    assert registre.async_get_entity_id("sensor", DOMAIN, f"{STATION}_hauteur") is None
    assert registre.async_get_entity_id("sensor", DOMAIN, f"{STATION}_debit") is None
    from homeassistant.helpers import device_registry as dr

    registre_appareils = dr.async_get(hass)
    assert registre_appareils.async_get_device(identifiers={(DOMAIN, STATION)}) is None
    # Capteur conservé : présent, avec son entity_id personnalisé et sa valeur.
    assert _etat(hass, "ma_passerelle") is not None
    assert float(_etat(hass, "ma_passerelle").state) == 2.5
    assert (
        registre.async_get_entity_id("sensor", DOMAIN, f"{STATION_SANS_DEBIT}_hauteur")
        == "sensor.ma_passerelle"
    )

    # Ajout de la station retirée via les options : elle revient.
    resultat = await hass.config_entries.options.async_init(entry.entry_id)
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"],
        {"stations": [STATION_SANS_DEBIT], "ajouter": True},
    )
    resultat = await hass.config_entries.options.async_configure(
        resultat["flow_id"], {"stations": STATION, "chercher": False}
    )
    await hass.async_block_till_done()
    assert resultat["type"] is FlowResultType.CREATE_ENTRY
    assert _etat(hass, "moulin_de_test_hauteur") is not None
    assert float(_etat(hass, "moulin_de_test_hauteur").state) == 1.234
    assert _etat(hass, "ma_passerelle") is not None


async def test_station_en_attente_recuperee(hass: HomeAssistant, client: TestClient) -> None:
    """Une station en attente est réessayée puis prise en charge.

    Le référentiel de la station A échoue au démarrage (A mise en
    attente, B fonctionnelle) puis redevient disponible : sans
    rechargement ni redémarrage, A obtient ses capteurs et B reste
    fonctionnelle.
    """
    hass.config.language = "fr"
    panne = {"code": "PANNEREF", "actif": True}
    serveur = TestClient(TestServer(_build_app(panne_referentiel=panne)))
    await serveur.start_server()
    try:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "custom_components.vigicrues_hubeau.api.BASE_URL",
                str(serveur.make_url("/")),
            )
            entry = MockConfigEntry(
                domain=DOMAIN,
                data={"stations": [STATION, "PANNEREF"]},
                unique_id=f"PANNEREF,{STATION}",
                version=2,
            )
            entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            # B fonctionne, A est en attente (aucun capteur).
            assert _etat(hass, "moulin_de_test_hauteur") is not None
            assert float(_etat(hass, "moulin_de_test_hauteur").state) == 1.234
            assert _etat(hass, "moulin_de_test_panneref_hauteur") is None

            # Le référentiel de A redevient disponible : la nouvelle
            # tentative (normalement planifiée toutes les minutes) prend
            # A en charge sans recharger l'entrée.
            panne["actif"] = False
            donnees = hass.data[DOMAIN][entry.entry_id]
            assert donnees["en_attente"] == ["PANNEREF"]
            await donnees["retenter"]()
            await hass.async_block_till_done()
            hauteur = _etat(hass, "moulin_de_test_panneref_hauteur")
            assert hauteur is not None
            assert float(hauteur.state) == 1.234
            assert donnees["en_attente"] == []
            # B reste fonctionnelle.
            assert float(_etat(hass, "moulin_de_test_hauteur").state) == 1.234
    finally:
        await serveur.close()


async def test_migration_registre_preexistant(hass: HomeAssistant, client: TestClient) -> None:
    """La migration adopte les entités et appareils existants.

    Les registres contiennent déjà l'appareil et les capteurs de
    l'entrée 0.1.0 (avec un entity_id personnalisé) : après migration,
    ce sont les mêmes entrées de registre qui sont reprises, sans
    doublon.
    """
    hass.config.language = "fr"
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "custom_components.vigicrues_hubeau.api.BASE_URL",
            str(client.make_url("/")),
        )
        entry = MockConfigEntry(domain=DOMAIN, data={"station": STATION}, unique_id=STATION, version=1)
        entry.add_to_hass(hass)

        # Registres AVANT installation : appareil et capteur historiques.
        registre_appareils = dr.async_get(hass)
        appareil = registre_appareils.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, STATION)},
            name="Le Douby à Exempleville - Moulin de Test",
        )
        registre_entites = er.async_get(hass)
        entite = registre_entites.async_get_or_create(
            domain="sensor",
            platform=DOMAIN,
            unique_id=f"{STATION}_hauteur",
            config_entry=entry,
            suggested_object_id="ma_hauteur_perso",
        )
        assert entite.entity_id == "sensor.ma_hauteur_perso"

        # Installation : la migration v1 → v2 s'exécute.
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.version == 2

        # La même entité de registre est reprise, avec son entity_id
        # personnalisé et sa valeur ; pas de doublon créé.
        assert (
            registre_entites.async_get_entity_id("sensor", DOMAIN, f"{STATION}_hauteur") == entite.entity_id
        )
        assert hass.states.get("sensor.ma_hauteur_perso") is not None
        assert float(hass.states.get("sensor.ma_hauteur_perso").state) == 1.234
        # L'entrée de registre est la même, rattachée à la même entrée
        # de configuration et au même appareil.
        entite_apres = registre_entites.async_get(entite.entity_id)
        assert entite_apres is not None
        assert entite_apres.id == entite.id
        assert entite_apres.config_entry_id == entry.entry_id
        assert entite_apres.device_id == appareil.id
        # L'appareil historique est conservé.
        appareil_apres = registre_appareils.async_get_device(identifiers={(DOMAIN, STATION)})
        assert appareil_apres is not None
        assert appareil_apres.id == appareil.id


async def test_retentative_obsolete(hass: HomeAssistant, client: TestClient) -> None:
    """Un réessai rendu obsolète par un rechargement ne modifie rien.

    Le réessai de la station A attend sa réponse réseau ; les options
    retirent A et rechargent l'entrée ; la réponse arrive enfin : la
    tentative obsolète doit sortir sans créer les capteurs de A ni
    perturber les stations conservées.
    """
    import asyncio

    hass.config.language = "fr"
    panne = {"code": "PANNEREF", "actif": True}
    # Inactif à l'installation (le référentiel répond 500 vite) : le
    # blocage ne s'active que pour suspendre le réessai.
    blocage = {
        "code": "PANNEREF",
        "actif": False,
        "evenement": asyncio.Event(),
        "atteint": asyncio.Event(),
    }
    serveur = TestClient(TestServer(_build_app(panne_referentiel=panne, blocage_referentiel=blocage)))
    await serveur.start_server()
    try:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "custom_components.vigicrues_hubeau.api.BASE_URL",
                str(serveur.make_url("/")),
            )
            entry = MockConfigEntry(
                domain=DOMAIN,
                data={"stations": [STATION, "PANNEREF"]},
                unique_id=f"PANNEREF,{STATION}",
                version=2,
            )
            entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            assert _etat(hass, "moulin_de_test_hauteur") is not None

            # Le référentiel de A redevient disponible, mais la réponse
            # est suspendue : le réessai démarre et attend.
            panne["actif"] = False
            blocage["actif"] = True  # la réponse du réessai sera suspendue
            donnees = hass.data[DOMAIN][entry.entry_id]
            tache = asyncio.create_task(donnees["retenter"]())
            # Attendre que la tentative soit réellement suspendue sur la
            # réponse bloquée, pas un délai arbitraire.
            await asyncio.wait_for(blocage["atteint"].wait(), timeout=5)

            # Retrait de A pendant l'attente : rechargement, nouvelle
            # instance des données, purge (rien à purger pour A).
            resultat = await hass.config_entries.options.async_init(entry.entry_id)
            resultat = await hass.config_entries.options.async_configure(
                resultat["flow_id"],
                {"stations": [STATION], "ajouter": False},
            )
            await hass.async_block_till_done()

            assert resultat["type"] is FlowResultType.CREATE_ENTRY
            assert entry.data == {"stations": [STATION]}

            # La réponse suspendue arrive : la tentative obsolète doit
            # sortir sans créer les capteurs de A.

            blocage["evenement"].set()
            await tache

            await hass.async_block_till_done()
            assert _etat(hass, "moulin_de_test_panneref_hauteur") is None
            # La station conservée reste fonctionnelle.
            assert float(_etat(hass, "moulin_de_test_hauteur").state) == 1.234
    finally:
        await serveur.close()


async def test_station_en_attente_temporisation(hass: HomeAssistant, client: TestClient) -> None:
    """La temporisation planifiée reprend les stations en attente.

    Le réessai périodique (60 s) est déclenché par l'horloge de test :
    la station en attente obtient ses capteurs sans aucune intervention.
    """
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    hass.config.language = "fr"
    panne = {"code": "PANNEREF", "actif": True}
    serveur = TestClient(TestServer(_build_app(panne_referentiel=panne)))
    await serveur.start_server()
    try:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(
                "custom_components.vigicrues_hubeau.api.BASE_URL",
                str(serveur.make_url("/")),
            )
            entry = MockConfigEntry(
                domain=DOMAIN,
                data={"stations": [STATION, "PANNEREF"]},
                unique_id=f"PANNEREF,{STATION}",
                version=2,
            )
            entry.add_to_hass(hass)
            assert await hass.config_entries.async_setup(entry.entry_id)
            await hass.async_block_till_done()
            assert _etat(hass, "moulin_de_test_panneref_hauteur") is None

            # Le référentiel redevient disponible : la temporisation de
            # 60 secondes déclenchée par l'horloge doit tout reprendre.
            panne["actif"] = False
            async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
            await hass.async_block_till_done()
            hauteur = _etat(hass, "moulin_de_test_panneref_hauteur")
            assert hauteur is not None
            assert float(hauteur.state) == 1.234
            assert float(_etat(hass, "moulin_de_test_hauteur").state) == 1.234
    finally:
        await serveur.close()

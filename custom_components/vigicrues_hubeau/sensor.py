"""Capteurs de hauteur et de débit des stations Vigicrues."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength, UnitOfVolumeFlowRate
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .coordinator import StationData, VigicruesCoordinator

if TYPE_CHECKING:
    from . import VigicruesConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VigicruesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée les capteurs de chaque station suivie par l'entrée."""
    LOGGER.debug("async_setup_entry() (capteurs) appelé")
    coordinateurs: dict[str, VigicruesCoordinator] = entry.runtime_data
    entites = []
    for coordinateur in coordinateurs.values():
        entites.append(
            VigicruesHauteurSensor(coordinateur),
        )
        entites.append(
            VigicruesDebitSensor(coordinateur),
        )
    async_add_entities(entites)
    LOGGER.debug("async_setup_entry() (capteurs) retourne | %s entité(s)", len(entites))
    # La plateforme publie sa fonction d'ajout : les stations résolues
    # plus tard (référentiel indisponible au démarrage) pourront créer
    # leurs capteurs sans recharger l'entrée.
    hass.data[DOMAIN][entry.entry_id]["ajouter_entites"] = async_add_entities
    LOGGER.debug("async_setup_entry() (capteurs) a publié sa fonction d'ajout")


def _informations_station(
    coordinateur: VigicruesCoordinator,
) -> DeviceInfo:
    """Appareil portant le nom réel de la station."""
    LOGGER.debug("_informations_station() appelé | code=%s", coordinateur.station.code)
    station = coordinateur.station
    LOGGER.debug("_informations_station() retourne les infos de l'appareil")
    return DeviceInfo(
        identifiers={(DOMAIN, station.code)},
        name=station.libelle,
        manufacturer="Vigicrues (Hub'Eau)",
        model=station.cours_eau or "Station hydrométrique",
        configuration_url="https://www.vigicrues.gouv.fr",
    )


class VigicruesHauteurSensor(CoordinatorEntity[VigicruesCoordinator], SensorEntity):
    """Hauteur d'eau en mètres (échelle de la station)."""

    _attr_has_entity_name = True
    _attr_translation_key = "hauteur"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VigicruesCoordinator) -> None:
        LOGGER.debug("VigicruesHauteurSensor.__init__() appelé | code=%s", coordinator.code)
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.code}_hauteur"
        self._attr_device_info = _informations_station(coordinator)
        LOGGER.debug("VigicruesHauteurSensor.__init__() retourne")

    @property
    def native_value(self) -> float | None:
        """Dernière hauteur, convertie de mm en m ; None si aucune mesure."""
        LOGGER.debug("native_value() (hauteur) appelé")
        if self.coordinator.data is None or self.coordinator.data.hauteur is None:
            LOGGER.debug("native_value() (hauteur) retourne None")
            return None
        LOGGER.debug("native_value() (hauteur) retourne la mesure")
        return self.coordinator.data.hauteur.resultat / 1000

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Contexte de la station et de la dernière mesure de hauteur.

        Les attributs géographiques (commune, cours d'eau, altitude,
        coordonnées) viennent des métadonnées de la station : ils restent
        présents même sans mesure de hauteur. La date et la continuité
        ne sont exposées que lorsqu'une observation existe.

        La latitude et la longitude sont exposées sur ce seul capteur (et
        pas sur le débit) : la carte « map » de Home Assistant affiche
        ainsi un marqueur unique par station.
        """
        LOGGER.debug("extra_state_attributes() (hauteur) appelé")
        station = self.coordinator.station
        attributs: dict[str, object] = {
            "commune": station.commune,
            "cours_eau": station.cours_eau,
            "altitude_reference_m": station.altitude,
        }
        if station.latitude is not None and station.longitude is not None:
            attributs["latitude"] = station.latitude
            attributs["longitude"] = station.longitude
        data: StationData | None = self.coordinator.data
        if data is not None and data.hauteur is not None:
            attributs["date_observation"] = data.hauteur.date_obs.isoformat()
            attributs["continuite"] = data.hauteur.continuite
        LOGGER.debug("extra_state_attributes() (hauteur) retourne %s attribut(s)", len(attributs))
        return attributs


class VigicruesDebitSensor(CoordinatorEntity[VigicruesCoordinator], SensorEntity):
    """Débit en m³/s ; indisponible si la station ne mesure pas le débit."""

    _attr_has_entity_name = True
    _attr_translation_key = "debit"
    _attr_native_unit_of_measurement = UnitOfVolumeFlowRate.CUBIC_METERS_PER_SECOND
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: VigicruesCoordinator) -> None:
        LOGGER.debug("VigicruesDebitSensor.__init__() appelé | code=%s", coordinator.code)
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.code}_debit"
        self._attr_device_info = _informations_station(coordinator)
        LOGGER.debug("VigicruesDebitSensor.__init__() retourne")

    @property
    def native_value(self) -> float | None:
        """Dernier débit, converti de l/s en m³/s ; None si aucune mesure."""
        LOGGER.debug("native_value() (débit) appelé")
        if self.coordinator.data is None or self.coordinator.data.debit is None:
            LOGGER.debug("native_value() (débit) retourne None")
            return None
        LOGGER.debug("native_value() (débit) retourne la mesure")
        return self.coordinator.data.debit.resultat / 1000

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Date et continuité de la dernière mesure de débit."""
        LOGGER.debug("extra_state_attributes() (débit) appelé")
        data: StationData | None = self.coordinator.data
        if data is None or data.debit is None:
            LOGGER.debug("extra_state_attributes() (débit) retourne un dictionnaire vide")
            return {}
        LOGGER.debug("extra_state_attributes() (débit) retourne les attributs")
        return {
            "date_observation": data.debit.date_obs.isoformat(),
            "continuite": data.debit.continuite,
            "commune": data.station.commune,
            "cours_eau": data.station.cours_eau,
        }

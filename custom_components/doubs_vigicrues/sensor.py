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

from .const import DOMAIN
from .coordinator import DoubsVigicruesCoordinator, StationData

if TYPE_CHECKING:
    from . import DoubsVigicruesConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DoubsVigicruesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée les capteurs de chaque station suivie par l'entrée."""
    coordinateurs: dict[str, DoubsVigicruesCoordinator] = entry.runtime_data
    entites = []
    for coordinateur in coordinateurs.values():
        entites.append(
            DoubsVigicruesHauteurSensor(coordinateur),
        )
        entites.append(
            DoubsVigicruesDebitSensor(coordinateur),
        )
    async_add_entities(entites)
    # La plateforme publie sa fonction d'ajout : les stations résolues
    # plus tard (référentiel indisponible au démarrage) pourront créer
    # leurs capteurs sans recharger l'entrée.
    hass.data[DOMAIN][entry.entry_id]["ajouter_entites"] = async_add_entities


def _informations_station(
    coordinateur: DoubsVigicruesCoordinator,
) -> DeviceInfo:
    """Appareil portant le nom réel de la station."""
    station = coordinateur.station
    return DeviceInfo(
        identifiers={(DOMAIN, station.code)},
        name=station.libelle,
        manufacturer="Vigicrues (Hub'Eau)",
        model=station.cours_eau or "Station hydrométrique",
        configuration_url="https://www.vigicrues.gouv.fr",
    )


class DoubsVigicruesHauteurSensor(CoordinatorEntity[DoubsVigicruesCoordinator], SensorEntity):
    """Hauteur d'eau en mètres (échelle de la station)."""

    _attr_has_entity_name = True
    _attr_translation_key = "hauteur"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DoubsVigicruesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.code}_hauteur"
        self._attr_device_info = _informations_station(coordinator)

    @property
    def native_value(self) -> float | None:
        """Dernière hauteur, convertie de mm en m ; None si aucune mesure."""
        if self.coordinator.data is None or self.coordinator.data.hauteur is None:
            return None
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
        return attributs


class DoubsVigicruesDebitSensor(CoordinatorEntity[DoubsVigicruesCoordinator], SensorEntity):
    """Débit en m³/s ; indisponible si la station ne mesure pas le débit."""

    _attr_has_entity_name = True
    _attr_translation_key = "debit"
    _attr_native_unit_of_measurement = UnitOfVolumeFlowRate.CUBIC_METERS_PER_SECOND
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DoubsVigicruesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.code}_debit"
        self._attr_device_info = _informations_station(coordinator)

    @property
    def native_value(self) -> float | None:
        """Dernier débit, converti de l/s en m³/s ; None si aucune mesure."""
        if self.coordinator.data is None or self.coordinator.data.debit is None:
            return None
        return self.coordinator.data.debit.resultat / 1000

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Date et continuité de la dernière mesure de débit."""
        data: StationData | None = self.coordinator.data
        if data is None or data.debit is None:
            return {}
        return {
            "date_observation": data.debit.date_obs.isoformat(),
            "continuite": data.debit.continuite,
            "commune": data.station.commune,
            "cours_eau": data.station.cours_eau,
        }

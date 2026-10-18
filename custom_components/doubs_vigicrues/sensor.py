"""Capteurs de hauteur et de débit d'une station Vigicrues."""

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
    from homeassistant.config_entries import ConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crée les capteurs de la station de l'entrée."""
    coordinator: DoubsVigicruesCoordinator = entry.runtime_data
    async_add_entities(
        [
            DoubsVigicruesHauteurSensor(coordinator),
            DoubsVigicruesDebitSensor(coordinator),
        ]
    )


def _informations_station(
    data: StationData,
) -> DeviceInfo:
    """Appareil portant le nom réel de la station."""
    return DeviceInfo(
        identifiers={(DOMAIN, data.station.code)},
        name=data.station.libelle,
        manufacturer="Vigicrues (Hub'Eau)",
        model=data.station.cours_eau or "Station hydrométrique",
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
        self._attr_device_info = _informations_station(coordinator.data)

    @property
    def native_value(self) -> float | None:
        """Dernière hauteur, convertie de mm en m ; None si aucune mesure."""
        if self.coordinator.data is None or self.coordinator.data.hauteur is None:
            return None
        return self.coordinator.data.hauteur.resultat / 1000

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Date, continuité et contexte de la dernière mesure."""
        data = self.coordinator.data
        if data is None or data.hauteur is None:
            return {}
        return {
            "date_observation": data.hauteur.date_obs.isoformat(),
            "continuite": data.hauteur.continuite,
            "commune": data.station.commune,
            "cours_eau": data.station.cours_eau,
            "altitude_reference_m": data.station.altitude,
        }


class DoubsVigicruesDebitSensor(CoordinatorEntity[DoubsVigicruesCoordinator], SensorEntity):
    """Débit en m³/s ; indisponible si la station ne mesure pas le débit."""

    _attr_has_entity_name = True
    _attr_translation_key = "debit"
    _attr_native_unit_of_measurement = UnitOfVolumeFlowRate.CUBIC_METERS_PER_SECOND
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: DoubsVigicruesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.code}_debit"
        self._attr_device_info = _informations_station(coordinator.data)

    @property
    def native_value(self) -> float | None:
        """Dernier débit, converti de l/s en m³/s ; None si aucune mesure."""
        if self.coordinator.data is None or self.coordinator.data.debit is None:
            return None
        return self.coordinator.data.debit.resultat / 1000

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Date et continuité de la dernière mesure de débit."""
        data = self.coordinator.data
        if data is None or data.debit is None:
            return {}
        return {
            "date_observation": data.debit.date_obs.isoformat(),
            "continuite": data.debit.continuite,
            "commune": data.station.commune,
            "cours_eau": data.station.cours_eau,
        }

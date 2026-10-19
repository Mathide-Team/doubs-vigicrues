"""Constantes de l'intégration Vigicrues (niveaux des cours d'eau)."""

from __future__ import annotations

import logging

DOMAIN = "vigicrues_hubeau"
LOGGER = logging.getLogger(__name__)

# Le Doubs à Besançon - Moulin Saint-Paul (référentiel Hub'Eau),
# simple suggestion initiale : n'importe quelle station Vigicrues peut
# être suivie.
DEFAULT_STATION = "U251201001"

# Schéma v1 (une entrée = une station, clé « station »).
CONF_STATION = "station"
# Schéma v2 : liste de stations suivies par l'entrée.
CONF_STATIONS = "stations"

# Rafraîchissement : les stations Vigicrues mesurent toutes les 5 à 60 min.
UPDATE_INTERVAL_MIN = 15

# Grandeurs hydrométriques Hub'Eau.
GRANDEUR_HAUTEUR = "H"
GRANDEUR_DEBIT = "Q"

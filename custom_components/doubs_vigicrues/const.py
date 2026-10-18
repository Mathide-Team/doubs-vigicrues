"""Constantes de l'intégration Niveau du Doubs (Vigicrues)."""

from __future__ import annotations

import logging

DOMAIN = "doubs_vigicrues"
LOGGER = logging.getLogger(__name__)

# Le Doubs à Besançon - Moulin Saint-Paul (référentiel Hub'Eau).
DEFAULT_STATION = "U251201001"

CONF_STATION = "station"

# Rafraîchissement : les stations Vigicrues mesurent toutes les 5 à 60 min.
UPDATE_INTERVAL_MIN = 15

# Grandeurs hydrométriques Hub'Eau.
GRANDEUR_HAUTEUR = "H"
GRANDEUR_DEBIT = "Q"

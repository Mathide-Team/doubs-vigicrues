# Journal des versions

## [0.2.0] — 18/10/2026

- Une entrée suit désormais **plusieurs stations** : codes séparés par
  des virgules ou des espaces à la configuration, ajout et retrait dans
  les options. Migration automatique des entrées 0.1.0 (appareils et
  capteurs conservés).
- **Recherche de stations** par nom de cours d'eau (partiel accepté)
  ou code INSEE de commune, avec sélection multiple.
- **Carte des stations** : le capteur de hauteur expose les attributs
  `latitude`/`longitude` — la carte « map » de Home Assistant affiche
  un marqueur par station.
- Indépendance renforcée : la panne d'une station ne rend pas les
  autres indisponibles, et une station disparue du référentiel est
  ignorée sans bloquer l'entrée.

## [0.1.0] — 18/10/2026

- Version initiale : hauteur d'eau (m) et débit (m³/s) d'une station
  hydrométrique Vigicrues, par défaut le Doubs à Besançon - Moulin
  Saint-Paul (`U251201001`), via l'API Hubeau (sans clé).
- Configuration par code de station, avec validation du libellé réel.
- Attributs : date de l'observation (UTC), continuité de la mesure,
  commune, cours d'eau et altitude de référence de la station.

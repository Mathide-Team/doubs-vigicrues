# Journal des versions

## [0.3.1] — 22/10/2026

- Réponses JSON invalides de Hub'Eau désormais journalisées.
- Journal de debug complet (SOCLE §8) : entrée et sortie de chaque
  fonction de l'intégration tracées ; scripts journalisés avec loguru.
- Avis en tête du README : développement arrêté le 20/10/2026, sources
  conservées.
- Tests : couverture 99,4 % lignes et branches, seuil bloquant à 95 % (#22).

## [0.3.0] — 19/10/2026

- **Renommage** : l'intégration s'appelle « Vigicrues (niveaux des cours
  d'eau) », domaine `vigicrues_hubeau`, dépôt `Mathilde-Team/Vigicrues`
  (#10). Toute station hydrométrique Vigicrues de France peut être suivie.
  **Changement incompatible** : supprimer l'ancienne entrée
  `doubs_vigicrues` et ajouter la nouvelle intégration (voir « Migration
  depuis doubs-vigicrues » dans le README).
- Tableau de bord d'exemple : niveaux, fraîcheur des mesures, courbe et
  carte (#11).
- Release : notes de version vérifiées en CI, workflow avec le Python de
  uv (#7, #13).

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

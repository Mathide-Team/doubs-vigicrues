# Niveau du Doubs (Vigicrues)

Intégration Home Assistant pour suivre la **hauteur** et le **débit** du
Doubs (ou de n'importe quelle station hydrométrique Vigicrues), par défaut
la station **Le Doubs à Besançon - Moulin Saint-Paul**.

Les données proviennent de l'API publique
[Hub'Eau](https://hubeau.eaufrance.fr/page/api-hydrometrie) (plateforme
nationale d'accès aux données sur l'eau, service Vigicrues/SCHAPI) : aucune
clé ni compte n'est nécessaire.

## Fonctionnalités

- **Hauteur d'eau** (m) : dernière observation temps réel de la station,
  rafraîchie toutes les 15 minutes.
- **Débit** (m³/s) : disponible selon la station ; son absence ne rend pas
  la hauteur indisponible.
- Attributs de chaque capteur : date de l'observation (UTC), continuité de
  la mesure, commune, cours d'eau et altitude de référence de la station.
- Choix de la station par son code Vigicrues (le libellé réel est vérifié
  à la configuration). La valeur 0 ou négative est conservée telle quelle :
  c'est une mesure, pas un défaut.
- La hauteur est l'échelle limnimétrique de la station (référence locale),
  pas la profondeur du Doubs.

## Installation

### HACS (recommandé)

1. Ajoutez ce dépôt dans HACS (« Dépôts personnalisés », catégorie
   « Intégration »).
2. Recherchez « Niveau du Doubs (Vigicrues) » et installez-la.
3. Redémarrez Home Assistant.

### Manuel

Copiez le dossier `custom_components/doubs_vigicrues` dans le dossier
`custom_components` de votre installation, puis redémarrez Home Assistant.

## Configuration

1. Ajoutez l'intégration « Niveau du Doubs (Vigicrues) ».
2. Renseignez le code de la station (prérempli avec `U251201001`,
   Le Doubs à Besançon - Moulin Saint-Paul). Les codes d'autres stations
   sont consultables sur
   [Hub'Eau](https://hubeau.eaufrance.fr/page/api-hydrometrie) ou
   [Vigicrues](https://www.vigicrues.gouv.fr).
3. Les capteurs apparaissent sur l'appareil portant le nom de la station.

Une entrée par station : ajoutez l'intégration plusieurs fois pour suivre
plusieurs stations.

## Sources

- API utilisée : [Hub'Eau Hydrométrie v2](https://hubeau.eaufrance.fr/page/api-hydrometrie)
  (observations temps réel H en mm et Q en l/s, converties en m et m³/s ;
  fenêtre glissante du dernier mois).
- Données produites par le service Vigicrues (SCHAPI) via la plateforme
  PHyC.

## Développement

Socle qualité Mathide-Team : CI (ruff, yamllint, pytest, hassfest, HACS),
branches protégées `dev` → `main`.

```bash
uv run -p 3.13 --only-group test pytest -q   # tests
uv run --only-group lint ruff check .        # lint
```

# Vigicrues (niveaux des cours d'eau)

Intégration Home Assistant pour suivre la **hauteur** et le **débit** de
**n'importe quelle station hydrométrique Vigicrues en France**, une ou
plusieurs par entrée, avec recherche par cours d'eau ou par commune. La
station **Le Doubs à Besançon - Moulin Saint-Paul** est seulement la
suggestion initiale du formulaire.

> Anciennement « Niveau du Doubs (Vigicrues) » (`doubs_vigicrues`,
> dépôt `doubs-vigicrues`) : voir [Migration depuis doubs-vigicrues](#migration-depuis-doubs-vigicrues).

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
- **Plusieurs stations par entrée** : codes séparés par des virgules ou
  des espaces, ou recherche par nom de cours d'eau (partiel accepté) ou
  code INSEE de commune. Les options permettent d'ajouter et de retirer
  des stations sans tout reconfigurer.
- **Carte des stations** : le capteur de hauteur porte les attributs
  `latitude`/`longitude` de sa station — la [carte « map »](https://www.home-assistant.io/dashboards/map/)
  de Home Assistant affiche un marqueur par station (voir plus bas).
- Choix de la station par son code Vigicrues (le libellé réel est vérifié
  à la configuration). La valeur 0 ou négative est conservée telle quelle :
  c'est une mesure, pas un défaut.
- La hauteur est l'échelle limnimétrique de la station (référence locale),
  pas la profondeur du cours d'eau.

## Installation

### HACS (recommandé)

1. Ajoutez ce dépôt dans HACS (« Dépôts personnalisés », catégorie
   « Intégration »).
2. Recherchez « Vigicrues (niveaux des cours d'eau) » et installez-la.
3. Redémarrez Home Assistant.

### Manuel

Copiez le dossier `custom_components/vigicrues_hubeau` dans le dossier
`custom_components` de votre installation, puis redémarrez Home Assistant.

## Configuration

1. Ajoutez l'intégration « Vigicrues (niveaux des cours d'eau) ».
2. Renseignez un ou plusieurs codes de stations (prérempli avec
   `U251201001`, Le Doubs à Besançon - Moulin Saint-Paul), séparés par
   des virgules ou des espaces — ou cochez « Chercher » pour trouver
   des stations par nom de cours d'eau ou code INSEE de commune. Les
   codes d'autres stations sont consultables sur
   [Hub'Eau](https://hubeau.eaufrance.fr/page/api-hydrometrie) ou
   [Vigicrues](https://www.vigicrues.gouv.fr).
3. Les capteurs apparaissent sur un appareil par station, portant le nom
   réel de la station.
4. Dans les options de l'intégration : désélectionnez une station pour
   la retirer, cochez « Ajouter » pour en ajouter d'autres.

Les entrées créées en 0.1.0 (une entrée par station) sont migrées
automatiquement : appareils, capteurs et personnalisations sont conservés.

## Carte des stations

Chaque capteur de hauteur expose `latitude` et `longitude` : la carte
« map » intégrée affiche donc toutes vos stations suivies.

```yaml
type: map
entities:
  - sensor.le_doubs_a_besancon_moulin_saint_paul_hauteur
  - sensor.le_doubs_a_mouthe_hauteur
```

Un seul marqueur par station : le capteur de débit ne porte pas les
coordonnées.

## Tableau de bord

Une vue prête à l'emploi est fournie dans
[`exemples/tableau-de-bord.yaml`](exemples/tableau-de-bord.yaml) :

- **niveaux des stations** : tableau station, cours d'eau, hauteur, débit
  et ancienneté de la mesure, pour toutes les stations suivies (rien à
  adapter) ;
- **fraîcheur des mesures** : signale les stations sans mesure depuis
  plus de 3 heures ;
- **courbe des hauteurs sur 48 h** et **carte des stations** : remplacer
  les capteurs d'exemple par les vôtres.

Seules des cartes intégrées à Home Assistant sont utilisées. Installation :
Paramètres → Tableaux de bord → ouvrir un tableau de bord → ⋮ → Modifier
→ ⋮ → Éditeur de configuration, puis coller le contenu du fichier comme
nouvel élément de `views:`.

## Migration depuis doubs-vigicrues

La version 0.3.0 renomme l'intégration (domaine `vigicrues_hubeau`) : Home
Assistant la voit comme une **nouvelle intégration**.

1. Supprimez l'entrée « Niveau du Doubs (Vigicrues) » (Paramètres →
   Appareils et services) et, avec HACS, le dépôt `doubs-vigicrues`.
2. Ajoutez le dépôt `Mathilde-Team/Vigicrues` dans HACS, installez
   « Vigicrues (niveaux des cours d'eau) » et redémarrez.
3. Ajoutez l'intégration avec les mêmes codes de station. Les entités
   gardent les mêmes noms (`sensor.<station>_hauteur`, `…_debit`) ;
   l'historique des anciennes entités n'est pas repris.

Le domaine n'est pas `vigicrues` pour ne pas entrer en conflit avec
l'intégration HACS [julcollas/hass-vigicrues](https://github.com/julcollas/hass-vigicrues),
qui l'utilise déjà : les deux peuvent être installées ensemble.

## Sources

- API utilisée : [Hub'Eau Hydrométrie v2](https://hubeau.eaufrance.fr/page/api-hydrometrie)
  (observations temps réel H en mm et Q en l/s, converties en m et m³/s ;
  fenêtre glissante du dernier mois).
- Données produites par le service Vigicrues (SCHAPI) via la plateforme
  PHyC.

## Développement

Socle qualité Mathilde-Team : CI (ruff, yamllint, pytest, hassfest, HACS),
branches protégées `dev` → `main`.

```bash
uv run -p 3.13 --only-group test pytest -q   # tests
uv run --only-group lint ruff check .        # lint
```

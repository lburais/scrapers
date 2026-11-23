# scrapers

Des outils Python pour archiver des profils **FindPenguins** ou **Polarsteps** et des listes Apple Reminders, puis générer séparément des articles reStructuredText pour Pelican.

Les scrapers authentifient et téléchargent les données et médias, puis génèrent des archives **GPX**, **XML** et JSON ; `aventures2rst.py` les convertit en sources Pelican. `reminder.py` prépare une commande **rem** à exécuter manuellement ; `reminders2rst.py` génère un article par rappel exporté.

---

## ✨ Fonctionnalités

- **Extraction Complète :** Récupération de la biographie de l'utilisateur, de la liste des voyages, des étapes (*footprints*), récits, dates, altitudes et relevés météo.
- **Authentification :** session HTTP puis Chromium pour FindPenguins ; connexion Chromium et API Polarsteps pour Polarsteps.
- **Hébergement Multi-Profils :** Possibilité de scraper plusieurs comptes d'un coup avec fusion automatique des indexes.
- **Export de Données Géographiques :** 
  - Restitution d'un fichier **GPX 1.1** standardisé par voyage avec intégration des waypoints et métadonnées enrichies.
  - Enrichissement optionnel des altitudes des traces via des API topographiques externes (SRTM90m).
- **Export Pelican (reStructuredText) :**
  - Génération d'un fichier `trip.rst` par voyage et d'un `footprint.rst` par étape. Il n'y a pas de page RST de profil.
  - Chaque voyage avec une trace valide peut inclure une carte de route WebP, avec fond configurable et bulles de photos pour les étapes.
  - Métadonnées Pelican en champ reStructuredText, avec une image de la carte du pays enregistrée dans le dossier de chaque *footprint* géolocalisé.
  - Les métadonnées des voyages alimentent l'index généré par le site Pelican; les sources contiennent les photos, vidéos, cartes et références des étapes.

---

## 📂 Architecture du Projet

Le projet est structuré de manière hautement modulaire :

```text
├── scrapers.py              # Point d'entrée CLI et sélection du programme
├── findpenguins.py          # Orchestrateur FindPenguins
├── polarsteps.py            # Archive Polarsteps par API et connexion automatique ou interactive
├── polarsteps_config.py     # Endpoints, version de l'API et météo Polarsteps
├── polarsteps_utils.py      # Connexion, accès API et téléchargement des médias
├── polarsteps_parsers.py    # Normalisation des trajets et parsing des données API
├── aventures2rst.py         # Conversion des archives en articles Pelican
├── reminder.py              # Préparation d'un export Apple Reminders via rem
├── reminders2rst.py         # Conversion des rappels en articles Pelican
├── output_safety.py         # Nettoyage --force et validation des chemins
├── build_scrapers.sh        # Construction de l'exécutable PyApp
├── docs/                    # Documentation technique (dont api-reference.md)
├── findpenguins_config.py   # Endpoints et en-têtes HTTP FindPenguins
├── findpenguins_utils.py    # Navigation Playwright, cookies et téléchargements
├── findpenguins_parsers.py  # Extraction des données et parsing DOM
├── aventures_archive.py    # Lecture des manifestes pour la conversion
├── aventures_writers.py    # Génération des articles Pelican et cartes de pays
├── common_archive.py       # Écriture des manifestes JSON portables
├── common_config.py        # Espaces de noms XML partagés
├── common_elevation.py     # Enrichissement topographique des traces GPX
├── common_profiles.py      # Profils et comptes partagés entre les services
├── common_writers.py       # Génération GPX, XML et cartes de route
├── common_utils.py         # Utilitaires XML, texte et images partagés
└── profiles.json            # Profils, identifiants et réglages
```

La documentation technique complémentaire se trouve dans [`docs/`](docs/), notamment la
[référence de toutes les fonctions](docs/api-reference.md).

---

## 🚀 Prérequis et Installation

Python 3.10 ou plus récent est nécessaire. Pour installer depuis le dépôt :

```bash
git clone https://github.com/lburais/scrapers.git
cd scrapers
python3 -m venv venv
source venv/bin/activate
python -m pip install -e .
```

Les dépendances sont déclarées dans `pyproject.toml` ; `pip install -r requirements.txt`
installe également le projet en mode éditable. L'installation fournit la seule commande
`scrapers`, avec les sous-commandes `aventures`, `findpenguins`, `polarsteps`, `aventures2rst`, `reminder`
et `reminders2rst`. On peut aussi utiliser `python -m scrapers` ou, depuis le
dépôt, `python scrapers.py`. Sans sous-commande, l'aide est affichée.

Après publication sur PyPI sous un nom disponible, l'installation pourra aussi
se faire avec `python -m pip install <nom-de-distribution>`.

### Initialiser Playwright
Le projet utilise Chromium pour FindPenguins et pour l'authentification Polarsteps :
```bash
python -m playwright install chromium
```

Pour les rappels, installer [rem](https://github.com/BRO3886/rem) et autoriser
l'accès à Reminders dans les réglages macOS. Les commandes de conversion n'ont
pas besoin d'accéder aux comptes sources.

### Construire et distribuer

Construire le wheel et l'archive source, puis vérifier leur contenu avant publication :

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

Le nom de distribution est `scrapers`, déjà utilisé par un autre projet sur PyPI :
choisir un nom disponible et modifier `project.name` avant publication. Aucun identifiant, fichier
de profils ni archive de données n'est inclus dans les distributions.

Pour tester le wheel construit depuis le dépôt :

```bash
SCRAPERS_TEST_WHEEL="$(pwd)/dist/scrapers-0.1.0-py3-none-any.whl" \
SCRAPERS_TEST_SDIST="$(pwd)/dist/scrapers-0.1.0.tar.gz" \
python -m unittest discover -s tests -v
```

Adapter les noms des fichiers à la version construite. Les tests installent le wheel
et ses dépendances dans un environnement temporaire et lancent les commandes hors
du dépôt ; cette installation nécessite un accès aux paquets.

### Exécutable PyApp

[PyApp](https://ofek.dev/pyapp/latest/) produit un exécutable unique. Avec
Rust/Cargo installé, construire le wheel comme ci-dessus, puis télécharger et
décompresser les sources PyApp selon son [guide](https://ofek.dev/pyapp/latest/how-to/).
Depuis le dossier des sources PyApp, exécuter le script du dépôt en remplaçant le
chemin du script et, si nécessaire, celui du wheel :

```bash
/chemin/vers/scrapers/build_scrapers.sh /chemin/absolu/scrapers-0.1.0-py3-none-any.whl
./executables/scrapers --help
```

Cet exemple et le script concernent macOS/Linux ; Windows produit `pyapp.exe`.
Le wheel est intégré à l'exécutable, mais PyApp télécharge Python et installe les
dépendances au premier lancement : une connexion réseau est donc nécessaire.
Pour préparer Chromium dans l'environnement PyApp avant une collecte :

```bash
./executables/scrapers self python -m playwright install chromium
```

`rem` et l'autorisation macOS restent nécessaires pour les rappels. Les chemins
par défaut des archives et articles sont relatifs au dossier courant, pas à
l'emplacement de l'exécutable.

---

## ⚙️ Utilisation

```bash
scrapers aventures profiles.json [--output DIR] [--content DIR] [--force] [--skip]
scrapers findpenguins profiles.json [--output DIR] [-t SLUG] [--force] [--skip]
scrapers polarsteps profiles.json [--output DIR] [-t SLUG] [--force] [--skip]
scrapers aventures2rst --output DIR [--content DIR] [-t SLUG] [--category CATEGORY]
```

- `profiles.json` : fichier de profils (obligatoire).
- `--output` : archive JSON, XML, GPX et médias (défaut `output` pour les deux programmes).
- `--content` : destination des articles Pelican du convertisseur (défaut `../website/content/articles/findpenguins`).
- `--category` : catégorie des articles de voyage et premier tag de service (défaut `findpenguins`, par exemple `polarsteps`).
- `-t`, `--trip` : ne scraper que le voyage portant ce slug (défaut : tous).
- `--force` : vider entièrement `--output` avant de scraper, y compris les archives d'autres services qui s'y trouvent. Avec `--trip`, seuls le dossier et le GPX de ce voyage sont supprimés pour chaque profil. Les articles Pelican ne sont pas supprimés.
- `--skip` : utiliser les captures enregistrées ; désactive `--force` s'il est aussi fourni.

`aventures` collecte d'abord FindPenguins puis Polarsteps, puis convertit les deux
archives. Les archives sont rangées sous `output/findpenguins` et
`output/polarsteps`, et les articles sous `../website/content/articles/findpenguins`
et `../website/content/articles/polarsteps` par défaut. `--output` et `--content`
remplacent leurs dossiers parents ; `--force` et `--skip` s'appliquent aux deux
services. Les deux services doivent être présents dans le fichier de profils.

### FindPenguins

Exécutez une première collecte, puis relancez avec `--skip` pour réutiliser
les pages HTML enregistrées du profil, du voyage, des étapes et des statistiques. Une page manquante
arrête l'exécution avec une erreur, sans téléchargement de remplacement. Les
données des menus d'étape sont également sauvegardées ; pour les anciennes
captures sans ces données, un avertissement est affiché et les champs
correspondants restent vides. Les anciens noms de fichiers HTML restent utilisables.
Cette option ne rend pas le traitement entièrement hors ligne : les médias
manquants, les cartes et les données d'altitude peuvent encore nécessiter le
réseau. Le GPX existant est réutilisé au lieu de retélécharger le parcours.

Les nouveaux manifestes `profile.json` et `trip.json` conservent les champs nécessaires
à la conversion, avec des chemins de médias relatifs à l'archive. Les anciennes archives
XML/GPX ne contiennent pas toutes ces données : rescraper (ou utiliser `--skip` avec
des captures existantes) pour créer les manifestes. Le convertisseur ne nettoie pas
les anciens articles ; retirer séparément les articles périmés si nécessaire.

### Polarsteps

```bash
scrapers polarsteps profiles.json --output polarsteps-output
scrapers aventures2rst --output polarsteps-output --content ../website/content/articles/polarsteps --category polarsteps
```

`profiles.json` est le même fichier que pour FindPenguins et permet de traiter tous ses comptes
Polarsteps. Chromium se connecte automatiquement en arrière-plan avec leurs
identifiants ; les requêtes vers des domaines tiers sont bloquées pendant cette
connexion. Pour utiliser le mode interactif, laissez le mot de passe vide dans
le fichier partagé : un navigateur s'ouvre, connectez-vous puis appuyez sur
Entrée dans le terminal. Celui-ci nécessite un
affichage graphique ; les deux modes nécessitent Chromium installé.
Le cookie `remember_token` est utilisé uniquement en mémoire pour les appels
à `api.polarsteps.com` et n'est pas enregistré.
L'API non officielle peut changer ; son utilisation dépend des conditions de
Polarsteps. Les appels de profil et de voyage suivent
[polarsteps-api](https://github.com/remuzel/polarsteps-api) ; la version 62 est
demandée afin de récupérer la trace GPS lorsqu'elle est disponible.

Les étapes, textes, photos, vidéos, météo, pays et modes de transport disponibles
sont intégrés aux mêmes manifestes, XML et GPX que FindPenguins.
Seules les étapes non supprimées dont le `type` vaut `1` sont archivées ;
les autres, y compris celles sans `type`, sont ignorées. Les réponses API
complètes sont conservées dans `api-user.json` et `api-trip.json`. Elles peuvent
contenir des données privées : protégez l'archive et ne la publiez pas.
Les conditions météo connues sont converties en icônes comme pour FindPenguins ;
un code inconnu est conservé avec un avertissement.
Les valeurs numériques du voyage et des étapes sont enregistrées sous forme de
chaînes dans `trip.json`, comme pour FindPenguins ; le champ de version du
manifeste reste numérique. Les réponses API brutes ne sont pas modifiées.
La trace GPS utilise `zelda_steps`, ou les routes encodées disponibles ; sans trace, le
GPX contient uniquement les étapes. Seule une carte transparente locale est
générée. Les coordonnées de la trace peuvent être envoyées au service
OpenTopoData pour enrichir les altitudes.
Si une photo originale est inaccessible, une miniature disponible est utilisée
avec un avertissement ; une vidéo inaccessible arrête la collecte. Les fichiers
déjà présents sont réutilisés : pour retenter un original après un avertissement,
retirez séparément le fichier WebP concerné et relancez.

Les slugs Polarsteps comprennent l'identifiant numérique du voyage avant son
nom, par exemple `42-aventure`. `-t` sélectionne ce slug complet. Les archives
créées avant ce changement utilisent les anciens noms : relancez une collecte
pour créer les nouveaux dossiers ; `--skip` ne réutilise pas les anciens dossiers.
Les anciens dossiers et articles ne sont pas supprimés automatiquement.
`--skip` relit les réponses sauvegardées et les médias déjà téléchargés sans
connexion au compte ; un fichier manquant arrête la collecte. Le service
d'altitude peut toujours être contacté. Pour rescraper après nettoyage, utilisez `--force` (ou
`--force --trip SLUG` pour un voyage). Utilisez un dossier d'archive distinct
de FindPenguins si les noms de profils coïncident.

### Apple Reminders

```bash
scrapers reminder --list "Ma liste" --output reminders-output [--all] [--force]
scrapers reminders2rst --output reminders-output [--content ../website/content/articles/reminders]
```

**État actuel :** `reminder.py` prépare le dossier de sortie (avec `--force`, il est
supprimé après validation de sécurité) puis **affiche** la commande
`rem export --list "…" --format json --incomplete > <dossier>/reminders.json` à exécuter
dans un terminal ; l'appel direct à `rem` est désactivé (commenté) dans `export_reminders`,
et `--all` n'a donc pas encore d'effet. `reminders2rst.py` lit ensuite `reminders.json`.
Une fois l'appel direct réactivé, sans `--all` seuls les rappels incomplets seront exportés.
Chaque rappel donne un
article à nom stable avec `Category: reminder` ; les notes sont rendues en texte
littéral. La conversion ne supprime pas les articles devenus périmés.
L'export utilise `rem export` ; macOS peut demander l'autorisation d'accès aux
rappels via la fenêtre de confidentialité système.

### Fichier de profils
```json
{
  "settings": {
    "map_background": "satellite"
  },
  "findpenguins": {
    "MonVoyageur": {
      "id": "pseudo_findpenguins",
      "username": "email_findpenguins@exemple.com",
      "password": "mot_de_passe_findpenguins"
    }
  },
  "polarsteps": {
    "MonVoyageur": {
      "id": "pseudo_polarsteps",
      "username": "identifiant_polarsteps",
      "password": "mot_de_passe_polarsteps"
    }
  }
}
```
Chaque commande traite les comptes de sa section ; une personne peut avoir un
seul compte ou les deux. `id` identifie le profil à archiver, `username` sert à
la connexion. Les anciens profils FindPenguins directement sous le nom et les
profils regroupés par personne restent acceptés. L'entrée `settings` est
facultative. Le fichier est ignoré par Git à la racine du dépôt ; protégez-le
(`chmod 600 profiles.json`) et ne le partagez pas.

| Réglage | Défaut | Rôle |
|---|---|---|
| `small_size` | `128` | Côté maximal (px) des photos de profil / compagnons (remplacent l'original). |
| `large_size` | `1600` | Côté maximal (px) des cartes, de la couverture et des photos `_thumb`. |
| `map_background` | `transparent` | Fond de `map_trip.webp` : `transparent`, `satellite` ou `street` (Esri). |
| `footprint_bubbles` | `false` | Bulles des étapes sur `map_trip.webp`. |
| `footprint_bubble_size` | `48` | Diamètre des bulles en pixels sur la carte d'origine (entier de 1 à 799). |

`small_size` et `large_size` sont enregistrés dans les manifestes des deux
services pour la conversion. `map_background` et `footprint_bubbles` configurent
la carte principale des deux services.

---

## 💾 Structure générée

### Archive FindPenguins (`--output`)

Exemple pour un ou plusieurs profils ; les fichiers de médias et de cartes ne
sont présents que lorsqu'ils ont été obtenus ou générés :

```text
output/
├── profiles.xml                       # Index fusionné si plusieurs profils traités
├── flags/
│   ├── codes.json                     # Nom de pays → liste des codes FlagCDN
│   ├── fr.webp                        # Drapeau FlagCDN (64 × 48)
│   └── ...                            # Autres drapeaux et drapeaux FindPenguins
├── pseudo_findpenguins/
│   ├── pseudo_findpenguins.xml         # Index XML du profil
│   ├── profile.json                   # Manifeste du profil et tailles d'image
│   ├── pseudo_findpenguins_profile_*.webp
│   ├── page-<hash-profil>.html         # Capture de la page du profil
│   ├── voyage-islande.gpx             # Parcours et waypoints enrichis
│   └── voyage-islande/
│       ├── trip.json                  # Manifeste du voyage et des étapes
│       ├── page-<hash-voyage>.html    # Capture de la page du voyage
│       ├── page-<hash-etape>.html     # Capture de chaque page d'étape
│       ├── page-<hash-etape>.popup.json # Données du menu de chaque étape
│       ├── insights.html              # Capture des statistiques, si obtenue
│       ├── map_trip.webp              # Carte principale, si trace valide
│       ├── satellite_trip.webp        # Carte satellite, si générée
│       ├── cover_trip.webp            # Couverture, si disponible
│       ├── <id-etape>__*.webp         # Photos des étapes
│       └── <id-etape>__*              # Vidéos et pièces jointes GPX/PDF
└── <id-compagnon>/
    └── <id-compagnon>_profile_*.webp  # Avatar partagé, si téléchargé
```

Chaque `<hash-…>` est le SHA-256 de l'URL de la page correspondante :
le HTML et le JSON du menu d'une même étape ont donc le même hash. Ces
captures servent à `--skip` ; les anciennes captures HTML restent également
utilisables. Si le GPX source du voyage est téléchargé, il est temporairement
placé dans le dossier du voyage puis normalement supprimé après la génération
du GPX enrichi.

### Archive Polarsteps (`--output`)

```text
polarsteps-output/
├── profiles.xml                       # Index fusionné si plusieurs profils traités
├── flags/
│   ├── codes.json                     # Nom de pays → liste des codes FlagCDN
│   └── *.webp                         # Drapeaux FlagCDN (64 × 48)
└── pseudo_polarsteps/
    ├── pseudo_polarsteps.xml           # Index XML du profil
    ├── profile.json                   # Manifeste du profil et tailles d'image
    ├── api-user.json                  # Réponse API du profil et liste des voyages
    ├── pseudo_polarsteps_profile.webp  # Avatar, si disponible
    ├── 42-aventure.gpx                # Trace et waypoints du voyage
    └── 42-aventure/                   # Slug préfixé par l'identifiant du voyage
        ├── trip.json                  # Manifeste du voyage et des étapes
        ├── api-trip.json              # Réponse API complète du voyage
        ├── map_trip.webp              # Carte principale, si trace valide
        ├── satellite_trip.webp        # Carte satellite, si générée
        ├── cover_trip.webp            # Couverture, si disponible
        ├── step-<id-etape>-<id-media>.webp # Photo d'étape
        └── step-<id-etape>-<id-media>.<ext> # Vidéo d'étape
```

Le nom d'une vidéo conserve son extension valide, ou utilise `.mp4` par
défaut. Les deux fichiers `api-*.json` sont les captures relues avec `--skip` ;
Polarsteps ne crée pas de captures HTML.

Dans les deux archives, `profile.json` et `trip.json` sont les manifestes
normalisés utilisés par le convertisseur, distincts des captures de la source.
Captures HTML, JSON et médias peuvent contenir des informations privées :
protégez l'ensemble de l'archive.

### Articles Pelican (`--content`)

La structure est commune aux deux services ; les noms de profil et de voyage
reflètent l'archive convertie :

```text
content/
├── flags/                    # Copie partagée pour le site Pelican
└── pseudo_findpenguins/
    └── voyage-islande/
        ├── trip.rst            # Article du voyage (Category: findpenguins, Date/EndDate)
        ├── cover_trip.webp      # Couverture (taille `large_size`)
        ├── map_trip.webp
        ├── satellite_trip.webp
        └── footprint_1/
            ├── footprint.rst   # Article de l'étape (Category: titre du voyage)
            ├── map_country.webp
            └── *.webp, *.mp4
```

Le voyage porte les métadonnées `Date` (première étape), `EndDate` (dernière étape plus ses nuits), `Transport` (ex. `bus 682 km; flight 581 km`) et `Category` (défaut `findpenguins`, configurable avec `--category`); son premier tag reprend la catégorie, suivi de `trip` et des pays. Les articles de voyage et d'étape définissent `Author` avec le nom du propriétaire. Les étapes ont également le tag `footprint`. Toutes les images (photos, couvertures, avatars, cartes) sont converties en WebP sans perte; les vidéos sont conservées telles quelles.

Les deux scrapers téléchargent les drapeaux FlagCDN en WebP 64 × 48 dans
`output/flags/` ainsi qu'une table `codes.json` associant chaque nom anglais à
une liste de codes (y compris les subdivisions et les noms en double). Les fichiers
existants valides sont réutilisés ; supprimer `codes.json` permet de rafraîchir la
liste lors d'une collecte normale. En mode `--skip`, seuls les fichiers présents
sont utilisés : si la table ou un drapeau manque, un avertissement est affiché.
Les deux scrapers utilisent le code du pays lorsqu'il est disponible ; sinon, un nom
inconnu ou ambigu reste sans drapeau et produit un avertissement. FindPenguins
utilise les codes présents dans les URL de ses drapeaux pour sélectionner les images
en cache, sans télécharger ces drapeaux. Les chemins `flags/...` sont enregistrés dans `trip.json`, puis les
drapeaux référencés sont copiés vers `--content/flags/` pour le site Pelican.

Les articles conservent l'image originale et ajoutent des variantes redimensionnées (jamais agrandies), référencées par les métadonnées :

| Image | Variantes créées | Utilisée dans le RST |
|---|---|---|
| Photo de profil / compagnon | aucune (taille `small_size` à la place de l'original) | `Companions` (photo du profil, partagée par tous les voyages) |
| Couverture du voyage | aucune (`cover_trip.webp` en taille `large_size`) | `TripImage` |
| Cartes du voyage et du pays | aucune (`map_trip.webp`, `satellite_trip.webp`, `map_country.webp` en taille `large_size`) | `TripMap`, `TripSatelliteMap`, `map_country.webp` (thème) |
| Photo d'étape | `_thumb` (taille `large_size`) | `Photo` (original, « Ouvrir la photo »); le thème déduit `_thumb` du nom (vignettes et carrousel) |

Les cartes de route mesurent 1200×800 pixels. Les bulles montrent la première photo
de l'étape, ou son numéro si elle n'a pas de photo. Pour chaque carte avec bulles,
un fichier `.inc` contient les boutons permettant de rejoindre les étapes.
`satellite_trip.webp` utilise toujours un fond satellite Esri et des bulles ; elle nécessite
un accès réseau pour les deux services. En cas d'échec, la carte
principale reste disponible. Un voyage sans trace GPX valide n'a pas de carte de route.

---

## 🔒 Sécurité & Bonnes Pratiques

- **Respect des quotas :** Le module d'élévation intègre une gestion adaptative du *Rate Limiting* (attente exponentielle en cas de code HTTP 429) pour ne pas saturer les serveurs tiers.
- **Données privées :** Les profils racine nommés `profile*.json` sont ignorés par Git ; vérifiez les autres emplacements ou noms avant publication. Protégez aussi les archives, qui peuvent contenir des données privées.

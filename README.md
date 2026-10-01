# MaxPlan

Trouve les **trains à 0 €** des abonnements **Max Jeune** et **Max Senior** (TGV INOUI et
Intercités), y compris en **enchaînant plusieurs trains** et en **finissant en TER ou en car
régional** jusqu'aux gares sans TGV : aller simple ou aller-retour, calendrier du mois, et calcul
« l'abonnement est-il rentable pour moi ? ».

👉 **https://maxplan.fr** · site non officiel, indépendant de la SNCF.

## Lancer en local

```bash
cp .env.example .env          # renseigner SNCF_TOKEN (clé API SNCF gratuite, numerique.sncf.com)
docker compose up -d          # → http://localhost:8765
```

Au premier démarrage, le serveur télécharge les horaires (~20 Mo) : les compléments TER et cars
sont disponibles au bout de quelques minutes. Sans Docker : `python server.py` (Python 3.12, aucune
dépendance externe).

## Comment ça marche

1. **Places Max** : l'open data SNCF `tgvmax` liste, pour les 30 prochains jours, chaque tronçon de
   train (TGV INOUI, Intercités) avec des places Max ouvertes. `maxplan/moteur/` en fait un graphe et
   cherche les trajets par un parcours en profondeur horodaté (jusqu'à 3 correspondances, index des
   trains par heure de départ et élagage par accessibilité pour rester rapide). Une ville regroupe ses
   gares (Paris avec Massy, Marne-la-Vallée, Roissy…) et ses gares voisines (Metz avec Lorraine TGV),
   et l'on peut changer de gare jumelle en cours de trajet.
2. **Compléments TER et cars** : quand la destination n'a pas de train Max, on regarde les gares
   atteignables en Max les plus proches, puis le TER ou le car jusqu'à la destination. Ces horaires
   sont calculés **en local** (`ter/gtfs.py`) à partir de l'export GTFS de la SNCF et d'une quarantaine
   de réseaux régionaux de cars (`ter/reseaux.py`), avec l'algorithme *Connection Scan* et des
   correspondances à pied entre arrêts proches. Les horaires sont mis à jour **la nuit**, et les tables
   de départs des 34 prochains jours sont préparées à ce moment-là (sur disque, compressées) : en
   journée, une recherche ne fait que les relire. L'API SNCF (Navitia, `ter/navitia.py`) ne sert qu'en
   secours, sous budget quotidien. Les réponses sont gardées en cache quelques minutes.
3. **Tri des résultats** : on écarte les options dominées (un trajet gratuit qui part plus tard et
   arrive plus tôt rend l'option payante inutile), les détours absurdes et, par défaut, les nuits en
   train ou en gare ; les trajets à 2 changements ou plus sont repliés.
4. **Prix** (`ter/prix.py`) : TER estimé sur la distance (barème dégressif calé sur des prix réels),
   réduction régionale déclarée par l'utilisateur appliquée au tarif normal, tarif unique pour les
   cars régionaux, −30 % Max Avantage sur les Intercités. Pour « Rentable ? », fourchettes
   officielles des billets TGV INOUI / Intercités (`ter/tarifs.py`, open data SNCF).
5. **Historique** (`historique.py`) : chaque jour, le serveur enregistre les trains ouverts au Max
   (SQLite, ~150 Mo par an). Il alimente les tendances (meilleurs jours, heures, quand les places
   s'ouvrent) et, après deux semaines, le calcul « Rentable ? ».
6. **Onglet Infos** : explique le fonctionnement des places Max, avec un graphique en direct de la part
   de trajets ouverts au Max chaque jour (open data SNCF) et des vacances scolaires (open data Éducation
   nationale), qui montre l'effet des vacances et des dates lointaines.
7. **Interface** (`web/`) : HTML/CSS/JS sans framework ni build, Leaflet et polices hébergés
   localement, PWA installable. Le profil, les favoris et les trajets « Rentable ? » restent dans le
   navigateur du visiteur.

## Architecture

Tout le code Python est dans le paquet `maxplan/` ; `server.py` ne fait que le lancer.

| Fichier | Rôle |
|---|---|
| `maxplan/serveur.py` | Serveur HTTP (bibliothèque standard) : routes, fichiers statiques, cache des réponses, limites de requêtes, en-têtes de sécurité. |
| `maxplan/api/` | Un module par point d'API : `recherche` (trajets Max + TER), `explorer`, `calendrier` (calendrier, tendances, idées), `rentable`, `infos` (onglet Infos, méta), `lieux` (autocomplétion, gare la plus proche), `retours` (bouton « Signaler »). `trajets` met en forme et trie les trajets ; `commun` lit les paramètres. |
| `maxplan/moteur/` | `donnees` : open data `tgvmax` ; `gares` : villes multi-gares, gares annexes et jumelles, gares parisiennes réelles, temps de correspondance ; `parcours` : recherche des trajets Max. |
| `maxplan/ter/` | `gtfs` / `reseaux` : horaires locaux (GTFS SNCF + cars régionaux) et calcul des trajets TER / cars ; `navitia` : API SNCF (géocodage, secours, budget quotidien) ; `prix` / `tarifs` : estimation des prix / tarifs officiels. |
| `maxplan/historique.py` | Historique quotidien des places Max et statistiques par liaison. |
| `maxplan/taches.py` | Tâches de fond : préchauffage au démarrage, relevé quotidien de l'historique. |
| `maxplan/regions.py` | Région d'un point (contours officiels dans `web/geo/regions.json`). |
| `maxplan/base.py` | Petites fonctions partagées (heures, distances, dates). |
| `maxplan/config.py` | Réglages (surchargés par les variables d'environnement, voir `.env.example`). |
| `web/` | Interface : `index.html`, `app.css`, `app.js`, `mentions-legales.html`, PWA, icônes. |
| `scripts/maxfinder.py` | Première version en ligne de commande (autonome, conservée pour mémoire). |

API : `/api/search`, `/api/calendar`, `/api/trends`, `/api/insights`, `/api/value`, `/api/ideas`, `/api/explore`,
`/api/stations`, `/api/nearest`, `/api/meta`, `POST /api/feedback`, `/healthz`.

## Contribuer

- Code et commentaires en français, sans dépendance externe (Python : bibliothèque standard ;
  web : pas de framework ni d'étape de build).
- Ajouter un réseau de cars : une ligne dans `maxplan/ter/reseaux.py` (jeu GTFS trouvé sur transport.data.gouv.fr).
- Tester en local avec `docker compose up -d --build`, puis les parcours principaux : recherche,
  aller-retour, calendrier, Explorer, « Rentable ? », sur ordinateur et sur téléphone.
- Signaler un bug ou proposer une idée : les *issues* du dépôt, ou le bouton « Signaler » du site.

## Données et limites

- Places Max : open data SNCF `tgvmax` (licence ODbL), **mis à jour une fois par jour** : une place
  affichée peut être partie entre-temps. La réservation se fait sur SNCF Connect (le lien ouvre la
  recherche du bon jour ; il ne pré-remplit pas toujours le trajet).
- Horaires : GTFS SNCF (~6 mois) et réseaux régionaux (transport.data.gouv.fr, licences ODbL ou
  Licence Ouverte). Quelques réseaux locaux manquent encore.
- Prix TER et cars : estimations.
- Pas de réservation automatique (interdite par les conditions de vente Max).

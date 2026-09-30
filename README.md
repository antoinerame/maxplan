# MaxPlan

Trouve les **trains à 0 €** des abonnements Max Jeune et Max Senior (TGV INOUI et Intercités), y compris en **recomposant
des correspondances** et en **complétant en TER** jusqu'aux gares sans TGV Max — sur une carte de
France lisible, sur ordinateur comme sur téléphone.

👉 **https://maxplan.fr**

## 🚀 Lancer

```bash
cp .env.example .env          # renseigner SNCF_TOKEN (clé API SNCF gratuite)
docker compose up -d          # → http://localhost:8765
```

## 🌍 Héberger sur un serveur

Même commande sur le serveur (`docker compose up -d`), derrière ton reverse proxy habituel
(Nginx, Caddy, Traefik…) qui fournit le HTTPS — nécessaire pour la géolocalisation (« gare la
plus proche ») et l'installation en application sur téléphone.

Sécurité (réglages dans `.env`) :
- le port n'écoute que sur la machine (`BIND=127.0.0.1`) : seul le reverse proxy le joint ; ne
  l'ouvre jamais directement sur Internet ;
- `PROXY_HOPS=1` : l'IP réelle des visiteurs (limite de requêtes) est la dernière entrée de
  `X-Forwarded-For`, ajoutée par ton proxy (`proxy_set_header X-Forwarded-For
  $proxy_add_x_forwarded_for;` et `X-Forwarded-Proto $scheme;` sous nginx) ;
- budget de la clé API SNCF : `NAVITIA_DAILY_BUDGET` (4 500/jour), dont `NAVITIA_PLACES_BUDGET`
  pour l'autocomplétion, et `NAVITIA_PER_IP_DAILY` par visiteur ; au-delà, le site reste utilisable
  sans compléments TER jusqu'au lendemain ;
- HSTS est envoyé quand le proxy transmet `X-Forwarded-Proto: https`.

**Retours des visiteurs** : le bouton « Signaler » enregistre les messages dans le volume de données
(`feedback.jsonl`). Pour les lire, mets un jeton dans `.env` (`FEEDBACK_TOKEN=…`, une longue chaîne
aléatoire) puis ouvre `https://<ton-domaine>/admin/retours?token=<le jeton>` (page introuvable sans
le bon jeton).

Chaque visiteur règle son propre profil (abonnement, réductions TER par région), stocké dans son
navigateur. Une recherche peut aussi se partager par lien (bouton « Partager »).

## Ce que fait l'app

- **Itinéraire** : départ → arrivée (autocomplétion, « gare la plus proche de moi »), plage de dates
  avec heures facultatives (« du jeudi 18 h au vendredi 15 h »), **aller-retour** (« Ajouter le
  retour »), dates rapides, complément TER activé par défaut, trajets de nuit masqués par défaut.
  Jusqu'à 3 changements cherchés automatiquement : les trajets simples (0 ou 1 changement) sont
  montrés d'abord, les autres derrière « Afficher plus de résultats ». Résultats façon tableau des
  départs en gare, triables (départ, durée, prix), filtre « 100 % gratuits », détail en plan de
  ligne, lien SNCF Connect qui ouvre le bon jour à la bonne heure. Carte masquée par défaut
  (bouton « Voir la carte »).
- **Correspondances TER automatiques** : l'API propose jusqu'à 3 trajets, on garde le direct sauf si
  une correspondance fait vraiment gagner du temps. Au-delà de ~4 semaines (horaires TER pas encore
  publiés par la SNCF), l'horaire TER est estimé d'après le même jour de la semaine précédente.
- **Trajets de nuit** (train de nuit, ou nuit à attendre en gare) masqués par défaut, dépliables par
  jour ; les détours absurdes (bien plus longs que le trajet le plus rapide du jour) sont écartés.
- **Rentable ?** : tes trajets habituels (et combien d'allers-retours par mois) → part des jours avec
  un train à 0 € sur les 30 prochains jours, prix officiels des billets (open data « Tarifs TGV INOUI
  et OUIGO » et « Tarifs Intercités »), et coût mensuel avec ou sans abonnement Max.
- **Historique des places Max** : chaque jour après la mise à jour de l'open data (~6 h UTC), le
  serveur photographie les trains ouverts au Max dans `history.sqlite` (volume de données) : une
  ligne par train et jour de voyage, avec le premier et le dernier jour où il était ouvert
  (~150 Mo par an). Sert aux statistiques de l'onglet « Rentable ? ».
- **Calendrier du mois** :

 pour un départ et une arrivée, le nombre de trajets à 0 € sur chacun des
  30 jours ; une touche sur un jour lance la recherche.
- **TGV INOUI et Intercités** (y compris de nuit) ouverts au Max. Le complément TER essaie plusieurs
  arrivées Max par gare-relais (ex. Paris → Lyon en Max puis TER vers Saint-Étienne, à différentes
  heures), écarte les détours et les options moins bonnes qu'un trajet gratuit.
- **Explorer** : toutes les gares atteignables à 0 € depuis une gare un jour donné ; une touche sur
  une gare ou une ligne ouvre la recherche d'itinéraire.
- **Favoris**, **thème clair/sombre/auto**, **mobile**, **application installable** (PWA), page
  **Mentions légales et sources** (`/mentions-legales.html`).
- **Prix TER estimés** : tarif normal estimé sur la distance (barème dégressif, calé sur des prix
  publiés), puis chaque tronçon reçoit la réduction déclarée pour *sa* région (détection
  géographique sur les contours officiels), appliquée au tarif normal et arrondie au décime
  supérieur comme dans les CGV TER. Les promos SNCF ne se cumulent pas avec les cartes. Estimations :
  le prix réel est sur SNCF Connect.

## Architecture

| Fichier | Rôle |
|---|---|
| `server.py` | Serveur HTTP (stdlib, zéro dépendance) : API + fichiers ; caches à durée de vie, calculs TER en parallèle, limite de requêtes par IP, gzip, en-têtes de sécurité (CSP). |
| `tgvmax_core.py` | Open data `tgvmax` + moteur de graphe (correspondances, fenêtre horaire, nuit). |
| `navitia.py` | API SNCF/Navitia : géocodage (cache disque), autocomplétion, itinéraires TER (cache mémoire). |
| `fares.py` | Fourchettes de prix officielles des billets TGV INOUI / Intercités (open data), pour « Rentable ? ». |
| `history.py` | Historique quotidien des places Max (SQLite) et statistiques par liaison. |
| `pricing.py` | Estimation des prix par tronçon selon le profil (abonnement + réductions par région). |
| `regions.py` | Région d'un point (point-dans-polygone sur `web/geo/regions.json`). |
| `web/` | Interface : `index.html`, `app.css`, `app.js`, polices et Leaflet hébergés localement, PWA (`manifest.webmanifest`, `sw.js`, icônes). |
| `web/geo/` | Contours de la France et des régions (france-geojson, IGN / data.gouv.fr). |
| `Dockerfile` / `docker-compose.yml` | Image + service, volume de cache, healthcheck. |

API : `/api/meta`, `/api/search`, `/api/calendar`, `/api/ideas`, `/api/value`, `/api/explore`, `/api/stations`, `/api/nearest`, `/healthz`.


## Données & limites

- Places Max : open data SNCF `tgvmax` (ODbL), ~30 jours glissants, **mis à jour 1×/jour** → dispo
  indicative. Le vendredi et les veilles de vacances ont souvent peu ou pas de places Max.
- Horaires TER : API SNCF (Navitia), clé gratuite ~5 000 requêtes/jour partagée par tous les
  visiteurs (les résultats sont mis en cache pour l'économiser).
- Fond de carte : relief Esri (sans libellés) ; noms de villes et régions posés par l'app, en français.
- Lien SNCF Connect : chaque tronçon ouvre SNCF Connect directement sur la liste des trains du bon
  jour, à partir de la bonne heure (phrase libre `userInput`, arrondie à l'heure par SNCF). Sur
  téléphone, le lien `/app/…` est censé ouvrir l'appli SNCF Connect si elle est installée.
- Pas de réservation automatique (interdite par les CGV Max).

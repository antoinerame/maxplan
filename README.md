# TGV Max Planner

Trouve les **TGV Max à 0 €** (abonnements Max Jeune et Max Senior), y compris en **recomposant
des correspondances** et en **complétant en TER** jusqu'aux gares sans TGV Max — sur une carte de
France lisible, sur ordinateur comme sur téléphone.

👉 **https://tgvmax.roulotte-rame.fr**

## 🚀 Lancer

```bash
cp .env.example .env          # renseigner SNCF_TOKEN (clé API SNCF gratuite)
docker compose up -d          # → http://localhost:8765
```

## 🌍 Héberger sur un serveur

Même commande sur le serveur (`docker compose up -d`), derrière ton reverse proxy habituel
(Nginx, Caddy, Traefik…) qui fournit le HTTPS — nécessaire pour la géolocalisation (« gare la
plus proche ») et l'installation en application sur téléphone. Le serveur lit l'IP réelle des
visiteurs dans `X-Forwarded-For` / `CF-Connecting-IP` pour la limite de requêtes : fais transmettre
ces en-têtes par le proxy, et n'expose pas le port 8765 directement.

Chaque visiteur règle son propre profil (abonnement, réductions TER par région), stocké dans son
navigateur. Une recherche peut aussi se partager par lien (bouton « Partager »).

## Ce que fait l'app

- **Itinéraire** : départ → arrivée (autocomplétion, « gare la plus proche de moi »), plage de dates
  avec heures facultatives (« du jeudi 18 h au vendredi 15 h »), dates rapides, correspondances Max
  et TER réglables, trajets de nuit masqués par défaut. Résultats façon tableau des départs, triables
  (départ, durée, prix), filtre « 100 % gratuits », détail en plan de ligne, lien SNCF Connect.
- **Explorer** : toutes les gares atteignables à 0 € depuis une gare un jour donné ; une touche sur
  une gare ou une ligne ouvre la recherche d'itinéraire.
- **Favoris**, **thème clair/sombre/auto**, **mobile** (carte plein écran + panneau coulissant),
  **application installable** (PWA).
- **Prix TER estimés tronçon par tronçon** : chaque tronçon TER reçoit la réduction déclarée pour
  *sa* région (détection géographique sur les contours officiels), les TGV/Intercités le −30 %
  Max Avantage. Estimations : le prix réel est sur SNCF Connect.

## Architecture

| Fichier | Rôle |
|---|---|
| `server.py` | Serveur HTTP (stdlib, zéro dépendance) : API + fichiers ; caches à durée de vie, calculs TER en parallèle, limite de requêtes par IP, gzip, en-têtes de sécurité (CSP). |
| `tgvmax_core.py` | Open data `tgvmax` + moteur de graphe (correspondances, fenêtre horaire, nuit). |
| `navitia.py` | API SNCF/Navitia : géocodage (cache disque), autocomplétion, itinéraires TER (cache mémoire). |
| `pricing.py` | Estimation des prix par tronçon selon le profil (abonnement + réductions par région). |
| `regions.py` | Région d'un point (point-dans-polygone sur `web/geo/regions.json`). |
| `web/` | Interface : `index.html`, `app.css`, `app.js`, polices et Leaflet hébergés localement, PWA (`manifest.webmanifest`, `sw.js`, icônes). |
| `web/geo/` | Contours de la France et des régions (france-geojson, IGN / data.gouv.fr). |
| `Dockerfile` / `docker-compose.yml` | Image + service, volume de cache, healthcheck. |

API : `/api/meta`, `/api/search`, `/api/explore`, `/api/stations`, `/api/nearest`, `/healthz`.

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

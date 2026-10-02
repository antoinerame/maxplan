# Réglages de MaxPlan (surchargés par les variables d'environnement, voir .env.example).
import os

# Racine du dépôt (où se trouvent .env et web/)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv(path=os.path.join(ROOT, ".env")):
    """Lit le .env local (lancement hors Docker) sans écraser les variables déjà définies."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                k, sep, v = line.strip().partition("=")
                if sep and k and not k.startswith("#"):
                    os.environ.setdefault(k.strip(), v.strip().strip('"\''))
    except OSError:
        pass


_load_dotenv()

# Clé API SNCF (Navitia / api.sncf.com) : variable d'env SNCF_TOKEN ou fichier .env (jamais versionnée).
SNCF_TOKEN = os.environ.get("SNCF_TOKEN", "")

HOST = os.environ.get("MAXFINDER_HOST", "127.0.0.1")
PORT = int(os.environ.get("MAXFINDER_PORT", os.environ.get("PORT", "8765")))

# Répertoire de données persistantes (cache de géocodage). En conteneur : /data (volume).
DATA_DIR = os.environ.get("DATA_DIR", ROOT)

# Réglages du moteur de recherche.
MIN_CONNECTION_MIN = 15          # temps de correspondance mini (gare simple)
MIN_CONNECTION_INTRAMUROS = 30   # idem pour une ville multi-gares "(intramuros)"
MAX_LAYOVER_MIN = 4 * 60         # attente max en correspondance
MAX_TOTAL_MIN = 16 * 60          # durée totale max d'un itinéraire
TER_MAX_TAIL_MIN = 5 * 60        # durée max d'un segment TER de complément (Valence → Briançon ≈ 4 h 30)
TER_MAX_DISTANCE_KM = 320        # ne tente un pont TER que vers une gare frontière < cette distance
TER_CANDIDATES = 7               # nb de gares frontières les plus proches testées en TER

# Caches (secondes). L'open data est rafraîchi 1×/jour : 3 h suffit largement.
EDGES_TTL = 3 * 3600
STATIONS_TTL = 12 * 3600
JOURNEY_TTL = 6 * 3600

# Garde-fous quand le site est partagé publiquement
MAX_RANGE_DAYS = 8               # l'interface interroge jour par jour
RATE_LIMITS = {               # groupe -> (requêtes autorisées, fenêtre en secondes) par adresse IP
    "search": (60, 60),
    "explore": (20, 60),
    "stations": (120, 60),
    "nearest": (30, 60),
    "calendar": (12, 60),
    "feedback": (5, 600),
}

# Complément TER : nombre d'arrivées Max essayées par gare-relais (la plus proche d'abord), espacées d'au moins…
TER_ARRIVALS_PER_RELAY = (5, 3, 2, 1)
ORIGIN_TER_KM = 150             # TER au départ (ville sans train Max) : gares Max à moins de 150 km
ORIGIN_TER_KM_MAX_CITY = 70     # depuis une ville qui a des trains Max : grandes gares toutes proches
ORIGIN_TER_CANDIDATES = 4
TER_ARRIVAL_SPACING_MIN = 45

# Page privée des retours visiteurs : /admin/retours?token=<FEEDBACK_TOKEN> (désactivée si vide)
FEEDBACK_TOKEN = os.environ.get("FEEDBACK_TOKEN", "")

# Budget quotidien de requêtes à l'API SNCF (quota de la clé : 5 000/jour). L'autocomplétion a son
# propre plafond pour ne jamais priver les recherches de compléments TER.
NAVITIA_DAILY_BUDGET = int(os.environ.get("NAVITIA_DAILY_BUDGET", "4500"))
NAVITIA_PLACES_BUDGET = int(os.environ.get("NAVITIA_PLACES_BUDGET", "1200"))
NAVITIA_PER_IP_DAILY = int(os.environ.get("NAVITIA_PER_IP_DAILY", "400"))   # compléments TER par visiteur

# Nombre de reverse proxys de confiance devant le serveur (pour lire l'IP réelle dans
# X-Forwarded-For). 1 derrière nginx/Caddy/Traefik ; 0 si le serveur est exposé directement.
PROXY_HOPS = int(os.environ.get("PROXY_HOPS", "1"))
# En-tête donnant l'IP réelle du visiteur, posé par un service de confiance devant le site.
# Derrière Cloudflare (tunnel ou proxy) : CLIENT_IP_HEADER=CF-Connecting-IP. À ne régler que si le
# site n'est joignable QUE par Cloudflare (sinon n'importe qui pourrait inventer cet en-tête).
CLIENT_IP_HEADER = os.environ.get("CLIENT_IP_HEADER", "").strip()

# Cohérence des trajets proposés
TRANSFER_PAID_MIN = 5          # changement de gare à partir de ce prix (Rhônexpress, aéroport) : trajet payant
DETOUR_MAX_EXPLORE = 1.6         # Explorer : destination via une correspondance trop détournée, masquée
DETOUR_ABSURD = 3.0             # trajet gratuit plus détourné que ça (Marseille → Paris → Nice) : retiré
DETOUR_MAX_PAID = 2.0            # trajet avec TER payant plus détourné que ça : retiré (pas juste replié)
DETOUR_MAX = 1.4                # gare-relais : au plus 40 % de distance en plus que le trajet direct
TER_MAX_SHARE_OF_FARE = 0.6      # Max + TER retiré s'il coûte plus de 60 % d'un billet direct habituel

"""Mise en forme et tri des trajets : tronçons Max, noms de gares, liens SNCF Connect, trajets
dominés, détours, places Max du jour (cache) et géocodage."""

import re
import threading
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from maxplan import base
from maxplan import config
from maxplan.moteur import donnees
from maxplan.moteur import gares
from maxplan.moteur import parcours
from maxplan.ter import gtfs
from maxplan.ter import tarifs
from maxplan.ter.navitia import navitia
from maxplan.api.commun import shift


IO_POOL = ThreadPoolExecutor(max_workers=16)   # géocodage + calculs TER
DAY_POOL = ThreadPoolExecutor(max_workers=4)   # plusieurs jours d'une même recherche


# ======================================================================= places Max du jour et géocodage
_EDGES = {}
_EDGE_LOCKS = defaultdict(threading.Lock)


def edges_for(date):
    """Segments Max du jour, mis en cache quelques heures (l'open data change 1×/jour)."""
    hit = _EDGES.get(date)
    if hit and time.time() - hit[0] < config.EDGES_TTL:
        return hit[1]
    with _EDGE_LOCKS[date]:  # une seule récupération même si plusieurs visiteurs arrivent ensemble
        hit = _EDGES.get(date)
        if hit and time.time() - hit[0] < config.EDGES_TTL:
            return hit[1]
        edges = donnees.fetch_oui_edges(date)
        now = time.time()
        _EDGES[date] = (now, edges)
        for d, (t, _) in list(_EDGES.items()):
            if now - t > 2 * config.EDGES_TTL:
                _EDGES.pop(d, None)
        return edges


def geocode_many(labels):
    labels = [l for l in dict.fromkeys(labels) if l]
    return dict(zip(labels, IO_POOL.map(navitia.geocode, labels))) if labels else {}


# ======================================================================= noms affichés
_SMALL = {"de", "du", "des", "la", "le", "les", "sur", "sous", "en", "et", "aux", "au"}


def nice_place(name):
    """« Lyon Part Dieu (Lyon) » -> « Lyon Part Dieu »."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", name or "").strip()


def pretty(label):
    s = label.replace("(intramuros)", "").strip().rstrip(".")
    out = []
    for i, w in enumerate(s.split()):
        lw = w.lower()
        if w in ("TGV", "TER", "CDG", "SNCF", "HBF"):
            out.append(w)
        elif lw == "st":
            out.append("Saint")
        elif lw == "ste":
            out.append("Sainte")
        elif i and lw in _SMALL:
            out.append(lw)
        else:
            out.append(lw.capitalize())
    return " ".join(out)


_MODES = {"REGIONAURA": "TER", "TER NA": "TER", "TER": "TER", "LEX": "Léman Express", "NOMAD": "Nomad",
          "LIO": "liO", "ALÉOP": "Aléop", "ALEOP": "Aléop", "RÉMI": "Rémi", "REMI": "Rémi", "FLUO": "Fluo",
          "MOBIGO": "Mobigo", "BREIZHGO": "BreizhGo", "ZOU !": "ZOU !", "TGV INOUI": "TGV INOUI",
          "INTERCITÉS": "Intercités", "INTERCITES": "Intercités", "OUIGO": "OUIGO", "CAR": "Car",
          "AUTOCAR": "Car", "BUS": "Bus", "TRAMWAY": "Tram", "TRANSILIEN": "Transilien", "RER": "RER"}


def nice_mode(mode):
    """Codes réseau Navitia -> libellé lisible (« REGIONAURA » -> « TER »)."""
    m = (mode or "").strip()
    return _MODES.get(m.upper(), "TER" if m.isupper() and len(m) > 4 else m or "Train")


def display_name(label, geo=None):
    if "(intramuros)" in label:
        return pretty(label)            # « PARIS (intramuros) » -> « Paris » (toutes gares)
    if geo and geo.get("name"):
        return nice_place(geo["name"])  # nom Navitia, accentué
    return pretty(label)


_MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
         "septembre", "octobre", "novembre", "décembre")


def booking_url(o_label, o_geo, d_label, d_geo, date, hhmm):
    """SNCF Connect comprend une phrase libre (`userInput`) : « Lyon Part-Dieu Marseille Saint-Charles
    le 1 octobre à 07h04 » ouvre directement la liste des trains de ce jour à partir de cette heure.
    Le chemin /app/ est déclaré en lien universel : sur téléphone, l'appli SNCF Connect s'ouvre."""
    y, m, d = (int(x) for x in date.split("-"))
    text = (f"{display_name(o_label, o_geo)} {display_name(d_label, d_geo)} "
            f"le {d} {_MOIS[m - 1]} à {hhmm.replace(':', 'h')}")
    return "https://www.sncf-connect.com/app/home/search?" + urllib.parse.urlencode({"userInput": text})


# ======================================================================= itinéraires
def train_mode(axe):
    """Axe open data -> type de train (« IC ARO », « IC SRO » : Intercités ; « IC NUIT » : de nuit)."""
    axe = (axe or "").upper()
    if axe == "IC NUIT":
        return "Intercités de nuit"
    if axe.startswith("IC"):
        return "Intercités"
    if axe.startswith("AUTOCAR"):
        return "Car SNCF"
    return "TGV INOUI"


def max_leg(edge, date, geo):
    o, d = edge["o"], edge["d"]
    og, dg = geo.get(o), geo.get(d)
    # Paris : la vraie gare (Gare de Lyon, Montparnasse…) d'après l'axe du train
    so, sd = gares.city_station(o, edge), gares.city_station(d, edge)
    if so:
        la, lo = gares.PARIS_COORDS[so]
        og = {"name": so, "lat": la, "lon": lo}
    if sd:
        la, lo = gares.PARIS_COORDS[sd]
        dg = {"name": sd, "lat": la, "lon": lo}
    dep = base.min_to_hhmm(edge["dep"])
    return {
        "free": True, "mode": train_mode(edge.get("axe", "")),
        "train": edge["train"], "axe": edge.get("axe", ""),
        "entity": edge.get("entity", ""),
        "from": o, "to": d, "from_name": so or display_name(o, og), "to_name": sd or display_name(d, dg),
        "dep": dep, "arr": base.min_to_hhmm(edge["arr"]),
        "dep_day": edge["dep"] // 1440, "arr_day": edge["arr"] // 1440,
        "from_lat": og and og["lat"], "from_lon": og and og["lon"],
        "to_lat": dg and dg["lat"], "to_lon": dg and dg["lon"],
        "book_url": booking_url(so or o, None if so else og, sd or d, None if sd else dg,
                                shift(date, edge["dep"] // 1440), dep),

    }


def path_nocturnal(path):
    """Un trajet touche-t-il la nuit (train ou attente de correspondance ~23 h–6 h) ?"""
    if any(parcours.night_overlap(e["dep"], e["arr"]) for e in path):
        return True
    return any(parcours.night_overlap(a["arr"], b["dep"]) for a, b in zip(path, path[1:]))


def dest_place(dst, targets, stations):
    """Lieu d'arrivée pour le calcul TER. Si l'arrivée est une gare Max (« Lyon » -> LYON (intramuros)),
    on géocode ce libellé (surcharges comprises) plutôt que le texte libre, que l'API SNCF peut
    confondre (« Lyon » -> « Paris - Gare de Lyon »)."""
    for t in targets:
        if t in stations:
            g = navitia.geocode(t)
            if g:
                return g
    return free_place(dst)


def free_place(label):
    """Lieu saisi librement (village, gare hors réseau Max) : d'abord dans les horaires GTFS
    (aucune requête à l'API SNCF), sinon géocodage par l'API."""
    if gtfs.ready():
        hits = gtfs.places(nice_place(label), limit=1)
        if hits:
            return hits[0]
    return navitia.geocode(label)


def ter_coverage():
    return gtfs.coverage() or navitia.coverage()


def _access_min(station):
    """Minutes pour rejoindre une gare annexe depuis le centre (Massy, Marne-la-Vallée…), 0 sinon."""
    a = gares.ANNEX.get(station)
    m = a and re.search(r"environ (\d+) min", a[2])
    return int(m.group(1)) if m else (30 if a else 0)


def drop_dominated(itins):
    """Retire un trajet quand un autre part au plus tôt pareil, arrive au plus tard pareil et coûte au plus
    autant (ex. Max + TER payant alors qu'un TGV Max direct part après et arrive avant).
    Une gare annexe compte son temps d'accès : un train depuis Massy ne cache pas celui de Montparnasse
    parti 10 min plus tôt. Une nuit en gare ne se justifie pas pour quelques centimes d'économie."""
    def ends(it):
        a, b = it["legs"][0], it["legs"][-1]
        pre = it["_pre"] if "_pre" in it else _access_min(a.get("from") or a.get("o"))
        post = it["_post"] if "_post" in it else _access_min(b.get("to") or b.get("d"))
        return it["_dep"] - pre, it["_arr"] + post

    span = [ends(it) for it in itins]

    def beats(j, i):
        y, x = itins[j], itins[i]
        (yd, ya), (xd, xa) = span[j], span[i]
        tol = 2 if x.get("nocturnal") and not y.get("nocturnal") else 0
        no_worse = yd >= xd and ya <= xa and y["cost_eur"] <= x["cost_eur"] + tol \
            and len(y["legs"]) <= len(x["legs"])
        better = yd > xd or ya < xa or y["cost_eur"] < x["cost_eur"] or len(y["legs"]) < len(x["legs"]) \
            or bool(tol)
        return no_worse and better

    n = len(itins)
    return [x for i, x in enumerate(itins) if not any(beats(j, i) for j in range(n) if j != i)]


def detour_ratio(origins, relay, fgeo, dest, direct_km):
    """(départ → relais + relais → destination) / (départ → destination), au mieux parmi les gares de départ."""
    g = fgeo.get(relay) or navitia._cache.get(relay)
    if not g:
        return 0
    best = None
    for o in origins:
        og = fgeo.get(o) or navitia._cache.get(o)
        if og:
            via = base.haversine_km(og["lat"], og["lon"], g["lat"], g["lon"]) + \
                base.haversine_km(g["lat"], g["lon"], dest["lat"], dest["lon"])
            r = via / max(1.0, base.haversine_km(og["lat"], og["lon"], dest["lat"], dest["lon"]))
            best = r if best is None else min(best, r)
    return best or 0


def path_detour(legs):
    """Distance parcourue / distance à vol d'oiseau entre le départ et l'arrivée d'un trajet."""
    pts = [(l.get("from_lat"), l.get("from_lon")) for l in legs] + [(legs[-1].get("to_lat"), legs[-1].get("to_lon"))]
    pts = [p for p in pts if p[0] is not None]
    if len(pts) < 3:
        return 1.0
    run = sum(base.haversine_km(*a, *b) for a, b in zip(pts, pts[1:]))
    return run / max(1.0, base.haversine_km(*pts[0], *pts[-1]))


_FARES = {}


def direct_fare(origins, targets):
    """Prix habituel (milieu de fourchette, tarif Avantage) d'un billet direct entre deux villes."""
    if (origins, targets) not in _FARES:
        try:
            p = tarifs.price_range(list(origins), list(targets))
            _FARES[(origins, targets)] = p and p["avantage"]["typical"]
        except Exception:
            return None
    return _FARES[(origins, targets)]


def max_legs(path, date, geo):
    """Tronçons Max d'un trajet ; quand on change de gare jumelle (Massy → Marne-la-Vallée…),
    le tronçon suivant dit comment faire."""
    legs = [max_leg(e, date, geo) for e in path]
    for prev, e, leg in zip(path, path[1:], legs[1:]):
        if e["o"] != prev["d"]:
            leg["change_note"] = gares.twin_note(prev["d"], e["o"], prev, e)
    return legs


def itinerary_from_path(path, date, geo):

    legs = max_legs(path, date, geo)
    return {
        "_dep": path[0]["dep"], "_arr": path[-1]["arr"],
        "type": "max", "paid": False, "cost_eur": 0, "nresa": len(legs), "changes": len(legs) - 1,
        "departure": legs[0]["dep"], "arrival": legs[-1]["arr"],
        "arrival_day": path[-1]["arr"] // 1440,
        "duration_min": path[-1]["arr"] - path[0]["dep"],
        "nocturnal": path_nocturnal(path), "legs": legs,
    }


def tail_end(jr, ready):
    """Minutes entre la fin du train Max (+ correspondance) et l'arrivée du TER."""
    wait = (base.hhmm_to_min(jr["departure"]) - ready % 1440) % 1440
    return wait + jr["duration_min"]

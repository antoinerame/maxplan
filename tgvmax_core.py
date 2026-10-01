# -*- coding: utf-8 -*-
"""Cœur métier : lecture de l'open data SNCF tgvmax + recherche de trajets Max."""

import json
import math
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import date as Date, timedelta

import config

API = "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/tgvmax"

# Villes multi-gares regroupées sous "<VILLE> (intramuros)" dans le dataset.
CITY_ALIASES = {
    "paris": ["PARIS (intramuros)", "MARNE LA VALLEE CHESSY", "MASSY TGV", "MASSY PALAISEAU",
              "AEROPORT ROISSY CDG 2 TGV", "VERSAILLES CHANTIERS"],
    "lyon": ["LYON (intramuros)", "LYON ST EXUPERY TGV."],
    "marseille": ["MARSEILLE ST CHARLES", "MARSEILLE BLANCARDE"],
    "lille": ["LILLE (intramuros)"],
    "avignon": ["AVIGNON TGV", "AVIGNON CENTRE"],
    "aix": ["AIX EN PROVENCE TGV"],
    "aix-en-provence": ["AIX EN PROVENCE TGV"],
    "bourg-en-bresse": ["BOURG EN BRESSE"],
    "bordeaux": ["BORDEAUX ST JEAN"],
    "nantes": ["NANTES"],
    "rennes": ["RENNES"],
    "strasbourg": ["STRASBOURG"],
    "montpellier": ["MONTPELLIER SAINT ROCH", "MONTPELLIER SUD DE FRANCE"],
    "nimes": ["NIMES CENTRE", "NIMES PONT DU GARD"],
    "valence": ["VALENCE VILLE", "VALENCE TGV AUVERGNE RHONE ALPES"],
    "besancon": ["BESANCON VIOTTE", "BESANCON FRANCHE COMTE TGV"],
    "reims": ["REIMS", "CHAMPAGNE ARDENNE TGV"],
    "nice": ["NICE VILLE"],
    "toulouse": ["TOULOUSE MATABIAU"],
    "grenoble": ["GRENOBLE"],
}


# Gares annexes proposées quand on cherche la ville (gare principale, ville, comment y aller)
ANNEX = {
    "MARNE LA VALLEE CHESSY": ("PARIS (intramuros)", "Paris", "RER A, environ 40 min depuis Châtelet, ticket 2,50 €"),
    "MASSY TGV": ("PARIS (intramuros)", "Paris", "RER B ou C, environ 30 min, ticket 2,50 €"),
    "MASSY PALAISEAU": ("PARIS (intramuros)", "Paris", "RER B ou C, environ 30 min, ticket 2,50 €"),
    "AEROPORT ROISSY CDG 2 TGV": ("PARIS (intramuros)", "Paris", "RER B, environ 35 min depuis Gare du Nord, billet aéroport ≈ 13 €"),
    "VERSAILLES CHANTIERS": ("PARIS (intramuros)", "Paris", "train ou RER C, environ 20 min depuis Montparnasse, ticket 2,50 €"),
    "LYON ST EXUPERY TGV.": ("LYON (intramuros)", "Lyon", "tram Rhônexpress depuis Part-Dieu, environ 30 min, ≈ 17 €"),
}
IDF_ACCESS = {k: v[2] for k, v in ANNEX.items() if v[0] == "PARIS (intramuros)"}
MAIN_STATION_KEY = {"PARIS (intramuros)": "paris", "LYON (intramuros)": "lyon"}

# Gares jumelles : on peut arriver à l'une et repartir de l'autre (minutes de changement, marge
# comprise, et comment faire). Paris intra-muros : voir transfer_min (gares déduites de l'axe).
_TWIN_PAIRS = [
    ("PARIS (intramuros)", "MARNE LA VALLEE CHESSY", 60, "RER A, environ 40 min"),
    ("PARIS (intramuros)", "MASSY TGV", 60, "RER B ou C, environ 35 min"),
    ("PARIS (intramuros)", "MASSY PALAISEAU", 60, "RER B ou C, environ 35 min"),
    ("PARIS (intramuros)", "AEROPORT ROISSY CDG 2 TGV", 60, "RER B, environ 35 min"),
    ("PARIS (intramuros)", "VERSAILLES CHANTIERS", 50, "train ou RER C, environ 25 min"),
    ("MASSY TGV", "MASSY PALAISEAU", 20, "à pied, environ 10 min"),
    ("MASSY TGV", "MARNE LA VALLEE CHESSY", 100, "RER B puis RER A, environ 1 h 15"),
    ("MASSY TGV", "AEROPORT ROISSY CDG 2 TGV", 90, "RER B, environ 1 h 05"),
    ("MARNE LA VALLEE CHESSY", "AEROPORT ROISSY CDG 2 TGV", 90, "RER A puis RER B, environ 1 h 10"),
    ("LYON (intramuros)", "LYON ST EXUPERY TGV.", 60, "tram Rhônexpress, environ 30 min, ≈ 17 €"),
    ("AVIGNON TGV", "AVIGNON CENTRE", 25, "navette TER, environ 5 min"),
    ("MONTPELLIER SAINT ROCH", "MONTPELLIER SUD DE FRANCE", 40, "navette ou tram, environ 20 min"),
    ("NIMES CENTRE", "NIMES PONT DU GARD", 35, "navette ou TER, environ 15 min"),
    ("VALENCE VILLE", "VALENCE TGV AUVERGNE RHONE ALPES", 25, "TER, environ 10 min"),
    ("REIMS", "CHAMPAGNE ARDENNE TGV", 25, "TER ou tram, environ 10 min"),
    ("BESANCON VIOTTE", "BESANCON FRANCHE COMTE TGV", 30, "TER, environ 15 min"),
    ("METZ VILLE", "LORRAINE TGV", 50, "navette en car, environ 30 min"),
    ("NANCY", "LORRAINE TGV", 50, "navette en car, environ 35 min"),
]
TWINS = {}
for _a, _b, _m, _n in _TWIN_PAIRS:
    TWINS.setdefault(_a, []).append((_b, _m, _n))
    TWINS.setdefault(_b, []).append((_a, _m, _n))


def twin_note(a, b):
    """Comment passer de la gare a à la gare b (gares jumelles), ou None."""
    return next((n for x, _, n in TWINS.get(a, ()) if x == b), None)


def _departures(by_origin, station, path):
    """Trains au départ de la gare… ou de sa jumelle (changement de gare) : (train, attente mini)."""
    for e in by_origin.get(station, ()):
        yield e, (transfer_min(station, path[-1], e) if path else 0)
    if path:
        for other, mins, _ in TWINS.get(station, ()):
            for e in by_origin.get(other, ()):
                yield e, mins


def normalize(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower().replace("-", " ").replace("(intramuros)", "").replace(".", "").strip()


def resolve_city(city, stations):
    """Libellés de gare du dataset correspondant à `city` (alias, exact, ou contient)."""
    key = city.strip().lower()
    if city.strip() in MAIN_STATION_KEY:          # gare choisie dans la liste : la ville et ses gares annexes
        key = MAIN_STATION_KEY[city.strip()]
    if key in CITY_ALIASES:
        hit = [s for s in CITY_ALIASES[key] if s in stations]
        return hit or CITY_ALIASES[key]
    nq = normalize(key)
    exact = [s for s in stations if normalize(s) == nq]
    if exact:
        return exact
    if len(nq) < 3:                       # « e », « pa »… : trop vague, ferait exploser la recherche
        return [city.upper()]
    contains = sorted((s for s in stations if nq in normalize(s)), key=len)[:6]
    return contains or [city.upper()]


def hhmm_to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def min_to_hhmm(x):
    x %= 1440
    return f"{x // 60:02d}:{x % 60:02d}"


def date_filter(d):
    y, m, dd = d.split("-")
    return f"year(date)={int(y)} and month(date)={int(m)} and day(date)={int(dd)}"


def fetch_oui_edges(d):
    """Tous les segments avec place Max (od_happy_card=OUI) pour la date d."""
    params = {
        "where": date_filter(d) + " and od_happy_card='OUI'",
        "select": "train_no,entity,axe,origine,destination,heure_depart,heure_arrivee",
        "limit": -1,
    }
    url = API + "/exports/json?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.load(r)
    rows = data if isinstance(data, list) else data.get("results", [])
    edges = []
    for x in rows:
        try:
            dep = hhmm_to_min(x["heure_depart"])
            arr = hhmm_to_min(x["heure_arrivee"])
        except Exception:
            continue
        if arr < dep:
            arr += 1440
        edges.append({
            "o": x["origine"], "d": x["destination"], "dep": dep, "arr": arr,
            "train": x["train_no"], "entity": x.get("entity", ""), "axe": x.get("axe", ""),
        })
    return edges


_STATIONS = None


def available_dates():
    url = API + "/records?" + urllib.parse.urlencode(
        {"select": "date", "group_by": "date", "order_by": "date", "limit": 100})
    with urllib.request.urlopen(url, timeout=30) as r:
        return [x["date"][:10] for x in json.load(r).get("results", [])]


_DATES = (0.0, [])


def dataset_dates():
    """Dates couvertes par l'open data (cache 1 h)."""
    global _DATES
    if time.time() - _DATES[0] > 3600 or not _DATES[1]:
        try:
            _DATES = (time.time(), available_dates())
        except Exception:
            pass
    return _DATES[1]


_STATIONS_TS = 0.0


def all_stations():
    """Toutes les gares Max (union de quelques jours d'open data). Caché, rafraîchi périodiquement."""
    global _STATIONS, _STATIONS_TS
    if _STATIONS is None or time.time() - _STATIONS_TS > config.STATIONS_TTL:
        names = set()
        dates = dataset_dates()
        n = len(dates)
        picks = [dates[i] for i in (1, n // 3, 2 * n // 3, n - 2) if 0 <= i < n] if n else []
        for d in dict.fromkeys(picks):
            try:
                for e in fetch_oui_edges(d):
                    names.add(e["o"]); names.add(e["d"])
            except Exception:
                pass
        if names or _STATIONS is None:
            _STATIONS = sorted(names)
            _STATIONS_TS = time.time()
    return _STATIONS


def search_stations(q, limit=8):
    nq = normalize(q)
    if not nq:
        return []
    hits = [s for s in all_stations() if nq in normalize(s)]
    hits.sort(key=lambda s: (not normalize(s).startswith(nq), len(s)))
    return hits[:limit]


# Paris : le jeu de données regroupe toutes les gares sous « PARIS (intramuros) ». L'axe du train
# indique la gare réelle ; changer de gare demande de traverser Paris (métro / RER).
PARIS_BY_AXE = {"SUD EST": "Paris Gare de Lyon", "ATLANTIQUE": "Paris Montparnasse", "NORD": "Paris Nord",
                "EST": "Paris Est", "IC NUIT": "Paris Austerlitz", "INTERNATIONAL": "Paris Gare de Lyon"}
PARIS_COORDS = {"Paris Gare de Lyon": (48.8443, 2.3744), "Paris Montparnasse": (48.8412, 2.3209),
                "Paris Nord": (48.8809, 2.3553), "Paris Est": (48.8766, 2.3592),
                "Paris Austerlitz": (48.8420, 2.3653), "Paris Bercy": (48.8390, 2.3826)}
PARIS_CHANGE = {frozenset(("Paris Gare de Lyon", "Paris Bercy")): 25, frozenset(("Paris Nord", "Paris Est")): 25,
                frozenset(("Paris Gare de Lyon", "Paris Austerlitz")): 40,
                frozenset(("Paris Austerlitz", "Paris Bercy")): 40}
PARIS_CHANGE_DEFAULT = 60        # traverser Paris en métro / RER, avec une marge


def city_station(label, edge):
    """Gare réelle d'un train dans une ville multi-gares (Paris seulement : ailleurs, inconnue)."""
    if label != "PARIS (intramuros)":
        return None
    axe, ent = edge.get("axe", ""), edge.get("entity", "")
    if axe.startswith("IC") and axe != "IC NUIT":
        return "Paris Bercy" if "CLERMONT" in ent else "Paris Austerlitz"
    return PARIS_BY_AXE.get(axe)


def transfer_min(station, arriving, departing):
    """Temps de correspondance mini entre deux trains Max à une gare (changement de gare compris)."""
    a, b = city_station(station, arriving), city_station(station, departing)
    if a and b:
        return config.MIN_CONNECTION_MIN if a == b else PARIS_CHANGE.get(frozenset((a, b)), PARIS_CHANGE_DEFAULT)
    return min_connection(station)


def min_connection(station):
    return config.MIN_CONNECTION_INTRAMUROS if "(intramuros)" in station else config.MIN_CONNECTION_MIN


def night_overlap(start, end):
    """[start,end] (minutes absolues : train ou attente en gare) empiète-t-il vraiment sur la nuit ?
    On regarde le cœur de la nuit (0 h 30 – 5 h) avec au moins 30 min de chevauchement : une arrivée
    à 23 h 20 ou un départ à 5 h 59 ne font pas un « trajet de nuit »."""
    for k in range(0, 5):  # autour de chaque minuit (0, 1440, 2880, ...)
        w0, w1 = k * 1440 + 30, k * 1440 + 300
        if min(end, w1) - max(start, w0) >= 30:
            return True
    return False


def _reach_levels(edges, targets, k):
    """levels[i] = gares d'où l'on peut atteindre `targets` en au plus i trains (sans tenir compte
    des horaires). Sert à élaguer la recherche : inutile de suivre un train vers une gare d'où la
    destination est hors de portée avec les correspondances restantes."""
    rev = {}
    for e in edges:
        rev.setdefault(e["d"], set()).add(e["o"])
    def with_twins(s):                    # une gare jumelle « vaut » l'autre (changement de gare)
        return s | {t for x in s for t, _, _ in TWINS.get(x, ())}

    levels = [with_twins(set(targets))]
    for _ in range(k):
        cur = levels[-1]
        nxt = set(cur)
        for s in cur:
            nxt |= rev.get(s, set())
        levels.append(with_twins(nxt))
    return levels


def search(edges, origins, targets, max_conn=3, max_results=40, min_dep=0, max_dep=1440):
    """DFS horodaté O -> targets, <= max_conn correspondances, sans repasser par une gare."""
    by_origin = {}
    for e in edges:
        by_origin.setdefault(e["o"], []).append(e)
    origins, targets = set(origins), set(targets)
    levels = _reach_levels(edges, targets, max_conn + 1)
    found = []

    def dfs(station, arrived_at, path, visited):
        if len(path) > max_conn + 1:
            return
        left = max_conn - len(path)            # trains encore possibles après celui-ci
        for e, need in _departures(by_origin, station, path):
            if e["d"] in visited or e["d"] not in levels[max(0, left)]:
                continue
            if not path and not (min_dep <= e["dep"] <= max_dep):  # fenêtre de départ (1er train)
                continue
            if path:
                wait = e["dep"] - arrived_at
                if wait < need or wait > config.MAX_LAYOVER_MIN:
                    continue
            total = (e["arr"] - path[0]["dep"]) if path else (e["arr"] - e["dep"])
            if total > config.MAX_TOTAL_MIN:
                continue
            newpath = path + [e]
            if e["d"] in targets:
                found.append(newpath)
                continue                        # arrivé : inutile de repartir
            if len(newpath) <= max_conn:
                dfs(e["d"], e["arr"], newpath, visited | {e["d"], e["o"]})

    for o in origins:
        dfs(o, 0, [], {o})

    seen, uniq = set(), []
    for p in found:
        sig = tuple((l["train"], l["o"], l["d"]) for l in p)   # même train, autre gare de montée : trajet distinct
        if sig not in seen:
            seen.add(sig)
            uniq.append(p)
    uniq.sort(key=lambda p: (p[-1]["arr"] - p[0]["dep"], len(p)))
    return uniq[:max_results]


def reachable(edges, origins, max_conn=1, min_dep=0, max_dep=1440):
    """Gares atteignables en Max depuis origins, avec le nb mini de trains et un exemple."""
    by_origin = {}
    for e in edges:
        by_origin.setdefault(e["o"], []).append(e)
    origins = set(origins)
    best = {}

    def dfs(station, arrived_at, path, visited):
        for e, need in _departures(by_origin, station, path):
            if e["d"] in visited:
                continue
            if not path and not (min_dep <= e["dep"] <= max_dep):
                continue
            if path:
                wait = e["dep"] - arrived_at
                if wait < need or wait > config.MAX_LAYOVER_MIN:
                    continue
            newpath = path + [e]
            cur = best.get(e["d"])
            if cur is None or len(newpath) < cur[0]:
                best[e["d"]] = (len(newpath), newpath)
            if len(newpath) <= max_conn:
                dfs(e["d"], e["arr"], newpath, visited | {e["d"], e["o"]})

    for o in origins:
        dfs(o, 0, [], {o})
    return best



def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def daterange(start, end):
    s, e = Date.fromisoformat(start), Date.fromisoformat(end)
    cur = s
    while cur <= e:
        yield cur.isoformat()
        cur += timedelta(days=1)


WEEKDAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def weekday(d):
    return WEEKDAYS[Date.fromisoformat(d).weekday()]

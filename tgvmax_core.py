# -*- coding: utf-8 -*-
"""Cœur métier : lecture de l'open data SNCF tgvmax + recherche de trajets Max."""

import bisect
import json
import math
import re
import threading
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
    ("MASSY TGV", "MARNE LA VALLEE CHESSY", 100, "RER B et RER A, environ 1 h 15"),
    ("MASSY TGV", "AEROPORT ROISSY CDG 2 TGV", 90, "RER B, environ 1 h 05"),
    ("MARNE LA VALLEE CHESSY", "AEROPORT ROISSY CDG 2 TGV", 90, "RER A et RER B, environ 1 h 10"),
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


# Paris intra-muros <-> gare TGV d'Île-de-France : tout dépend de la gare parisienne réelle
# (Montparnasse -> Roissy, c'est 1 h, pas 35 min). Minutes de changement (marge comprise), comment faire.
_CDG = "billet aéroport ≈ 13 €"
PARIS_ANNEX = {
    ("Paris Nord", "AEROPORT ROISSY CDG 2 TGV"): (50, f"RER B direct, environ 35 min, {_CDG}"),
    ("Paris Est", "AEROPORT ROISSY CDG 2 TGV"): (55, f"RER B et 5 min à pied entre Paris Est et Paris Nord, environ 40 min, {_CDG}"),
    ("Paris Gare de Lyon", "AEROPORT ROISSY CDG 2 TGV"): (65, f"RER D et RER B, environ 50 min, {_CDG}"),
    ("Paris Bercy", "AEROPORT ROISSY CDG 2 TGV"): (70, f"métro et RER B, environ 55 min, {_CDG}"),
    ("Paris Austerlitz", "AEROPORT ROISSY CDG 2 TGV"): (75, f"RER C et RER B, environ 1 h, {_CDG}"),
    ("Paris Montparnasse", "AEROPORT ROISSY CDG 2 TGV"): (80, f"métro 4 et RER B, environ 1 h, {_CDG}"),
    ("Paris Gare de Lyon", "MARNE LA VALLEE CHESSY"): (55, "RER A direct, environ 40 min"),
    ("Paris Bercy", "MARNE LA VALLEE CHESSY"): (60, "RER A et 10 min à pied entre Bercy et Gare de Lyon, environ 45 min"),
    ("Paris Austerlitz", "MARNE LA VALLEE CHESSY"): (65, "métro et RER A, environ 50 min"),
    ("Paris Nord", "MARNE LA VALLEE CHESSY"): (70, "RER B ou D et RER A, environ 55 min"),
    ("Paris Est", "MARNE LA VALLEE CHESSY"): (75, "métro et RER A, environ 1 h"),
    ("Paris Montparnasse", "MARNE LA VALLEE CHESSY"): (80, "métro et RER A, environ 1 h"),
    ("Paris Austerlitz", "MASSY TGV"): (55, "RER C direct, environ 40 min"),
    ("Paris Nord", "MASSY TGV"): (55, "RER B direct, environ 40 min"),
    ("Paris Montparnasse", "MASSY TGV"): (55, "métro 4 et RER B, environ 40 min"),
    ("Paris Gare de Lyon", "MASSY TGV"): (65, "RER D et RER B, environ 50 min"),
    ("Paris Bercy", "MASSY TGV"): (70, "métro et RER B ou C, environ 55 min"),
    ("Paris Est", "MASSY TGV"): (65, "RER B et 5 min à pied entre Paris Est et Paris Nord, environ 50 min"),
    ("Paris Montparnasse", "VERSAILLES CHANTIERS"): (40, "train direct, environ 15 min"),
    ("Paris Austerlitz", "VERSAILLES CHANTIERS"): (60, "RER C direct, environ 45 min"),
}
for (_p, _x), _v in list(PARIS_ANNEX.items()):
    if _x == "MASSY TGV":
        PARIS_ANNEX[(_p, "MASSY PALAISEAU")] = _v
for _p in ("Paris Nord", "Paris Est", "Paris Gare de Lyon", "Paris Bercy"):
    PARIS_ANNEX.setdefault((_p, "VERSAILLES CHANTIERS"), (75, "métro et train via Montparnasse, environ 1 h"))


def twin_change(a, b, arriving=None, departing=None):
    """Passer de la gare a (arrivée par le train `arriving`) à sa jumelle b (départ par `departing`) :
    (minutes de changement, comment faire), ou None si a et b ne sont pas jumelles."""
    base = next(((m, n) for x, m, n in TWINS.get(a, ()) if x == b), None)
    if base is None:
        return None
    if a == "PARIS (intramuros)" and arriving is not None:
        return PARIS_ANNEX.get((city_station(a, arriving), b), base)
    if b == "PARIS (intramuros)" and departing is not None:
        return PARIS_ANNEX.get((city_station(b, departing), a), base)
    return base


def twin_note(a, b, arriving=None, departing=None):
    """Comment passer de la gare a à la gare b (gares jumelles), ou None."""
    t = twin_change(a, b, arriving, departing)
    return t and t[1]


_IDX = {}            # id(liste de trains du jour) -> (liste, index) : construit une fois par jour
_IDX_LOCK = threading.Lock()


def _index(edges):
    """Trains par gare de départ, triés par heure (pour ne lire que ceux de la fenêtre utile)."""
    hit = _IDX.get(id(edges))
    if hit and hit[0] is edges:
        return hit[1]
    by = {}
    for i, e in enumerate(edges):
        by.setdefault(e["o"], []).append((e["dep"], i, e))
    idx = {}
    for st, v in by.items():
        v.sort(key=lambda x: (x[0], x[1]))
        idx[st] = ([x[0] for x in v], [(x[1], x[2]) for x in v])
    rev = {}
    for e in edges:
        rev.setdefault(e["d"], set()).add(e["o"])
    idx[None] = rev                      # clé spéciale : graphe inverse, pour _reach_levels
    with _IDX_LOCK:
        if len(_IDX) >= 70:                  # tout le calendrier (~2 mois) tient dedans
            _IDX.pop(next(iter(_IDX)))
        _IDX[id(edges)] = (edges, idx)
    return idx


def _window(idx, station, lo, hi):
    """Trains partant de station entre lo et hi, dans l'ordre de l'open data."""
    hit = idx.get(station)
    if not hit:
        return ()
    deps, items = hit
    sel = items[bisect.bisect_left(deps, lo):bisect.bisect_right(deps, hi)]
    sel.sort(key=lambda x: x[0])
    return [e for _, e in sel]


def _departures(idx, station, path, lo, hi):
    """Trains au départ de la gare… ou de sa jumelle (changement de gare) : (train, attente mini).
    Premier train : départ entre lo et hi ; ensuite : dans l'attente maximale de correspondance."""
    if not path:
        for e in _window(idx, station, lo, hi):
            yield e, 0
        return
    arrived = path[-1]["arr"]
    hi = arrived + config.MAX_LAYOVER_MIN
    for e in _window(idx, station, arrived, hi):
        yield e, None                        # attente mini calculée seulement si besoin (coûteuse)
    for other, mins, _ in TWINS.get(station, ()):
        paris = "PARIS (intramuros)" in (station, other)
        for e in _window(idx, other, arrived, hi):
            yield e, (twin_change(station, other, path[-1], e)[0] if paris else mins)


def normalize(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower().replace("-", " ").replace("(intramuros)", "").replace(".", "").strip()


# Gare jumelle ajoutée d'office à une recherche si on la rejoint en moins d'une heure (marge comprise) :
# chercher « Metz » propose aussi Lorraine TGV, « Avignon TGV » aussi Avignon Centre, « Massy » aussi Paris.
NEARBY_MAX_MIN = 60


def resolve_area(city, stations):
    """(gares, voisines) : les gares de la ville cherchée, puis leurs gares jumelles proches.
    voisines : gare ajoutée -> (gare cherchée la plus proche, minutes, comment y aller)."""
    base = _match_city(city, stations)
    extra = {}
    for s in base:
        for t, mins, note in TWINS.get(s, ()):
            if mins <= NEARBY_MAX_MIN and t not in base and t not in extra and (not stations or t in stations):
                extra[t] = (s, mins, note)
    return base + list(extra), extra


def resolve_city(city, stations):
    """Libellés de gare du dataset pour `city` : la ville (alias, exact, ou contient) et ses gares voisines."""
    return resolve_area(city, stations)[0]


def note_minutes(note, default):
    """« RER B direct, environ 40 min » -> 40 (temps de trajet annoncé), sinon default."""
    m = re.search(r"environ (\d+) h(?: (\d+))?|environ (\d+) min", note or "")
    if not m:
        return default
    return int(m.group(3)) if m.group(3) else int(m.group(1)) * 60 + int(m.group(2) or 0)


def _match_city(city, stations):
    """Libellés de gare du dataset correspondant à `city` (alias, exact, ou contient)."""
    key = city.strip().lower()
    if city.strip() in MAIN_STATION_KEY:          # gare choisie dans la liste : la ville et ses gares annexes
        key = MAIN_STATION_KEY[city.strip()]
    if key in CITY_ALIASES:
        hit = [s for s in CITY_ALIASES[key] if s in stations]
        return hit or CITY_ALIASES[key]
    nq = normalize(key)
    exact = sorted(s for s in stations if normalize(s) == nq)
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
        if x["origine"] == x["destination"]:   # Part-Dieu -> Perrache : même libellé « LYON (intramuros) »
            continue
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
    rev = _index(edges)[None]             # gare -> gares d'où un train y va (calculé une fois par jour)
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
    idx = _index(edges)
    origins, targets = set(origins), set(targets)
    levels = _reach_levels(edges, targets, max_conn + 1)
    found = []

    def dfs(station, arrived_at, path, visited):
        if len(path) > max_conn + 1:
            return
        left = max_conn - len(path)            # trains encore possibles après celui-ci
        lvl = levels[max(0, left)]
        for e, need in _departures(idx, station, path, min_dep, max_dep):
            if e["d"] in visited or e["d"] not in lvl:
                continue
            if path:
                if need is None:
                    need = transfer_min(station, path[-1], e)
                if e["dep"] - arrived_at < need:
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

    for o in sorted(origins):             # ordre stable (résultats identiques d'un lancement à l'autre)
        dfs(o, 0, [], {o})

    seen, uniq = set(), []
    for p in found:
        # même train, autre gare de montée (ou autre horaire, ex. Perrache / Part-Dieu) : trajet distinct
        sig = tuple((l["train"], l["o"], l["d"], l["dep"]) for l in p)
        if sig not in seen:
            seen.add(sig)
            uniq.append(p)
    uniq.sort(key=lambda p: (p[-1]["arr"] - p[0]["dep"], len(p)))
    # les directs sont toujours gardés (un train de nuit direct est long mais imbattable)
    direct = [p for p in uniq if len(p) == 1]
    rest = [p for p in uniq if len(p) > 1][:max(0, max_results - len(direct))]
    return sorted(direct + rest, key=lambda p: (p[-1]["arr"] - p[0]["dep"], len(p)))


def reachable(edges, origins, max_conn=1, min_dep=0, max_dep=1440):
    """Gares atteignables en Max depuis origins, avec le nb mini de trains et un exemple."""
    idx = _index(edges)
    origins_list = list(origins)
    best = {}

    def dfs(station, arrived_at, path, visited):
        for e, need in _departures(idx, station, path, min_dep, max_dep):
            if e["d"] in visited:
                continue
            if path:
                if need is None:
                    need = transfer_min(station, path[-1], e)
                if e["dep"] - arrived_at < need:
                    continue
            newpath = path + [e]
            cur = best.get(e["d"])
            if cur is None or len(newpath) < cur[0]:
                best[e["d"]] = (len(newpath), newpath)
            if len(newpath) <= max_conn:
                dfs(e["d"], e["arr"], newpath, visited | {e["d"], e["o"]})

    for o in dict.fromkeys(origins_list):  # gare principale d'abord : l'exemple de trajet part d'elle
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

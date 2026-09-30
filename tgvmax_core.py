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
    "paris": ["PARIS (intramuros)"],
    "lyon": ["LYON (intramuros)"],
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
    "nice": ["NICE VILLE"],
    "toulouse": ["TOULOUSE MATABIAU"],
    "grenoble": ["GRENOBLE"],
}


def normalize(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower().replace("-", " ").replace("(intramuros)", "").replace(".", "").strip()


def resolve_city(city, stations):
    """Libellés de gare du dataset correspondant à `city` (alias, exact, ou contient)."""
    key = city.strip().lower()
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
    levels = [set(targets)]
    for _ in range(k):
        cur = levels[-1]
        nxt = set(cur)
        for s in cur:
            nxt |= rev.get(s, set())
        levels.append(nxt)
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
        for e in by_origin.get(station, []):
            if e["d"] in visited or e["d"] not in levels[max(0, left)]:
                continue
            if not path and not (min_dep <= e["dep"] <= max_dep):  # fenêtre de départ (1er train)
                continue
            if path:
                wait = e["dep"] - arrived_at
                if wait < min_connection(station) or wait > config.MAX_LAYOVER_MIN:
                    continue
            total = (e["arr"] - path[0]["dep"]) if path else (e["arr"] - e["dep"])
            if total > config.MAX_TOTAL_MIN:
                continue
            newpath = path + [e]
            if e["d"] in targets:
                found.append(newpath)
                continue                        # arrivé : inutile de repartir
            if len(newpath) <= max_conn:
                dfs(e["d"], e["arr"], newpath, visited | {e["d"]})

    for o in origins:
        dfs(o, 0, [], {o})

    seen, uniq = set(), []
    for p in found:
        sig = tuple(l["train"] for l in p)
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
        for e in by_origin.get(station, []):
            if e["d"] in visited:
                continue
            if not path and not (min_dep <= e["dep"] <= max_dep):
                continue
            if path:
                wait = e["dep"] - arrived_at
                if wait < min_connection(station) or wait > config.MAX_LAYOVER_MIN:
                    continue
            newpath = path + [e]
            cur = best.get(e["d"])
            if cur is None or len(newpath) < cur[0]:
                best[e["d"]] = (len(newpath), newpath)
            if len(newpath) <= max_conn:
                dfs(e["d"], e["arr"], newpath, visited | {e["d"]})

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

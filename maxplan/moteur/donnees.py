"""Open data SNCF « tgvmax » : places Max ouvertes, jours couverts, liste des gares."""

import json
import time
import urllib.request

from maxplan import config
from maxplan.base import hhmm_to_min, normalize


API = "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/tgvmax"


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

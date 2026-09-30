# -*- coding: utf-8 -*-
"""Horaires SNCF en local (GTFS open data) : calcul des trajets TER sans l'API SNCF.

L'export GTFS de la SNCF (tous les trains et cars TER, ~6 mois d'horaires, mis à jour chaque jour)
est téléchargé puis chargé en mémoire. Les trajets TER se calculent avec l'algorithme « Connection
Scan » (CSA) : on parcourt les départs de la journée dans l'ordre et on garde l'arrivée la plus tôt
à chaque gare. Résultat : aucune requête à l'API SNCF pour les compléments TER, et des horaires
réels bien au-delà de l'horizon de l'API (~4 semaines).

Le résultat de journey() a la même forme que navitia.Navitia.journey().
"""

import bisect
import csv
import io
import os
import threading
import time
import unicodedata
import urllib.request
import zipfile
from datetime import date as Date, timedelta

import config
import regions
from tgvmax_core import haversine_km

URL = "https://eu.ftp.opendatasoft.com/sncf/plandata/Export_OpenData_SNCF_GTFS_NewTripId.zip"
ZIP_FILE = os.path.join(config.DATA_DIR, "gtfs-sncf.zip")

# Types de circulation (préfixe des quais « StopPoint:OCE<type>-<UIC> ») gardés pour les compléments :
# TER et Intercités à réservation ; pas de grande vitesse ni de trains/cars à réservation spéciale.
MODES = {"Train TER": "TER", "TramTrain": "TER", "Train": "TER", "Navette": "TER",
         "Car TER": "Car TER", "INTERCITES": "Intercités"}
MIN_TRANSFER = 5          # minutes pour changer de train dans une même gare
HORIZON = 300             # on ne cherche pas au-delà de 5 h après l'heure de départ

_lock = threading.Lock()
_data = None              # dict chargé (voir load())
_days = {}                # cache : date AAAAMMJJ -> connexions triées
_memo = {}                # cache des trajets calculés (vidé à chaque rechargement)


def _fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = " " + s.replace("-", " ").replace("'", " ") + " "
    return s.replace(" sainte ", " ste ").replace(" saint ", " st ").strip()


def _mins(hms):
    h, m, _ = hms.split(":")
    return int(h) * 60 + int(m)


def _hm(x):
    x %= 1440
    return f"{x // 60:02d}:{x % 60:02d}"


# ------------------------------------------------------------------ chargement
def download(force=False):
    """Télécharge l'export s'il manque ou s'il a changé (If-Modified-Since). True si nouveau fichier."""
    req = urllib.request.Request(URL)
    if os.path.exists(ZIP_FILE) and not force:
        req.add_header("If-Modified-Since", time.strftime("%a, %d %b %Y %H:%M:%S GMT",
                                                          time.gmtime(os.path.getmtime(ZIP_FILE))))
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return False
        raise
    tmp = ZIP_FILE + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    zipfile.ZipFile(tmp).testzip()
    os.replace(tmp, ZIP_FILE)
    return True


def load():
    """Charge le GTFS en mémoire (~2 s). Remplace les données d'un coup (les recherches en cours
    continuent sur l'ancienne version)."""
    global _data, _days
    z = zipfile.ZipFile(ZIP_FILE)
    rows = lambda n: csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8-sig"))

    area_idx, areas = {}, []          # gares (StopArea)
    point_area, point_mode = {}, {}
    for s in rows("stops.txt"):
        if s["location_type"] == "1":
            area_idx[s["stop_id"]] = len(areas)
            uic = s["stop_id"].rsplit("OCE", 1)[-1]
            areas.append({"id": s["stop_id"], "uic": uic, "name": s["stop_name"],
                          "lat": float(s["stop_lat"]), "lon": float(s["stop_lon"]), "rail": False, "major": False})
    for s in rows("stops.txt"):
        if s["location_type"] != "1" and s["parent_station"] in area_idx:
            a = area_idx[s["parent_station"]]
            point_area[s["stop_id"]] = a
            kind = s["stop_id"].split(":OCE", 1)[-1].rsplit("-", 1)[0]
            point_mode[s["stop_id"]] = kind
            if kind in ("Train TER", "TramTrain", "Train", "INTERCITES", "TGV INOUI", "OUIGO"):
                areas[a]["rail"] = True
            if kind in ("TGV INOUI", "INTERCITES", "OUIGO"):
                areas[a]["major"] = True

    services = {}
    for c in rows("calendar_dates.txt"):
        if c["exception_type"] == "1":
            services.setdefault(c["service_id"], set()).add(int(c["date"]))
    trip_service = {t["trip_id"]: t["service_id"] for t in rows("trips.txt")}

    trips = {}                        # trip_id -> [(gare, arrivée, départ, montée ok, descente ok)]
    trip_mode = {}
    for st in rows("stop_times.txt"):
        p = st["stop_id"]
        a = point_area.get(p)
        if a is None:
            continue
        mode = MODES.get(point_mode.get(p))
        tid = st["trip_id"]
        if mode is None:
            trip_mode[tid] = None     # un seul arrêt TGV/OUIGO… suffit à écarter la circulation
            continue
        trip_mode.setdefault(tid, mode)
        trips.setdefault(tid, []).append((int(st["stop_sequence"]), a, _mins(st["arrival_time"]),
                                          _mins(st["departure_time"]), st["pickup_type"] != "1",
                                          st["drop_off_type"] != "1"))
    by_date = {}
    tlist = []
    for tid, stops in trips.items():
        if not trip_mode.get(tid) or len(stops) < 2:
            continue
        stops.sort()
        ti = len(tlist)
        tlist.append((trip_mode[tid], [s[1:] for s in stops]))
        for d in services.get(trip_service.get(tid), ()):
            by_date.setdefault(d, []).append(ti)

    all_dates = sorted(by_date)
    new = {"areas": areas, "by_uic": {a["uic"]: i for i, a in enumerate(areas)},
           "trips": tlist, "by_date": by_date,
           "first": all_dates[0] if all_dates else None, "last": all_dates[-1] if all_dates else None,
           "loaded": time.time(),
           "names": [(_fold(a["name"]), i) for i, a in enumerate(areas)]}
    with _lock:
        _data, _days = new, {}
        _memo.clear()

    return len(tlist)


def ready():
    return _data is not None


def covers(ymd):
    d = int(ymd.replace("-", ""))
    return bool(_data) and _data["first"] <= d <= _data["last"]


def coverage():
    if not _data:
        return None
    return {"start": str(_data["first"]), "end": str(_data["last"])}


# ------------------------------------------------------------------ connexions d'une journée
def _connections(ymd):
    """Tous les tronçons (départ, arrivée, gare A, gare B, circulation, rang) d'une journée, triés par
    heure de départ ; les circulations de la veille qui passent minuit sont incluses (décalées)."""
    d = int(ymd.replace("-", ""))
    with _lock:
        hit = _days.get(d)
        data = _data
    if hit:
        return hit
    prev = int((Date.fromisoformat(ymd) - timedelta(days=1)).strftime("%Y%m%d"))
    conns = []
    for day, shift in ((prev, -1440), (d, 0)):
        for ti in data["by_date"].get(day, ()):
            stops = data["trips"][ti][1]
            if shift and stops[-1][1] < 1440:
                continue
            for k in range(len(stops) - 1):
                a, b = stops[k], stops[k + 1]
                if a[2] + shift < 0:
                    continue
                conns.append((a[2] + shift, b[1] + shift, a[0], b[0], ti, k))
    conns.sort()
    deps = [c[0] for c in conns]
    with _lock:
        if len(_days) > 12:
            _days.clear()
        _days[d] = (conns, deps)
    return conns, deps


def _csa(conns, deps, src, dst, t0, max_legs, stop_at=None):
    """Arrivée au plus tôt src -> dst en au plus max_legs circulations. Renvoie la liste des tronçons
    empruntés [(circulation, rang montée, rang descente)] ou None. stop_at : inutile d'aller au-delà
    (une meilleure solution est déjà connue)."""
    INF = 10 ** 9
    end = min(t0 + 2 * HORIZON, stop_at if stop_at is not None else INF)
    best = {src: t0}
    legs_at = {src: 0}
    via = {}                          # gare -> (circulation, rang montée, rang descente, gare de montée)
    boarded = {}                      # circulation -> (rang montée, gare de montée, nb de circulations)
    trips = _data["trips"]
    for i in range(bisect.bisect_left(deps, t0), len(conns)):
        dep, arr, a, b, ti, k = conns[i]
        if dep >= end or best.get(dst, INF) <= dep:
            break
        stops = trips[ti][1]
        if ti not in boarded:
            if dep > t0 + HORIZON:        # on ne monte plus après l'horizon, mais on finit les trajets en cours
                continue
            if not stops[k][3]:       # montée interdite à cet arrêt
                continue
            t = best.get(a, INF)
            if t == INF or t + (0 if a == src else MIN_TRANSFER) > dep:
                continue
            n = legs_at[a] + 1
            if n > max_legs:
                continue
            boarded[ti] = (k, a, n)
        k0, a0, n = boarded[ti]
        if stops[k + 1][4] and arr < best.get(b, INF):
            best[b] = arr
            legs_at[b] = n
            via[b] = (ti, k0, k + 1, a0)
    if dst not in via:
        return None
    path, cur = [], dst
    while cur != src and cur in via:
        ti, k0, k1, a0 = via[cur]
        path.append((ti, k0, k1))
        cur = a0
        if len(path) > max_legs:
            return None
    return path[::-1] if cur == src else None


def knows(stop_id):
    """La gare (identifiant « …:<UIC> ») est-elle dans le GTFS ?"""
    return bool(_data) and str(stop_id).rsplit(":", 1)[-1] in _data["by_uic"]


def journey(from_id, to_id, ymd, hhmm, max_transfers=3):

    """Meilleur trajet TER from -> to partant après hhmm (identifiants « …:87xxxxxx » : code UIC).
    Même format que navitia.journey(). None si rien, ou si la gare n'est pas dans le GTFS."""
    if not _data or not covers(ymd):
        return None
    ua, ub = str(from_id).rsplit(":", 1)[-1], str(to_id).rsplit(":", 1)[-1]
    src, dst = _data["by_uic"].get(ua), _data["by_uic"].get(ub)
    if src is None or dst is None or src == dst:
        return None
    key = (src, dst, ymd, hhmm, max_transfers)
    with _lock:
        if key in _memo:
            return _memo[key]
    h, m = hhmm.split(":")
    t0 = int(h) * 60 + int(m)
    conns, deps = _connections(ymd)
    # comme avec l'API : on ne change de train que si ça fait vraiment arriver plus tôt (20 min par
    # changement) ; chaque passe ne cherche que ce qui peut battre la meilleure solution déjà trouvée
    best = None
    for legs in range(1, max_transfers + 2):
        stop_at = best[0] - 20 * (legs - 1) if best else None
        path = _csa(conns, deps, src, dst, t0, legs, stop_at)
        if path:
            arr = _data["trips"][path[-1][0]][1][path[-1][2]][1]
            score = arr + 20 * (len(path) - 1)
            if best is None or score < best[0]:
                best = (score, path)
    res = _format(best[1]) if best else None
    with _lock:
        if len(_memo) > 20000:
            _memo.clear()
        _memo[key] = res
    return res


def _format(path):
    trips, areas = _data["trips"], _data["areas"]
    sections, modes, networks = [], [], []
    for ti, k0, k1 in path:
        mode, stops = trips[ti]
        a, b = areas[stops[k0][0]], areas[stops[k1][0]]
        mid_lat, mid_lon = (a["lat"] + b["lat"]) / 2, (a["lon"] + b["lon"]) / 2
        code = regions.locate(mid_lat, mid_lon)
        net = regions.REGIONS.get(code, (None, "TER"))[1] if code and mode != "Intercités" else mode
        modes.append(mode)
        networks.append(net)
        sections.append({
            "mode": mode, "network": net, "from": a["name"], "to": b["name"],
            "dep": _hm(stops[k0][2]), "arr": _hm(stops[k1][1]),
            "dist_km": haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]),
            "lat": mid_lat, "lon": mid_lon,
            "coords": [[areas[s[0]]["lat"], areas[s[0]]["lon"]] for s in stops[k0:k1 + 1]],
        })
    first, last = trips[path[0][0]][1][path[0][1]], trips[path[-1][0]][1][path[-1][2]]
    return {
        "duration_min": last[1] - first[2], "transfers": len(path) - 1,
        "modes": modes, "networks": networks, "sections": sections,
        "distance_km": round(sum(s["dist_km"] for s in sections)),
        "departure": _hm(first[2]), "arrival": _hm(last[1]), "source": "gtfs",
    }


# ------------------------------------------------------------------ recherche de gares
def places(q, limit=8):
    """Gares et arrêts dont le nom contient q (gares ferroviaires d'abord)."""
    if not _data:
        return []
    fq = _fold(q).strip()
    if len(fq) < 2:
        return []
    hits = [i for name, i in _data["names"] if fq in name]
    areas = _data["areas"]
    hits.sort(key=lambda i: (not areas[i]["rail"], not _fold(areas[i]["name"]).startswith(fq),
                             not areas[i]["major"], len(areas[i]["name"])))
    return [{"id": "stop_area:SNCF:" + areas[i]["uic"], "name": areas[i]["name"],
             "lat": areas[i]["lat"], "lon": areas[i]["lon"]} for i in hits[:limit]]


def refresh_loop():
    """Au démarrage puis chaque nuit : télécharge l'export s'il a changé et le recharge."""
    while True:
        try:
            fresh = download(force=not os.path.exists(ZIP_FILE))
            if fresh or not _data:
                n = load()
                print(f"    Horaires GTFS chargés : {n} circulations TER/Intercités "
                      f"({_data['first']} → {_data['last']}).", flush=True)
        except Exception as e:
            print("    Horaires GTFS indisponibles pour l'instant :", e, flush=True)
            if not _data and os.path.exists(ZIP_FILE):
                try:
                    load()
                except Exception:
                    pass
        time.sleep(6 * 3600)

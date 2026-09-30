# -*- coding: utf-8 -*-
"""Horaires en local (GTFS open data) : calcul des trajets TER et cars régionaux sans l'API SNCF.

Sources (voir feeds.py) : l'export GTFS de la SNCF (TER, cars TER, Intercités, ~6 mois) et une
quarantaine de réseaux régionaux de cars publiés sur transport.data.gouv.fr (ZOU!, liO, Aléop…).
Tout est chargé en mémoire sous une forme compacte, puis les trajets se calculent avec l'algorithme
« Connection Scan » (CSA) : on parcourt les départs de la journée dans l'ordre en gardant l'arrivée la
plus tôt à chaque arrêt, avec des correspondances à pied entre arrêts proches (gare ↔ gare routière).

Le résultat de journey() a la même forme que navitia.Navitia.journey().
"""

import bisect
import csv
import io
import math
import os
import threading
import time
import unicodedata
import urllib.request
import zipfile
from array import array
from datetime import date as Date, timedelta

import config
import feeds
import regions
from tgvmax_core import haversine_km

DIR = os.path.join(config.DATA_DIR, "gtfs")
KEEP = ("agency.txt", "stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "calendar.txt", "calendar_dates.txt")

# GTFS SNCF : type de circulation lu dans l'identifiant du quai (« StopPoint:OCE<type>-<UIC> »).
# On garde TER, cars TER et Intercités à réservation ; pas la grande vitesse ni le car à réservation.
SNCF_MODES = {"Train TER": "TER", "TramTrain": "TER", "Train": "TER", "Navette": "TER",
              "Car TER": "Car TER", "INTERCITES": "Intercités"}
MIN_TRANSFER = 5          # minutes pour changer de véhicule au même arrêt
WALK_MAX_M = 350          # correspondance à pied entre arrêts proches
HORIZON = 300             # on ne monte plus dans un véhicule au-delà de 5 h après l'heure de départ
F_PICK, F_DROP = 1, 2

_lock = threading.Lock()
_data = None
_days = {}                # date AAAAMMJJ -> (connexions triées, heures de départ)
_memo = {}                # trajets déjà calculés
_day_locks = {}           # une seule construction à la fois par journée
CELL = 0.5                # maillage géographique (degrés) pour ne parcourir que la zone utile


def _fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = " " + s.replace("-", " ").replace("'", " ") + " "
    return " ".join(s.replace(" sainte ", " ste ").replace(" saint ", " st ").split())


def _mins(hms):
    h, m, _ = hms.split(":")
    return int(h) * 60 + int(m)


def _hm(x):
    x %= 1440
    return f"{x // 60:02d}:{x % 60:02d}"


def _ymd(d):
    return int(d.strftime("%Y%m%d"))


# ------------------------------------------------------------------ téléchargement
def _path(fid):
    return os.path.join(DIR, fid + ".zip")


def download(fid, url, max_age):
    """Télécharge un réseau s'il manque ou date de plus de max_age secondes, et n'en garde que les
    fichiers utiles (sans les tracés, souvent l'essentiel du poids). True si nouveau fichier."""
    p = _path(fid)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < max_age:
        return False
    os.makedirs(DIR, exist_ok=True)
    tmp = p + ".dl"
    urllib.request.urlretrieve(url, tmp)
    with zipfile.ZipFile(tmp) as src, zipfile.ZipFile(p + ".tmp", "w", zipfile.ZIP_DEFLATED) as dst:
        names = {n.rsplit("/", 1)[-1]: n for n in src.namelist()}
        if "stop_times.txt" not in names:
            raise ValueError("pas de stop_times.txt")
        for n in KEEP:
            if n in names:
                dst.writestr(n, src.read(names[n]))
    os.replace(p + ".tmp", p)
    os.remove(tmp)
    return True


# ------------------------------------------------------------------ chargement
class _Builder:
    def __init__(self):
        self.areas, self.by_key = [], {}
        self.trips = []           # (mode, réseau, tarif forfaitaire ?, arrêts compacts, clé service)
        self.services = {}        # (flux, service) -> [masque jours, début, fin, ajouts, retraits]

    def area(self, key, name, lat, lon, sncf=False):
        i = self.by_key.get(key)
        if i is None:
            i = len(self.areas)
            self.by_key[key] = i
            self.areas.append({"key": key, "name": name, "lat": lat, "lon": lon,
                               "rail": False, "major": False, "sncf": sncf})
        return i

    def add_trip(self, mode, network, flat, stops, skey):
        stops = sorted(s for s in stops if s[2] is not None)   # arrêts sans horaire : ignorés
        if len(stops) < 2:
            return
        arr = array("i")
        for _, a, t_arr, t_dep, fl in stops:
            arr.extend((a, t_arr, t_dep, fl))
        self.trips.append((mode, network, flat, arr, skey))


def _rows(z, name):
    return csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig"))


def _calendar(z, fid, b):
    names = set(z.namelist())
    if "calendar.txt" in names:
        for c in _rows(z, "calendar.txt"):
            mask = sum(1 << i for i, d in enumerate(("monday", "tuesday", "wednesday", "thursday",
                                                     "friday", "saturday", "sunday")) if c.get(d) == "1")
            b.services[(fid, c["service_id"])] = [mask, int(c["start_date"]), int(c["end_date"]), set(), set()]
    if "calendar_dates.txt" in names:
        for c in _rows(z, "calendar_dates.txt"):
            s = b.services.setdefault((fid, c["service_id"]), [0, 0, 0, set(), set()])
            (s[3] if c["exception_type"] == "1" else s[4]).add(int(c["date"]))


def _times(st):
    a = st.get("arrival_time") or st.get("departure_time")
    d = st.get("departure_time") or st.get("arrival_time")
    if not a:
        return None, None
    return _mins(a), _mins(d)


def _flags(st):
    return (F_PICK if st.get("pickup_type") != "1" else 0) | (F_DROP if st.get("drop_off_type") != "1" else 0)


def _load_sncf(b):
    z = zipfile.ZipFile(_path("sncf"))
    point_area, point_mode = {}, {}
    stops = list(_rows(z, "stops.txt"))
    for s in stops:
        if s["location_type"] == "1":
            uic = s["stop_id"].rsplit("OCE", 1)[-1]
            b.area(uic, s["stop_name"], float(s["stop_lat"]), float(s["stop_lon"]), sncf=True)
    for s in stops:
        if s["location_type"] != "1":
            a = b.by_key.get(s["parent_station"].rsplit("OCE", 1)[-1])
            if a is None:
                continue
            kind = s["stop_id"].split(":OCE", 1)[-1].rsplit("-", 1)[0]
            point_area[s["stop_id"]], point_mode[s["stop_id"]] = a, kind
            if kind in ("Train TER", "TramTrain", "Train", "INTERCITES", "TGV INOUI", "OUIGO"):
                b.areas[a]["rail"] = True
            if kind in ("TGV INOUI", "INTERCITES", "OUIGO"):
                b.areas[a]["major"] = True
    _calendar(z, "sncf", b)
    trip_service = {t["trip_id"]: t["service_id"] for t in _rows(z, "trips.txt")}
    trips, bad = {}, set()
    for st in _rows(z, "stop_times.txt"):
        tid, p = st["trip_id"], st["stop_id"]
        a = point_area.get(p)
        if a is None:
            continue
        mode = SNCF_MODES.get(point_mode.get(p))
        if mode is None:
            bad.add(tid)              # un seul arrêt TGV/OUIGO… suffit à écarter la circulation
            continue
        t_arr, t_dep = _times(st)
        trips.setdefault(tid, [mode, []])[1].append((int(st["stop_sequence"]), a, t_arr, t_dep, _flags(st)))
    for tid, (mode, stops) in trips.items():
        if tid not in bad:
            b.add_trip(mode, None, False, stops, ("sncf", trip_service.get(tid)))


def _route_kind(rt):
    try:
        t = int(rt)
    except ValueError:
        return None
    if t == 2 or 100 <= t <= 117:
        return "train"
    if t == 3 or 200 <= t <= 209 or 700 <= t <= 716:
        return "car"
    return None                   # tram, métro, bateau… : hors sujet


def _load_regional(fid, brand, b):
    z = zipfile.ZipFile(_path(fid))
    parent = {}
    stops = list(_rows(z, "stops.txt"))
    for s in stops:
        lt = s.get("location_type") or "0"
        if lt == "1" or (lt == "0" and not s.get("parent_station")):
            try:
                lat, lon = float(s["stop_lat"]), float(s["stop_lon"])
            except (TypeError, ValueError):
                continue
            b.area(f"{fid}:{s['stop_id']}", s["stop_name"], lat, lon)
    for s in stops:
        if (s.get("location_type") or "0") == "0" and s.get("parent_station"):
            parent[s["stop_id"]] = s["parent_station"]
    routes = {r["route_id"]: _route_kind(r.get("route_type", "")) for r in _rows(z, "routes.txt")}
    trip_info = {}
    for t in _rows(z, "trips.txt"):
        kind = routes.get(t["route_id"])
        if kind:
            trip_info[t["trip_id"]] = (kind, t["service_id"])
    _calendar(z, fid, b)
    trips = {}
    for st in _rows(z, "stop_times.txt"):
        info = trip_info.get(st["trip_id"])
        if not info:
            continue
        sid = st["stop_id"]
        a = b.by_key.get(f"{fid}:{parent.get(sid, sid)}")
        if a is None:
            continue
        t_arr, t_dep = _times(st)
        trips.setdefault(st["trip_id"], []).append((int(st["stop_sequence"]), a, t_arr, t_dep, _flags(st)))
    for tid, stops in trips.items():
        kind, service = trip_info[tid]
        b.add_trip(brand, brand, kind == "car", stops, (fid, service))
        if kind == "train":
            for s in stops:
                b.areas[s[1]]["rail"] = True


def _footpaths(areas):
    """Correspondances à pied entre arrêts à moins de WALK_MAX_M (gare SNCF ↔ gare routière…)."""
    cell = 0.005
    grid = {}
    for i, a in enumerate(areas):
        grid.setdefault((int(a["lat"] / cell), int(a["lon"] / cell)), []).append(i)
    foot = {}
    for (gy, gx), members in grid.items():
        near = [j for dy in (-1, 0, 1) for dx in (-1, 0, 1) for j in grid.get((gy + dy, gx + dx), ())]
        for i in members:
            a = areas[i]
            for j in near:
                if j == i:
                    continue
                c = areas[j]
                m = haversine_km(a["lat"], a["lon"], c["lat"], c["lon"]) * 1000
                if m <= WALK_MAX_M:
                    foot.setdefault(i, []).append((j, 2 + math.ceil(m / 70)))
    return foot


def load():
    """Charge tous les réseaux téléchargés. Remplace les données d'un coup (les recherches en cours
    continuent sur l'ancienne version)."""
    global _data, _days
    b = _Builder()
    loaded = []
    if os.path.exists(_path("sncf")):
        _load_sncf(b)
        loaded.append("sncf")
    for fid, (_, brand) in feeds.REGIONAL.items():
        if os.path.exists(_path(fid)):
            try:
                _load_regional(fid, brand, b)
                loaded.append(fid)
            except Exception as e:
                print(f"    GTFS {fid} illisible : {e}", flush=True)
    sncf_dates = sorted(d for (f, _), s in b.services.items() if f == "sncf" for d in s[3])
    cell_of = array("i", (_cell(a["lat"], a["lon"]) for a in b.areas))
    new = {"areas": b.areas, "by_key": b.by_key, "trips": b.trips, "services": b.services, "cell_of": cell_of,
           "foot": _footpaths(b.areas), "feeds": loaded,
           "first": sncf_dates[0] if sncf_dates else None, "last": sncf_dates[-1] if sncf_dates else None,
           "names": [(_fold(a["name"]), i) for i, a in enumerate(b.areas)]}
    with _lock:
        _data, _days = new, {}
        _memo.clear()
    return len(b.trips), len(loaded)


def ready():
    return _data is not None and _data["first"] is not None


def covers(ymd):
    d = int(ymd.replace("-", ""))
    return ready() and _data["first"] <= d <= _data["last"]


def coverage():
    return {"start": str(_data["first"]), "end": str(_data["last"])} if ready() else None


def _key(stop_id):
    s = str(stop_id)
    return s[5:] if s.startswith("gtfs:") else s.rsplit(":", 1)[-1]


def knows(stop_id):
    return bool(_data) and _key(stop_id) in _data["by_key"]


# ------------------------------------------------------------------ connexions d'une journée
def _active(services, d):
    wd = 1 << Date(d // 10000, d // 100 % 100, d % 100).weekday()
    return {k for k, (mask, start, end, added, removed) in services.items()
            if d in added or (mask & wd and start <= d <= end and d not in removed)}


def _cell(lat, lon):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):     # coordonnées aberrantes dans un réseau
        return -1
    return int((lat + 90) / CELL) * 10000 + int((lon + 180) / CELL)


def _box_cells(a, b, margin_km=60):
    """Mailles couvrant le rectangle autour de deux arrêts, élargi de margin_km."""
    m = margin_km / 111
    lat0, lat1 = min(a["lat"], b["lat"]) - m, max(a["lat"], b["lat"]) + m
    mlon = m / max(0.3, math.cos(math.radians((lat0 + lat1) / 2)))
    lon0, lon1 = min(a["lon"], b["lon"]) - mlon, max(a["lon"], b["lon"]) + mlon
    y0, y1 = int((lat0 + 90) / CELL), int((lat1 + 90) / CELL)
    x0, x1 = int((lon0 + 180) / CELL), int((lon1 + 180) / CELL)
    return {y * 10000 + x for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)}


def _connections(ymd):
    """Tous les tronçons d'une journée (départ, arrivée, arrêt A, arrêt B, circulation, rang), triés
    par heure de départ ; les circulations de la veille qui passent minuit sont incluses."""
    d = int(ymd.replace("-", ""))
    with _lock:
        hit, data = _days.get(d), _data
        lock = _day_locks.setdefault(d, threading.Lock())
    if hit:
        return hit
    with lock:                    # plusieurs recherches simultanées : une seule construction
        with _lock:
            hit = _days.get(d)
        if hit:
            return hit
        return _build_day(d, ymd, data)


def _build_day(d, ymd, data):
    prev = _ymd(Date.fromisoformat(ymd) - timedelta(days=1))
    conns = []
    for day, shift in ((prev, -1440), (d, 0)):
        active = _active(data["services"], day)
        for ti, (_, _, _, st, skey) in enumerate(data["trips"]):
            if skey not in active:
                continue
            n = len(st) // 4
            if shift and st[4 * (n - 1) + 1] < 1440:
                continue
            for k in range(n - 1):
                dep = st[4 * k + 2] + shift
                if dep >= 0:
                    conns.append((dep, st[4 * (k + 1) + 1] + shift, st[4 * k], st[4 * (k + 1)], ti, k))
    conns.sort()
    # stockage compact : 6 tableaux d'entiers (≈ 24 octets par tronçon au lieu d'un tuple Python)
    cols = tuple(array("i", (c[j] for c in conns)) for j in range(6))
    del conns
    res = (cols, cols[0])
    with _lock:
        if len(_days) > 3:
            _days.clear()
            _day_locks.clear()
        _days[d] = res
    return res


def _csa(conns, deps, src, dst, t0, max_legs, stop_at=None, cells=None):
    """Arrivée au plus tôt src -> dst en au plus max_legs véhicules, correspondances à pied comprises.
    Renvoie les tronçons empruntés [(circulation, rang montée, rang descente)] ou None.
    cells : mailles géographiques utiles (les départs ailleurs sont ignorés d'emblée)."""
    INF = 10 ** 9
    end = min(t0 + 2 * HORIZON, stop_at if stop_at is not None else INF)
    trips, foot, cell_of = _data["trips"], _data["foot"], _data["cell_of"]
    best, legs_at, via, boarded = {src: t0}, {src: 0}, {}, {}
    bd = [INF]                    # meilleure arrivée connue à destination (évite une recherche par tronçon)

    def walk(x):
        for y, w in foot.get(x, ()):
            t = best[x] + w
            if t < best.get(y, INF):
                best[y], legs_at[y], via[y] = t, legs_at[x], ("walk", x)
                if y == dst:
                    bd[0] = t

    walk(src)
    C_dep, C_arr, C_a, C_b, C_ti, C_k = conns
    for i in range(bisect.bisect_left(deps, t0), len(deps)):
        dep = C_dep[i]
        a = C_a[i]
        if dep >= end or bd[0] <= dep:
            break
        if cells is not None and cell_of[a] not in cells:
            continue
        arr, b, ti, k = C_arr[i], C_b[i], C_ti[i], C_k[i]

        st = trips[ti][3]
        if ti not in boarded:
            if dep > t0 + HORIZON or not st[4 * k + 3] & F_PICK:
                continue
            t = best.get(a, INF)
            if t == INF or t + (0 if a == src else MIN_TRANSFER) > dep:
                continue
            n = legs_at[a] + 1
            if n > max_legs:
                continue
            boarded[ti] = (k, a, n)
        k0, a0, n = boarded[ti]
        if st[4 * (k + 1) + 3] & F_DROP and arr < best.get(b, INF):
            best[b], legs_at[b], via[b] = arr, n, ("ride", ti, k0, k + 1, a0)
            if b == dst:
                bd[0] = arr
            walk(b)

    if dst not in via:
        return None
    path, cur, guard = [], dst, 0
    while cur != src and cur in via and guard < 50:
        v = via[cur]
        guard += 1
        if v[0] == "walk":
            cur = v[1]
        else:
            path.append(v[1:4])
            cur = v[4]
    return path[::-1] if cur == src and path else None


def journey(from_id, to_id, ymd, hhmm, max_transfers=3):
    """Meilleur trajet from -> to partant après hhmm. Identifiants : « stop_area:SNCF:<UIC> » ou
    « gtfs:<réseau>:<arrêt> ». Même format que navitia.journey(). None si rien."""
    if not ready() or not covers(ymd):
        return None
    src, dst = _data["by_key"].get(_key(from_id)), _data["by_key"].get(_key(to_id))
    if src is None or dst is None or src == dst:
        return None
    key = (src, dst, ymd, hhmm, max_transfers)
    with _lock:
        if key in _memo:
            return _memo[key]
    h, m = hhmm.split(":")
    t0 = int(h) * 60 + int(m)
    conns, deps = _connections(ymd)
    cells = _box_cells(_data["areas"][src], _data["areas"][dst])
    # on ne change de véhicule que si ça fait vraiment arriver plus tôt (20 min par changement) ;
    # chaque passe ne cherche que ce qui peut battre la meilleure solution déjà trouvée
    best = None
    for legs in range(1, max_transfers + 2):
        path = _csa(conns, deps, src, dst, t0, legs, best[0] - 20 * (legs - 1) if best else None, cells)

        if path:
            st = _data["trips"][path[-1][0]][3]
            score = st[4 * path[-1][2] + 1] + 20 * (len(path) - 1)
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
        mode, network, flat, st, _ = trips[ti]
        a, b = areas[st[4 * k0]], areas[st[4 * k1]]
        mid_lat, mid_lon = (a["lat"] + b["lat"]) / 2, (a["lon"] + b["lon"]) / 2
        if network is None:           # SNCF : réseau TER de la région traversée
            code = regions.locate(mid_lat, mid_lon)
            network = regions.REGIONS.get(code, (None, "TER"))[1] if code and mode != "Intercités" else mode
        modes.append(mode)
        networks.append(network)
        sections.append({
            "mode": mode, "network": network, "flat_fare": flat, "from": a["name"], "to": b["name"],
            "dep": _hm(st[4 * k0 + 2]), "arr": _hm(st[4 * k1 + 1]),
            "dist_km": haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]),
            "lat": mid_lat, "lon": mid_lon,
            "coords": [[areas[st[4 * k]]["lat"], areas[st[4 * k]]["lon"]] for k in range(k0, k1 + 1)],
        })
    first = trips[path[0][0]][3][4 * path[0][1] + 2]
    last = trips[path[-1][0]][3][4 * path[-1][2] + 1]
    return {
        "duration_min": last - first, "transfers": len(path) - 1,
        "modes": modes, "networks": networks, "sections": sections,
        "distance_km": round(sum(s["dist_km"] for s in sections)),
        "departure": _hm(first), "arrival": _hm(last), "source": "gtfs",
    }


# ------------------------------------------------------------------ recherche de lieux
def _public_id(a):
    return "stop_area:SNCF:" + a["key"] if a["sncf"] else "gtfs:" + a["key"]


def places(q, limit=8):
    """Gares et arrêts dont le nom contient q (gares SNCF et ferroviaires d'abord)."""
    if not _data:
        return []
    fq = _fold(q)
    if len(fq) < 2:
        return []
    areas = _data["areas"]
    hits = [i for name, i in _data["names"] if fq in name]
    hits.sort(key=lambda i: (not areas[i]["rail"], not _fold(areas[i]["name"]).startswith(fq),
                             not areas[i]["major"], not areas[i]["sncf"], len(areas[i]["name"])))
    out, seen = [], set()
    for i in hits:
        a = areas[i]
        k = _fold(a["name"])
        if k in seen:                 # un même nom d'arrêt dans plusieurs réseaux : une seule fois
            continue
        seen.add(k)
        out.append({"id": _public_id(a), "name": a["name"], "lat": a["lat"], "lon": a["lon"]})
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ mise à jour
def refresh_loop():
    """Au démarrage puis toutes les 6 h : SNCF rafraîchi chaque jour, réseaux régionaux chaque semaine."""
    while True:
        changed = not _data
        for fid, (url, _), max_age in [("sncf", feeds.SNCF, 20 * 3600)] + \
                [(k, v, 7 * 86400) for k, v in feeds.REGIONAL.items()]:
            try:
                changed |= download(fid, url, max_age)
            except Exception as e:
                print(f"    GTFS {fid} : téléchargement impossible ({e})", flush=True)
            if fid == "sncf" and not ready() and os.path.exists(_path("sncf")):
                load()                    # premier démarrage : les TER tout de suite, les cars ensuite
        if changed:
            try:
                t = time.time()
                n, f = load()
                print(f"    Horaires locaux chargés : {n} circulations, {f} réseaux "
                      f"({_data['first']} → {_data['last']}, {time.time() - t:.0f} s).", flush=True)
            except Exception as e:
                print("    Horaires locaux indisponibles :", e, flush=True)
        time.sleep(6 * 3600)

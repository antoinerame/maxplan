# -*- coding: utf-8 -*-
"""Horaires en local (GTFS open data) : calcul des trajets TER et cars régionaux sans l'API SNCF.

Sources (voir reseaux.py) : l'export GTFS de la SNCF (TER, cars TER, Intercités, ~6 mois) et une
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
import re
import threading
import time
import unicodedata
import urllib.request
import zipfile
import zlib
from array import array
from datetime import date as Date, timedelta

from maxplan import config, regions
from maxplan.base import haversine_km
from maxplan.ter import reseaux

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
_by_cell = {}             # date AAAAMMJJ -> (connexions, {maille: indices des tronçons})
_memo = {}                # trajets déjà calculés
_day_locks = {}           # une seule construction à la fois par journée
DAYS_CACHED = 3           # journées gardées en mémoire (~15 Mo chacune ; relues du disque en ~30 ms)
PRECOMPUTE_DAYS = 34      # tables préparées la nuit (sur disque, compressées)
CELL = 0.5                # maillage géographique (degrés) pour ne parcourir que la zone utile


def _fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = " " + s.replace("-", " ").replace("'", " ") + " "
    return " ".join(s.replace(" sainte ", " ste ").replace(" saint ", " st ").split())


fold = _fold                # nom replié, pour comparer avec les noms saisis


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
WINDOW_DAYS = 40          # on ne garde que les circulations des 40 prochains jours (les places Max : 30)


class _Builder:
    def __init__(self):
        self.areas, self.by_key = [], {}
        self.trips = []           # (mode, réseau, tarif forfaitaire ?, arrêts compacts, clé service)
        self.trains = {}          # n° de TGV / Intercités -> [(clé service, arrêts compacts (gare, arr., dép.))]
        self.services = {}        # (flux, service) -> [masque jours, début, fin, ajouts, retraits]
        today = Date.today()
        self.w0, self.w1 = _ymd(today - timedelta(days=2)), _ymd(today + timedelta(days=WINDOW_DAYS))
        self._inwin = {}

    def in_window(self, skey):
        """Le service circule-t-il au moins un jour dans la fenêtre utile ? (sinon : mémoire inutile)"""
        r = self._inwin.get(skey)
        if r is None:
            s = self.services.get(skey)
            r = bool(s) and (any(self.w0 <= d <= self.w1 for d in s[3])
                             or (s[0] and s[1] <= self.w1 and s[2] >= self.w0))
            self._inwin[skey] = r
        return r

    def area(self, key, name, lat, lon, sncf=False):
        i = self.by_key.get(key)
        if i is None:
            i = len(self.areas)
            self.by_key[key] = i
            self.areas.append({"key": key, "name": name, "lat": lat, "lon": lon,
                               "rail": False, "major": False, "sncf": sncf})
        return i

    def add_trip(self, mode, network, flat, stops, skey):
        if not self.in_window(skey):
            return
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
    trip_info = {t["trip_id"]: (t["service_id"], t.get("trip_headsign", "")) for t in _rows(z, "trips.txt")}
    trip_service = {k: v[0] for k, v in trip_info.items()}
    trips, bad, long_trains = {}, set(), {}
    for st in _rows(z, "stop_times.txt"):
        tid, p = st["trip_id"], st["stop_id"]
        a = point_area.get(p)
        if a is None:
            continue
        if point_mode.get(p) in ("TGV INOUI", "INTERCITES"):   # trains Max : leurs vraies gares
            t_arr, t_dep = _times(st)
            if t_arr is not None:
                long_trains.setdefault(tid, []).append((int(st["stop_sequence"]), a, t_arr, t_dep))
        mode = SNCF_MODES.get(point_mode.get(p))
        if mode is None:
            bad.add(tid)              # un seul arrêt TGV/OUIGO… suffit à écarter la circulation
            continue
        t_arr, t_dep = _times(st)
        trips.setdefault(tid, [mode, []])[1].append((int(st["stop_sequence"]), a, t_arr, t_dep, _flags(st)))
    for tid, (mode, stops) in trips.items():
        if tid not in bad:
            b.add_trip(mode, None, False, stops, ("sncf", trip_service.get(tid)))
    for tid, stops in long_trains.items():
        service, number = trip_info.get(tid, (None, ""))
        skey = ("sncf", service)
        if number and b.in_window(skey):
            arr = array("i")
            for _, a, t_arr, t_dep in sorted(stops):
                arr.extend((a, t_arr, t_dep))
            b.trains.setdefault(number, []).append((skey, arr))


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


def _stamp(loaded):
    """Version des horaires : dépend des fichiers chargés et du jour (fenêtre de 40 jours), pas de
    l'heure. Un simple redémarrage réutilise donc les tables préparées la nuit."""
    sig = "|".join(f"{f}:{int(os.path.getmtime(_path(f)))}:{os.path.getsize(_path(f))}" for f in sorted(loaded))
    return zlib.crc32((sig + str(_ymd(Date.today()))).encode())


def load():
    """Charge tous les réseaux téléchargés. Remplace les données d'un coup (les recherches en cours
    continuent sur l'ancienne version)."""
    global _data, _days
    b = _Builder()
    loaded = []
    if os.path.exists(_path("sncf")):
        _load_sncf(b)
        loaded.append("sncf")
    for fid, (_, brand) in reseaux.REGIONAL.items():
        if os.path.exists(_path(fid)):
            try:
                _load_regional(fid, brand, b)
                loaded.append(fid)
            except Exception as e:
                print(f"    GTFS {fid} illisible : {e}", flush=True)
    sncf_dates = sorted(d for (f, _), s in b.services.items() if f == "sncf" for d in s[3] if d <= b.w1)
    cell_of = array("i", (_cell(a["lat"], a["lon"]) for a in b.areas))
    new = {"areas": b.areas, "by_key": b.by_key, "trips": b.trips, "trains": b.trains,
           "services": b.services, "cell_of": cell_of,
           "foot": _footpaths(b.areas), "feeds": loaded,
           "first": sncf_dates[0] if sncf_dates else None, "last": sncf_dates[-1] if sncf_dates else None,
           "names": [(_fold(a["name"]), i) for i, a in enumerate(b.areas)], "built": _ymd(Date.today()),
           "stamp": _stamp(loaded)}
    with _lock:
        _data, _days = new, {}
        _by_cell.clear()
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


_ACTIVE = {}              # jour -> services qui circulent (pour retrouver les vraies gares des TGV)


def train_stop(train, ymd, minute, when="dep"):
    """Vraie gare où le train n° `train` part (when="dep") ou arrive (when="arr") à `minute` (minutes
    depuis minuit du jour ymd, peut dépasser 1440), d'après les horaires SNCF. L'open data Max ne dit
    que « LYON (intramuros) » : ici on sait si c'est Part-Dieu ou Perrache. {name, lat, lon} ou None."""
    data = _data
    runs = data.get("trains", {}).get(str(train)) if data else None
    if not runs:
        return None
    day = Date.fromisoformat(ymd)
    for back in (0, 1):                       # parti la veille (horaires après minuit : > 1440)
        d = _ymd(day - timedelta(days=back))
        key = (id(data), d)
        active = _ACTIVE.get(key)
        if active is None:
            if len(_ACTIVE) > 64:
                _ACTIVE.clear()
            active = _ACTIVE[key] = _active(data["services"], d)
        t = minute + 1440 * back
        for skey, arr in runs:
            if skey not in active:
                continue
            for k in range(0, len(arr), 3):
                if arr[k + (2 if when == "dep" else 1)] == t:
                    a = data["areas"][arr[k]]
                    return {"name": a["name"], "lat": a["lat"], "lon": a["lon"]}
    return None


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
        res = _read_day(d, data)  # préparée la nuit ?
        if res is None:
            res = _build_day(d, ymd, data)
            _write_day(d, data, res)
        return _remember(d, res)


def _day_file(d, data):
    return os.path.join(DIR, "days", f"{data['stamp']}-{d}.bin")


def _write_day(d, data, res):
    """Enregistre la table d'un jour (6 tableaux d'entiers, compressés) pour ne plus la recalculer."""
    try:
        os.makedirs(os.path.join(DIR, "days"), exist_ok=True)
        raw = b"".join(col.tobytes() for col in res[0])
        tmp = _day_file(d, data) + ".tmp"
        with open(tmp, "wb") as f:
            f.write(len(res[0][0]).to_bytes(4, "little") + zlib.compress(raw, 1))
        os.replace(tmp, _day_file(d, data))
    except OSError:
        pass


def _read_day(d, data):
    try:
        with open(_day_file(d, data), "rb") as f:
            n = int.from_bytes(f.read(4), "little")
            raw = zlib.decompress(f.read())
    except (OSError, zlib.error):
        return None
    cols = []
    for j in range(6):
        col = array("i")
        col.frombytes(raw[j * 4 * n:(j + 1) * 4 * n])
        cols.append(col)
    return tuple(cols), cols[0]


def _remember(d, res):
    with _lock:
        _days[d] = res
        while len(_days) > DAYS_CACHED:           # garde les journées les plus récemment utilisées
            old = next(iter(_days))
            _days.pop(old)
            _day_locks.pop(old, None)
            _by_cell.pop(old, None)
    return res


def _cell_index(ymd, conns):
    """Tronçons d'une journée rangés par maille géographique de départ (indices croissants) : une
    recherche ne lit que les mailles entre le départ et l'arrivée au lieu de toute la France."""
    d = int(ymd.replace("-", ""))
    hit = _by_cell.get(d)
    if hit is not None and hit[0] is conns:
        return hit[1]
    cell_of, m = _data["cell_of"], {}
    for i, a in enumerate(conns[2]):
        c = cell_of[a]
        x = m.get(c)
        if x is None:
            x = m[c] = array("i")
        x.append(i)
    with _lock:
        if d in _days:                            # journée encore en cache : on garde son index
            _by_cell[d] = (conns, m)
    return m


def precompute():
    """La nuit, après le chargement : prépare sur disque les tables des prochains jours, et supprime
    celles d'anciennes versions des horaires. En journée, une recherche n'a plus qu'à les relire."""
    data = _data
    if not data:
        return 0
    folder = os.path.join(DIR, "days")
    os.makedirs(folder, exist_ok=True)
    for name in os.listdir(folder):
        if not name.startswith(f"{data['stamp']}-"):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass
    n = 0
    for k in range(-1, PRECOMPUTE_DAYS):
        day = Date.today() + timedelta(days=k)
        d = _ymd(day)
        if _data is not data:                     # rechargé entre-temps : on arrête
            break
        if not os.path.exists(_day_file(d, data)):
            _write_day(d, data, _build_day(d, day.isoformat(), data))
            n += 1
            time.sleep(0.2)                       # laisse respirer le serveur
    return n


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
    return cols, cols[0]


def _csa(conns, idx, src, dst, t0, max_legs, stop_at=None):
    """Arrivée au plus tôt src -> dst en au plus max_legs véhicules, correspondances à pied comprises.
    Renvoie les tronçons empruntés [(circulation, rang montée, rang descente)] ou None.
    idx : indices (croissants, donc par heure de départ) des tronçons utiles : ceux des mailles
    géographiques entre le départ et l'arrivée, à partir de l'heure de départ."""
    INF = 10 ** 9
    end = min(t0 + 2 * HORIZON, stop_at if stop_at is not None else INF)
    trips, foot = _data["trips"], _data["foot"]
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
    for i in idx:
        dep = C_dep[i]
        if dep >= end or bd[0] <= dep:
            break
        a, arr, b, ti, k = C_a[i], C_arr[i], C_b[i], C_ti[i], C_k[i]
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
    lo, hi = bisect.bisect_left(deps, t0), bisect.bisect_left(deps, t0 + 2 * HORIZON)
    by_cell, parts = _cell_index(ymd, conns), []
    for c in cells:
        x = by_cell.get(c)
        if x:
            parts.append(x[bisect.bisect_left(x, lo):bisect.bisect_left(x, hi)])
    idx = sorted(i for x in parts for i in x)       # calculé une fois pour les 4 passes
    # on ne change de véhicule que si ça fait vraiment arriver plus tôt (20 min par changement) ;
    # chaque passe ne cherche que ce qui peut battre la meilleure solution déjà trouvée
    best = None
    for legs in range(1, max_transfers + 2):
        path = _csa(conns, idx, src, dst, t0, legs, best[0] - 20 * (legs - 1) if best else None)

        if path:
            st = _data["trips"][path[-1][0]][3]
            score = st[4 * path[-1][2] + 1] + 20 * (len(path) - 1)
            if best is None or score < best[0]:
                best = (score, path)
    res = _format(best[1]) if best else None
    with _lock:
        if len(_memo) > 6000:            # borné : chaque trajet garde ses coordonnées
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
    word = re.compile(r"(^| )" + re.escape(fq) + r"( |$)")   # « Albi » : Albi Ville avant Albias
    hits.sort(key=lambda i: (_fold(areas[i]["name"]) != fq,          # « Aix-en-Provence » avant Aix TGV
                             not areas[i]["rail"], not word.search(_fold(areas[i]["name"])),
                             not _fold(areas[i]["name"]).startswith(fq),
                             not areas[i]["major"], not areas[i]["sncf"], len(areas[i]["name"])))
    out, seen = [], set()
    for i in hits:
        a = areas[i]
        k = _fold(a["name"])
        if k in seen:                 # un même nom d'arrêt dans plusieurs réseaux : une seule fois
            continue
        seen.add(k)
        out.append({"id": _public_id(a), "name": a["name"], "lat": a["lat"], "lon": a["lon"], "rail": a["rail"]})
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ mise à jour
def refresh_loop():
    """Mise à jour des horaires LA NUIT (1 h – 5 h UTC) pour ne pas charger le serveur en journée :
    SNCF chaque nuit, réseaux régionaux chaque semaine. Au premier démarrage : tout de suite."""
    while True:
        night = 1 <= time.gmtime().tm_hour < 5
        if _data and not night:
            time.sleep(1800)
            continue
        changed = not _data
        for fid, (url, _), max_age in [("sncf", reseaux.SNCF, 20 * 3600)] + \
                [(k, v, 7 * 86400) for k, v in reseaux.REGIONAL.items()]:
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
        elif _data and _data.get("built") != _ymd(Date.today()):
            load()                    # pas de nouveau fichier : on fait au moins glisser la fenêtre de 40 jours
        if _data:
            t = time.time()
            n = precompute()
            if n:
                print(f"    {n} journées préparées ({time.time() - t:.0f} s).", flush=True)

        time.sleep(1800 if not _data else 4 * 3600)


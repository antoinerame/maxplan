# -*- coding: utf-8 -*-
"""TGV Max Planner — serveur HTTP (stdlib, zéro dépendance).

Lancer :  python server.py    puis ouvrir http://127.0.0.1:8765
API :
  GET /api/meta                          fenêtre de données, régions, version
  GET /api/search?from&to&from_date&to_date&maxconn&ter&ter_transfers&start&end&nights&sub&ter_disc
  GET /api/explore?from&date&maxconn&sub
  GET /api/stations?q&kind=origin|dest
  GET /api/nearest?lat&lon
  GET /healthz
"""

import gzip
import json
import os
import re
import sys
import threading
import time
import traceback
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date as Date, timedelta
from email.utils import formatdate, parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:  # console Windows : éviter UnicodeEncodeError sur les logs
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import config
import pricing
import regions
import tgvmax_core as core
from navitia import navitia

VERSION = "2.0"
WEB_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "web"))
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
IO_POOL = ThreadPoolExecutor(max_workers=16)   # géocodage + calculs TER
DAY_POOL = ThreadPoolExecutor(max_workers=4)   # plusieurs jours d'une même recherche


class BadRequest(Exception):
    pass


# ======================================================================= données
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
        edges = core.fetch_oui_edges(date)
        now = time.time()
        _EDGES[date] = (now, edges)
        for d, (t, _) in list(_EDGES.items()):
            if now - t > 2 * config.EDGES_TTL:
                _EDGES.pop(d, None)
        return edges


def geocode_many(labels):
    labels = [l for l in dict.fromkeys(labels) if l]
    return dict(zip(labels, IO_POOL.map(navitia.geocode, labels))) if labels else {}


def weekday_idx(d):
    return Date.fromisoformat(d).weekday()


def shift(d, days):
    return (Date.fromisoformat(d) + timedelta(days=days)).isoformat()


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
def max_leg(edge, date, geo):
    o, d = edge["o"], edge["d"]
    og, dg = geo.get(o), geo.get(d)
    dep = core.min_to_hhmm(edge["dep"])
    return {
        "free": True, "mode": "TGV Max", "train": edge["train"], "axe": edge.get("axe", ""),
        "entity": edge.get("entity", ""),
        "from": o, "to": d, "from_name": display_name(o, og), "to_name": display_name(d, dg),
        "dep": dep, "arr": core.min_to_hhmm(edge["arr"]),
        "dep_day": edge["dep"] // 1440, "arr_day": edge["arr"] // 1440,
        "from_lat": og and og["lat"], "from_lon": og and og["lon"],
        "to_lat": dg and dg["lat"], "to_lon": dg and dg["lon"],
        "book_url": booking_url(o, og, d, dg, shift(date, edge["dep"] // 1440), dep),
    }


def path_nocturnal(path):
    """Un trajet touche-t-il la nuit (train ou attente de correspondance ~23 h–6 h) ?"""
    if any(core.night_overlap(e["dep"], e["arr"]) for e in path):
        return True
    return any(core.night_overlap(a["arr"], b["dep"]) for a, b in zip(path, path[1:]))


def itinerary_from_path(path, date, geo):
    legs = [max_leg(e, date, geo) for e in path]
    return {
        "type": "max", "paid": False, "cost_eur": 0, "nresa": len(legs),
        "departure": legs[0]["dep"], "arrival": legs[-1]["arr"],
        "arrival_day": path[-1]["arr"] // 1440,
        "duration_min": path[-1]["arr"] - path[0]["dep"],
        "nocturnal": path_nocturnal(path), "legs": legs,
    }


def senior_weekend(prefs, date):
    return prefs["sub"] == "senior" and weekday_idx(date) >= 5


SENIOR_NOTICE = "Max Senior : pas de place à 0 € le samedi ni le dimanche."


def search_one_day(src, dst, date, opts):
    prefs = opts["prefs"]
    if senior_weekend(prefs, date):
        return {"itineraries": [], "notice": SENIOR_NOTICE}
    edges = edges_for(date)
    stations = {e["o"] for e in edges} | {e["d"] for e in edges}
    origins = core.resolve_city(src, stations)
    targets = core.resolve_city(dst, stations)
    win = dict(min_dep=opts["min_dep"], max_dep=opts["max_dep"])

    # 1) trajets 100 % Max
    max_paths = core.search(edges, origins, targets, max_conn=opts["maxconn"], max_results=12, **win)
    labels = set(origins)
    for p in max_paths:
        for e in p:
            labels.update((e["o"], e["d"]))

    # 2) compléments TER : gares atteignables en Max les plus proches de la destination
    ter_itins = []
    dest_geo = navitia.geocode(dst) if opts["ter"] else None
    if dest_geo:
        best = core.reachable(edges, origins, max_conn=opts["maxconn"], **win)
        tset = set(targets)
        frontier = {s: pp for s, pp in best.items() if s not in tset}
        fgeo = geocode_many(list(frontier))
        ranked = []
        for s, (_, path) in frontier.items():
            g = fgeo.get(s)
            if g:
                km = core.haversine_km(g["lat"], g["lon"], dest_geo["lat"], dest_geo["lon"])
                if km <= config.TER_MAX_DISTANCE_KM:
                    ranked.append((km, s, path, g))
        ranked.sort(key=lambda x: x[0])

        def tail(item):
            _, s, path, g = item
            ready = path[-1]["arr"] + core.min_connection(s)       # minutes depuis le jour J (peut dépasser 1440)
            jdate = shift(date, ready // 1440)                      # après un train de nuit : le lendemain !
            if not navitia.date_in_range(jdate):
                return item, None, None, None
            jr = navitia.journey(g["id"], dest_geo["id"], jdate, core.min_to_hhmm(ready),
                                 max_transfers=opts["ter_transfers"])
            return item, jr, ready, jdate

        for (_, s, path, g), jr, ready, jdate in IO_POOL.map(tail, ranked[:config.TER_CANDIDATES]):
            if jr and jr["duration_min"] <= config.TER_MAX_TAIL_MIN:
                ter_itins.append((path, s, g, jr, ready))
                labels.update(e for leg in path for e in (leg["o"], leg["d"]))

    geo = geocode_many(list(labels))
    out = [dict(itinerary_from_path(p, date, geo)) for p in max_paths]

    for path, s, g, jr, ready in ter_itins:
        legs = [max_leg(e, date, geo) for e in path]
        last_arr = path[-1]["arr"]
        tdep = core.hhmm_to_min(jr["departure"]) if jr.get("departure") else ready % 1440
        ter_dep = (ready // 1440) * 1440 + tdep
        if ter_dep < ready - 1:
            ter_dep += 1440
        ter_arr = ter_dep + jr["duration_min"]
        price = pricing.estimate(jr["sections"], prefs)
        dest_name = nice_place(dest_geo["name"])
        legs.append({
            "free": False, "mode": " + ".join(dict.fromkeys(nice_mode(m) for m in jr["modes"])) or "TER",
            "networks": list(dict.fromkeys(jr["networks"])), "train": "",
            "from": s, "to": dst, "from_name": display_name(s, g), "to_name": dest_name,
            "dep": jr["departure"], "arr": jr["arrival"],
            "dep_day": ter_dep // 1440, "arr_day": ter_arr // 1440,
            "duration_min": jr["duration_min"], "transfers": jr["transfers"], "price": price,
            "steps": [{"mode": nice_mode(x["mode"]), "from": nice_place(x["from"]), "to": nice_place(x["to"]),
                       "dep": x["dep"], "arr": x["arr"]} for x in jr["sections"]],
            "path": [pt for x in jr["sections"] for pt in x["coords"]],
            "from_lat": g["lat"], "from_lon": g["lon"],
            "to_lat": dest_geo["lat"], "to_lon": dest_geo["lon"],
            "book_url": booking_url(s, g, dest_geo["name"], dest_geo, shift(date, ter_dep // 1440),
                                    jr["departure"] or core.min_to_hhmm(ready)),
        })
        out.append({
            "type": "max+ter", "paid": True, "cost_eur": price["price"], "nresa": len(path),
            "departure": legs[0]["dep"], "arrival": jr["arrival"], "arrival_day": ter_arr // 1440,
            "duration_min": ter_arr - path[0]["dep"],
            "nocturnal": (path_nocturnal(path) or core.night_overlap(last_arr, ter_dep)
                          or core.night_overlap(ter_dep, ter_arr)),
            "legs": legs,
        })

    total = len(out)
    if not opts["nights"]:
        out = [it for it in out if not it["nocturnal"]]
    out.sort(key=lambda it: (it["paid"], it["departure"]))
    res = {"itineraries": out}
    if total and not out:
        res["notice"] = f"{total} trajet(s) de nuit masqué(s) — active « Trajets de nuit » pour les voir."
    elif total > len(out):
        res["hidden_night"] = total - len(out)
    return res


# ======================================================================= endpoints
def _p(qs, name, default=""):
    return (qs.get(name, [default])[0] or default).strip()


def _int(qs, name, default, lo, hi):
    try:
        return max(lo, min(hi, int(_p(qs, name, str(default)))))
    except ValueError:
        return default


def _flag(qs, name, default):
    v = _p(qs, name, "1" if default else "0").lower()
    return v not in ("0", "false", "no", "")


def do_search(qs):
    src, dst = _p(qs, "from"), _p(qs, "to")
    if not src or not dst:
        raise BadRequest("Indique une gare de départ et une gare d'arrivée.")
    fd = _p(qs, "from_date")
    td = _p(qs, "to_date") or fd
    if not DATE_RE.match(fd) or not DATE_RE.match(td):
        raise BadRequest("Date invalide (format attendu AAAA-MM-JJ).")
    if td < fd:
        fd, td = td, fd
    dates = list(core.daterange(fd, td))
    if len(dates) > config.MAX_RANGE_DAYS:
        raise BadRequest(f"Période trop longue : {config.MAX_RANGE_DAYS} jours maximum.")
    start, end = _p(qs, "start"), _p(qs, "end")
    start_min = core.hhmm_to_min(start) if TIME_RE.match(start) else None
    end_min = core.hhmm_to_min(end) if TIME_RE.match(end) else None
    prefs = pricing.prefs_from_qs(qs)
    base = {
        "prefs": prefs, "maxconn": _int(qs, "maxconn", 1, 0, 2),
        "ter": _flag(qs, "ter", True), "ter_transfers": _int(qs, "ter_transfers", 1, 0, 3),
        "nights": _flag(qs, "nights", False),
    }

    def one(day):
        opts = dict(base,
                    min_dep=start_min if (day == fd and start_min is not None) else 0,
                    max_dep=end_min if (day == td and end_min is not None) else 1440)
        try:
            r = search_one_day(src, dst, day, opts)
        except Exception:
            traceback.print_exc()
            r = {"itineraries": [], "error": "Données indisponibles pour ce jour, réessaie plus tard."}
        return dict(r, date=day, weekday=core.weekday(day))

    days = list(DAY_POOL.map(one, dates)) if len(dates) > 1 else [one(dates[0])]
    dest_geo = navitia.geocode(dst)
    return {
        "mode": "search", "from": src, "to": dst, "prefs": prefs, "days": days,
        "to_coord": dest_geo and {"lat": dest_geo["lat"], "lon": dest_geo["lon"],
                                  "name": nice_place(dest_geo["name"])},
    }


def do_explore(qs):
    src, date = _p(qs, "from", "paris"), _p(qs, "date")
    if not DATE_RE.match(date):
        raise BadRequest("Date invalide (format attendu AAAA-MM-JJ).")
    prefs = pricing.prefs_from_qs(qs)
    edges = [] if senior_weekend(prefs, date) else edges_for(date)
    stations = {e["o"] for e in edges} | {e["d"] for e in edges}
    origins = core.resolve_city(src, stations)
    best = core.reachable(edges, origins, max_conn=_int(qs, "maxconn", 1, 0, 2))
    geo = geocode_many(list(origins) + list(best))
    og = next((geo[o] for o in origins if geo.get(o)), None)
    dests = []
    for label, (nlegs, path) in best.items():
        g = geo.get(label)
        if not g:
            continue
        dests.append({
            "label": label, "name": display_name(label, g), "lat": g["lat"], "lon": g["lon"],
            "nconn": nlegs - 1, "dep": core.min_to_hhmm(path[0]["dep"]),
            "arr": core.min_to_hhmm(path[-1]["arr"]), "arr_day": path[-1]["arr"] // 1440,
            "via": [display_name(e["d"], geo.get(e["d"])) for e in path[:-1]],
        })
    dests.sort(key=lambda x: (x["nconn"], x["name"]))
    res = {
        "mode": "explore", "date": date, "weekday": core.weekday(date),
        "origin": {"label": origins[0] if origins else src,
                   "name": display_name(origins[0], og) if origins else src,
                   "lat": og and og["lat"], "lon": og and og["lon"]},
        "destinations": dests,
    }
    if senior_weekend(prefs, date):
        res["notice"] = SENIOR_NOTICE
    return res


def do_stations(qs):
    q, kind = _p(qs, "q"), _p(qs, "kind", "origin")
    out, seen = [], set()
    for label in core.search_stations(q, limit=8):
        key = core.normalize(label)
        if key not in seen:
            seen.add(key)
            out.append({"label": label, "name": display_name(label, navitia._cache.get(label) or None),
                        "max": True})
    if kind == "dest":  # destinations : aussi des lieux hors réseau Max (ex. Manosque)
        for p in navitia.places(q, limit=6):
            key = core.normalize(nice_place(p["name"]))
            if key not in seen:
                seen.add(key)
                out.append({"label": p["name"], "name": nice_place(p["name"]), "max": False})
    return out[:10]


def do_nearest(qs):
    try:
        lat, lon = float(_p(qs, "lat")), float(_p(qs, "lon"))
    except ValueError:
        raise BadRequest("Position invalide.")
    ranked = []
    for s in core.all_stations():
        g = navitia._cache.get(s)
        if g:
            ranked.append((core.haversine_km(lat, lon, g["lat"], g["lon"]), s, g))
    ranked.sort(key=lambda x: x[0])
    return [{"label": s, "name": display_name(s, g), "km": round(d)} for d, s, g in ranked[:3]]


def do_meta(qs):
    dates = core.dataset_dates()
    return {
        "version": VERSION,
        "dates": {"start": dates[0] if dates else None, "end": dates[-1] if dates else None},
        "ter_coverage": navitia.coverage(),
        "regions": regions.as_list(),
    }


ROUTES = {
    "/api/search": ("search", do_search),
    "/api/explore": ("explore", do_explore),
    "/api/stations": ("stations", do_stations),
    "/api/nearest": ("nearest", do_nearest),
    "/api/meta": (None, do_meta),
}


# ======================================================================= limiteur de débit
class RateLimiter:
    def __init__(self):
        self.hits = defaultdict(list)
        self.lock = threading.Lock()

    def allow(self, key, limit, window):
        now = time.time()
        with self.lock:
            q = [t for t in self.hits[key] if now - t < window]
            ok = len(q) < limit
            if ok:
                q.append(now)
            self.hits[key] = q
            if len(self.hits) > 20000:
                self.hits.clear()
            return ok


LIMITER = RateLimiter()

# ======================================================================= HTTP
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml",
    ".png": "image/png", ".woff2": "font/woff2", ".ico": "image/x-icon",
}
COMPRESSIBLE = {".html", ".js", ".css", ".json", ".webmanifest", ".svg"}
_GZ = {}
CSP = ("default-src 'self'; img-src 'self' data: https://server.arcgisonline.com; "
       "style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; connect-src 'self'; "
       "manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


class Handler(BaseHTTPRequestHandler):
    server_version = "TGVMaxPlanner/" + VERSION
    sys_version = ""

    def log_message(self, *a):
        pass

    def client_ip(self):
        return (self.headers.get("CF-Connecting-IP")
                or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or self.client_address[0])

    def _gzip_ok(self):
        return "gzip" in self.headers.get("Accept-Encoding", "")

    def _common(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
        self.send_header("Content-Security-Policy", CSP)

    def _send(self, status, body, ctype, extra=None, compressible=True):
        enc = None
        if compressible and len(body) > 1024 and self._gzip_ok():
            body, enc = gzip.compress(body, 6), "gzip"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if enc:
            self.send_header("Content-Encoding", enc)
            self.send_header("Vary", "Accept-Encoding")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self._common()
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status=200, extra=None):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8",
                   dict({"Cache-Control": "no-store"}, **(extra or {})))

    def _static(self, path):
        rel = "index.html" if path in ("/", "/index.html") else urllib.parse.unquote(path.lstrip("/"))
        fp = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not fp.startswith(WEB_DIR + os.sep) or not os.path.isfile(fp):
            return self._send(404, "Page introuvable".encode("utf-8"), "text/plain; charset=utf-8")
        ext = os.path.splitext(fp)[1].lower()
        mtime = int(os.path.getmtime(fp))
        cache = ("public, max-age=604800" if rel.startswith(("vendor/", "fonts/", "geo/"))
                 else "no-cache")
        headers = {"Last-Modified": formatdate(mtime, usegmt=True), "Cache-Control": cache}
        ims = self.headers.get("If-Modified-Since")
        if ims:
            try:
                if int(parsedate_to_datetime(ims).timestamp()) >= mtime:
                    self.send_response(304)
                    for k, v in headers.items():
                        self.send_header(k, v)
                    self._common()
                    self.end_headers()
                    return
            except Exception:
                pass
        with open(fp, "rb") as f:
            body = f.read()
        ctype = STATIC_TYPES.get(ext, "application/octet-stream")
        if ext in COMPRESSIBLE and len(body) > 1024 and self._gzip_ok():
            hit = _GZ.get(fp)
            if not hit or hit[0] != mtime:
                hit = (mtime, gzip.compress(body, 6))
                _GZ[fp] = hit
            headers.update({"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
            return self._send(200, hit[1], ctype, headers, compressible=False)
        return self._send(200, body, ctype, headers, compressible=False)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == "/healthz":
            return self._json({"ok": True, "service": "tgvmax", "version": VERSION})
        route = ROUTES.get(u.path)
        if not route:
            return self._static(u.path)
        group, fn = route
        if group:
            limit, window = config.RATE_LIMITS[group]
            if not LIMITER.allow((self.client_ip(), group), limit, window):
                return self._json({"error": "Beaucoup de recherches d'un coup — réessaie dans une minute."},
                                  429, {"Retry-After": "30"})
        try:
            return self._json(fn(qs))
        except BadRequest as e:
            return self._json({"error": str(e)}, 400)
        except Exception:
            traceback.print_exc()
            return self._json({"error": "Erreur interne, réessaie dans un instant."}, 500)


def warmup():
    """Au démarrage : récupère la liste des gares et les géocode (sert à « gare la plus proche »)."""
    try:
        stations = core.all_stations()
        geocode_many(stations)
        core.dataset_dates()
        print(f"    Préchauffage terminé : {len(stations)} gares Max géocodées.", flush=True)
    except Exception as e:
        print("    Préchauffage incomplet :", e, flush=True)


def main():
    srv = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    srv.daemon_threads = True
    threading.Thread(target=warmup, daemon=True).start()
    print(f"\n🚄  TGV Max Planner {VERSION}  →  http://{config.HOST}:{config.PORT}", flush=True)
    print("    Ctrl+C pour arrêter.\n", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
        srv.shutdown()


if __name__ == "__main__":
    main()

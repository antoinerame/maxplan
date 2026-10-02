"""Serveur HTTP (bibliothèque standard) : routes de l'API, fichiers statiques, cache des réponses,
limites de requêtes et en-têtes de sécurité."""

import gzip
import json
import os
import threading
import time
import traceback
import urllib.request
from collections import defaultdict
from email.utils import formatdate, parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from maxplan import VERSION
from maxplan import config
from maxplan.ter import gtfs
from maxplan.api.calendrier import do_calendar, do_calprices, do_ideas, do_trends
from maxplan.api.commun import BadRequest, _p
from maxplan.api.explorer import do_explore
from maxplan.api.infos import do_insights, do_meta
from maxplan.api.lieux import do_nearest, do_stations
from maxplan.api.recherche import do_search
from maxplan.api.rentable import do_value
from maxplan.api.retours import feedback_page, save_feedback
from maxplan.taches import history_loop, warmup


WEB_DIR = os.path.join(config.ROOT, "web")


ROUTES = {
    "/api/search": ("search", do_search),
    "/api/explore": ("explore", do_explore),
    "/api/stations": ("stations", do_stations),
    "/api/nearest": ("nearest", do_nearest),
    "/api/calendar": ("calendar", do_calendar),
    "/api/calprices": ("prices", do_calprices),
    "/api/ideas": ("calendar", do_ideas),
    "/api/value": ("calendar", do_value),
    "/api/trends": ("calendar", do_trends),
    "/api/insights": ("calendar", do_insights),


    "/api/meta": (None, do_meta),
}


# ======================================================================= cache des réponses et limites
# Réponses déjà calculées : plusieurs visiteurs qui cherchent la même chose ne coûtent qu'un calcul.
# Durées courtes : les places Max changent une fois par jour, les horaires la nuit.
CACHE_TTL = {"/api/insights": 1800, "/api/search": 900, "/api/calendar": 3600, "/api/value": 3600, "/api/trends": 3600,
             "/api/explore": 1800, "/api/ideas": 3600, "/api/stations": 300, "/api/meta": 30,
             "/api/calprices": 3600}


# Calculs lourds (CPU) : au plus 2 à la fois. Sur un petit serveur, 10 calculs en parallèle finissent
# tous lentement ; en file d'attente, chacun finit vite et les requêtes légères restent fluides.
HEAVY = {"/api/search", "/api/calendar", "/api/value", "/api/trends", "/api/insights", "/api/ideas",
         "/api/calprices"}
_HEAVY_SLOTS = threading.BoundedSemaphore(2)
# prix du calendrier (≈ 20 s, en arrière-plan) : un seul à la fois, sans prendre la place des recherches
_PRICE_SLOTS = threading.BoundedSemaphore(1)
_RESP = {}
_RESP_LOCK = threading.Lock()
_INFLIGHT = {}            # requête en cours de calcul -> verrou (les suivantes identiques attendent)


def cached(path, fn, qs):
    ttl = CACHE_TTL.get(path)
    if not ttl:
        return fn(qs)
    key = (path, tuple(sorted((k, tuple(v)) for k, v in qs.items() if k != "_ip")))
    with _RESP_LOCK:
        hit = _RESP.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        flight = _INFLIGHT.setdefault(key, threading.Lock())
    with flight:                       # la même requête déjà en calcul : on attend son résultat
        with _RESP_LOCK:
            hit = _RESP.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        try:
            if path in HEAVY:
                with _PRICE_SLOTS if path == "/api/calprices" else _HEAVY_SLOTS:
                    res = fn(qs)
            else:
                res = fn(qs)
        finally:
            with _RESP_LOCK:
                _INFLIGHT.pop(key, None)
        if isinstance(res, dict) and res.pop("_nocache", False):
            return res                 # réponse bridée (budget API) : jamais servie à d'autres
        now = time.time()
        with _RESP_LOCK:
            if len(_RESP) > 3000:
                for k in [k for k, (t, _) in _RESP.items() if now - t > 900] or list(_RESP)[:1500]:
                    _RESP.pop(k, None)
            _RESP[key] = (now, res)
        return res


class RateLimiter:
    def __init__(self):
        self.hits = defaultdict(list)
        self.lock = threading.Lock()
        self.swept = time.time()

    def allow(self, key, limit, window):
        now = time.time()
        with self.lock:
            q = [t for t in self.hits[key] if now - t < window]
            ok = len(q) < limit
            if ok:
                q.append(now)
            self.hits[key] = q
            longest = max(w for _, w in config.RATE_LIMITS.values())
            if now - self.swept > 60:            # oublie les adresses IP sans activité récente
                self.hits = defaultdict(list, {k: v for k, v in self.hits.items()
                                               if v and now - v[-1] < longest})
                self.swept = now
            return ok


LIMITER = RateLimiter()


# ======================================================================= HTTP
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml",
    ".png": "image/png", ".woff2": "font/woff2", ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8", ".xml": "application/xml; charset=utf-8",
}
COMPRESSIBLE = {".html", ".js", ".css", ".json", ".webmanifest", ".svg", ".txt", ".xml"}
_GZ = {}
CSP = ("default-src 'self'; img-src 'self' data: https://server.arcgisonline.com; "
       "style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self'; connect-src 'self'; "
       "manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
       "object-src 'none'")


class Handler(BaseHTTPRequestHandler):
    timeout = 20                  # une connexion lente ou muette ne bloque pas un thread indéfiniment
    server_version = "MaxPlan/" + VERSION
    sys_version = ""

    def log_message(self, *a):
        pass

    def client_ip(self):
        """IP du visiteur. Derrière le reverse proxy, c'est la DERNIÈRE entrée de X-Forwarded-For (ajoutée
        par le proxy) qui est fiable : les précédentes peuvent être inventées par le visiteur pour
        contourner la limite de requêtes. PROXY_HOPS = nombre de proxys de confiance (0 = aucun)."""
        if config.CLIENT_IP_HEADER:          # derrière Cloudflare : « CF-Connecting-IP »
            ip = self.headers.get(config.CLIENT_IP_HEADER, "").strip()
            if ip:
                return ip[:64]
        hops = config.PROXY_HOPS
        xff = [x.strip() for x in self.headers.get("X-Forwarded-For", "").split(",") if x.strip()]

        if hops and xff:
            return xff[-min(hops, len(xff))][:64]
        return self.client_address[0]

    def _gzip_ok(self):
        return "gzip" in self.headers.get("Accept-Encoding", "")

    def _common(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        if self.headers.get("X-Forwarded-Proto", "") == "https":
            self.send_header("Strict-Transport-Security", "max-age=31536000")

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

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != "/api/feedback":
            return self._json({"error": "Adresse inconnue."}, 404)
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json({"error": "Format attendu : JSON."}, 415)
        limit, window = config.RATE_LIMITS["feedback"]
        if not LIMITER.allow((self.client_ip(), "feedback"), limit, window):
            return self._json({"error": "Merci ! Tu as déjà envoyé plusieurs messages, réessaie un peu plus tard."}, 429)
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if not 0 < n <= 10000:
            return self._json({"error": "Message trop long."}, 413)
        try:
            return self._json(save_feedback(json.loads(self.rfile.read(n).decode("utf-8"))))
        except BadRequest as e:
            return self._json({"error": str(e)}, 400)
        except Exception:
            traceback.print_exc()
            return self._json({"error": "Erreur interne, réessaie dans un instant."}, 500)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == "/healthz":
            return self._json({"ok": True, "service": "tgvmax", "version": VERSION})
        if u.path == "/admin/retours":
            import hmac
            token = _p(qs, "token")
            if not LIMITER.allow((self.client_ip(), "admin"), 20, 600):
                return self._send(429, "Trop d'essais".encode("utf-8"), "text/plain; charset=utf-8")
            if (len(config.FEEDBACK_TOKEN) < 24
                    or not hmac.compare_digest(token.encode("utf-8"), config.FEEDBACK_TOKEN.encode("utf-8"))):
                return self._send(404, "Page introuvable".encode("utf-8"), "text/plain; charset=utf-8")
            return self._send(200, feedback_page().encode("utf-8"), "text/html; charset=utf-8",
                              {"Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"})


        route = ROUTES.get(u.path)
        if not route:
            return self._static(u.path)
        qs["_ip"] = [self.client_ip()]
        group, fn = route
        if group:
            limit, window = config.RATE_LIMITS[group]
            if not LIMITER.allow((self.client_ip(), group), limit, window):
                return self._json({"error": "Beaucoup de recherches d'un coup, réessaie dans une minute."},
                                  429, {"Retry-After": "30"})
        try:
            return self._json(cached(u.path, fn, qs))
        except BadRequest as e:
            return self._json({"error": str(e)}, 400)
        except Exception:
            traceback.print_exc()
            return self._json({"error": "Erreur interne, réessaie dans un instant."}, 500)


def main():
    srv = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    srv.daemon_threads = True
    threading.Thread(target=warmup, daemon=True).start()
    threading.Thread(target=history_loop, daemon=True).start()
    threading.Thread(target=gtfs.refresh_loop, daemon=True).start()


    print(f"\n🚄  MaxPlan {VERSION}  →  http://{config.HOST}:{config.PORT}", flush=True)
    print("    Ctrl+C pour arrêter.\n", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
        srv.shutdown()

# -*- coding: utf-8 -*-
"""Client minimal de l'API SNCF (Navitia, api.sncf.com) : géocodage + calcul TER.

- geocode(label)  -> {id, name, lat, lon}  (cache disque persistant)
- journey(...)    -> meilleur itinéraire TER/régional entre deux gares
"""

import base64
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

import config

BASE = "https://api.sncf.com/v1"
CACHE_FILE = os.path.join(config.DATA_DIR, "geo_cache_v2.json")   # v2 : choix de la gare par ville

# Trains exclus des compléments « TER » : grande vitesse et trains à réservation obligatoire.
FORBIDDEN_MODES = ("OUI", "TGVOUIGO", "OUIGO_TC", "LYR", "DBS", "ICN")

# Surcharges manuelles pour les libellés tgvmax ambigus / "(intramuros)".
LABEL_OVERRIDES = {
    "PARIS (intramuros)": "Paris Gare de Lyon",
    "LYON (intramuros)": "Lyon Part Dieu",
    "LILLE (intramuros)": "Lille Europe",
}


def _clean(label):
    if label in LABEL_OVERRIDES:
        return LABEL_OVERRIDES[label]
    s = re.sub(r"\s*\([^)]*\)\s*$", "", label)  # retire le suffixe "(...)"
    return s.replace(".", "").strip().title()


def _fold(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _variants(q):
    """Nom complet, puis raccourci par la fin (« Valence Tgv Auvergne Rhone Alpes » -> « Valence Tgv »),
    puis dernier mot en tête (« Les Aubrais Orleans » -> « Orleans Les Aubrais »)."""
    w = q.split()
    out = [q] + [" ".join(w[:n]) for n in range(len(w) - 1, 0, -1)]
    if len(w) >= 2:
        out.insert(1, " ".join(w[-1:] + w[:-1]))
    return list(dict.fromkeys(out))


class Navitia:
    def __init__(self, token):
        self.auth = "Basic " + base64.b64encode((token + ":").encode()).decode()
        self._lock = threading.Lock()
        self._journeys = {}  # cache mémoire des itinéraires : clé -> (horodatage, résultat)
        self._cache = {}
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, encoding="utf-8") as f:
                    self._cache = {k: v for k, v in json.load(f).items() if v}   # anciens échecs ignorés
            except Exception:
                self._cache = {}
        self._miss = {}   # échecs récents (mémoire seulement) : libellé -> horodatage
        self._coverage = None
        self._coverage_ts = 0.0

    # -- HTTP --------------------------------------------------------------
    def _get(self, path):
        req = urllib.request.Request(BASE + path, headers={"Authorization": self.auth})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            return {"_status": e.code}
        except Exception as e:
            return {"_error": str(e)}

    def _save_cache(self):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False)
        except Exception:
            pass

    # -- Couverture (période de production) --------------------------------
    def coverage(self):
        if self._coverage is None or time.time() - self._coverage_ts > 6 * 3600:
            d = self._get("/coverage/sncf")
            reg = (d.get("regions") or [{}])[0] if isinstance(d, dict) else {}
            if reg.get("start_production_date") or self._coverage is None:
                self._coverage = {
                    "start": reg.get("start_production_date"),
                    "end": reg.get("end_production_date"),
                }
                self._coverage_ts = time.time()
        return self._coverage

    def date_in_range(self, ymd):  # ymd = 'YYYY-MM-DD'
        c = self.coverage()
        if not c.get("start") or not c.get("end"):
            return True
        d = ymd.replace("-", "")
        return c["start"] <= d <= c["end"]

    # -- Géocodage ---------------------------------------------------------
    def _lookup(self, q):
        """Meilleure gare pour q. Navitia classe « Paris - Gare de Lyon » avant « Lyon Part Dieu »
        quand on cherche « Lyon » : on préfère les gares dont la ville ou le nom commence par q."""
        d = self._get("/coverage/sncf/places?type%5B%5D=stop_area&count=8&q=" + urllib.parse.quote(q))
        fq = _fold(q)
        best = None
        for rank, p in enumerate(d.get("places", []) if isinstance(d, dict) else []):
            coord = (p.get("stop_area") or {}).get("coord") or {}
            if not (coord.get("lat") and coord.get("lon")):
                continue
            name = p.get("name", q)
            m = re.search(r"\(([^)]*)\)\s*$", name)
            city, fname = _fold(m.group(1) if m else ""), _fold(name)
            score = 0 if (fname.startswith(fq) or city == fq) else 1 if city.startswith(fq) else 2
            if best is None or (score, rank) < best[0]:
                best = ((score, rank), {"id": p["id"], "name": name,
                                        "lat": float(coord["lat"]), "lon": float(coord["lon"])})
        return best and best[1]

    def geocode(self, label):
        v = self._cache.get(label)
        if v:
            return v
        if time.time() - self._miss.get(label, 0) < 3600:   # échec récent : on réessaiera plus tard
            return None
        res = None
        base = _clean(label)
        key = _fold(base.split()[0]) if base.split() else ""
        for i, q in enumerate(_variants(base)):
            res = self._lookup(q)
            # une variante raccourcie n'est acceptée que si le lieu trouvé porte bien le nom de la ville
            if res and (i == 0 or key in _fold(res["name"])):
                break
            res = None
        with self._lock:
            if res:
                self._cache[label] = res
                self._miss.pop(label, None)
                self._save_cache()
            else:
                self._cache.pop(label, None)
                self._miss[label] = time.time()   # jamais persisté : pas d'échec « définitif »
        return res

    # -- Recherche de gares (autocomplétion) -------------------------------
    def places(self, q, limit=8):
        if not q or len(q) < 2:
            return []
        d = self._get("/coverage/sncf/places?" + urllib.parse.urlencode(
            [("type[]", "stop_area"), ("count", limit), ("q", q)]))
        out = []
        for p in d.get("places", []) if isinstance(d, dict) else []:
            sa = p.get("stop_area") or {}
            c = sa.get("coord") or {}
            if c.get("lat") and c.get("lon"):
                out.append({"id": p["id"], "name": p.get("name", q),
                            "lat": float(c["lat"]), "lon": float(c["lon"])})
        return out

    # -- Calcul d'itinéraire (segment TER de complément) -------------------
    def journey(self, from_id, to_id, ymd, hhmm, max_transfers=1):
        """Meilleur trajet from->to partant après hhmm le jour ymd (mis en cache). None si rien."""
        key = (from_id, to_id, ymd, hhmm, int(max_transfers))
        now = time.time()
        with self._lock:
            hit = self._journeys.get(key)
        if hit and now - hit[0] < config.JOURNEY_TTL:
            return hit[1]
        res = self._journey(from_id, to_id, ymd, hhmm, max_transfers)
        with self._lock:
            if len(self._journeys) > 5000:          # borne mémoire : on vide les plus anciennes
                for k, _ in sorted(self._journeys.items(), key=lambda kv: kv[1][0])[:2500]:
                    self._journeys.pop(k, None)
            self._journeys[key] = (now, res)
        return res

    def _journey(self, from_id, to_id, ymd, hhmm, max_transfers=1):
        if not self.date_in_range(ymd):
            return None
        dt = ymd.replace("-", "") + "T" + hhmm.replace(":", "") + "00"
        path = (f"/coverage/sncf/journeys?from={urllib.parse.quote(from_id)}"
                f"&to={urllib.parse.quote(to_id)}&datetime={dt}"
                f"&datetime_represents=departure&max_nb_journeys=3"
                f"&max_nb_transfers={int(max_transfers)}"
                + "".join(f"&forbidden_uris%5B%5D=commercial_mode:{m}" for m in FORBIDDEN_MODES))
        d = self._get(path)
        journeys = d.get("journeys", []) if isinstance(d, dict) else []
        if not journeys:
            return None

        def cost(jj):
            # arrivée (en minutes), chaque correspondance « coûte » 20 min : on ne change de train
            # que si ça fait vraiment arriver plus tôt, sinon on préfère le trajet direct
            s = jj.get("arrival_date_time", "")
            try:
                arr = int(s[6:8]) * 1440 + int(s[9:11]) * 60 + int(s[11:13])
            except ValueError:
                arr = 0
            return arr + 20 * jj.get("nb_transfers", 0)

        j = min(journeys, key=cost)

        def hm(s):  # "20260708T090000" -> "09:00"
            if not s or "T" not in s:
                return ""
            t = s.split("T")[1]
            return f"{t[0:2]}:{t[2:4]}"

        def coord(obj):
            for k in ("stop_point", "stop_area"):
                c = (obj.get(k) or {}).get("coord") if obj else None
                if c:
                    return float(c["lat"]), float(c["lon"])
            c = (obj or {}).get("coord")
            return (float(c["lat"]), float(c["lon"])) if c else None

        from tgvmax_core import haversine_km
        modes, networks, sections, first_dep, last_arr = [], [], [], None, None
        for s in j.get("sections", []):
            if s.get("type") != "public_transport":
                continue
            di = s.get("display_informations", {})
            mode = di.get("commercial_mode") or di.get("physical_mode") or "Train"
            modes.append(mode)
            if di.get("network"):
                networks.append(di["network"])
            if first_dep is None:
                first_dep = s.get("departure_date_time")
            last_arr = s.get("arrival_date_time")
            a, b = coord(s.get("from")), coord(s.get("to"))
            dist = haversine_km(a[0], a[1], b[0], b[1]) if a and b else 0.0
            sections.append({
                "mode": mode, "network": di.get("network", ""),
                "from": (s.get("from") or {}).get("name", ""), "to": (s.get("to") or {}).get("name", ""),
                "dep": hm(s.get("departure_date_time", "")), "arr": hm(s.get("arrival_date_time", "")),
                "dist_km": dist,
                "lat": ((a[0] + b[0]) / 2) if a and b else None,
                "lon": ((a[1] + b[1]) / 2) if a and b else None,
                "coords": [list(a), list(b)] if a and b else [],
            })
        if not modes:
            return None
        return {
            "duration_min": round(j.get("duration", 0) / 60),
            "transfers": j.get("nb_transfers", 0),
            "modes": modes, "networks": networks, "sections": sections,
            "distance_km": round(sum(x["dist_km"] for x in sections)),
            "departure": hm(first_dep or j.get("departure_date_time", "")),
            "arrival": hm(last_arr or j.get("arrival_date_time", "")),
        }


navitia = Navitia(config.SNCF_TOKEN)

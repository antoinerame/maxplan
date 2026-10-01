# -*- coding: utf-8 -*-
"""Fourchettes de prix des billets payants (open data SNCF), pour le calcul « Max est-il rentable ? ».

Jeux de données (licence ODbL, SNCF Voyageurs) :
  - tarifs-tgv-inoui-ouigo : prix minimum / maximum par liaison TGV INOUI, par classe et profil tarifaire ;
  - tarifs-intercites      : idem pour les Intercités à réservation.
On garde la 2de classe, profils « Tarif Normal » et « Tarif Avantage » (carte Avantage, ou avantage MAX).
"""

import json
import threading
import time
import urllib.parse
import urllib.request

from maxplan.base import normalize

BASE = "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/"
TTL = 24 * 3600
PROFILES = {"Tarif Normal": "normal", "Tarif Avantage": "avantage"}

_lock = threading.Lock()
_cache = {"ts": 0.0, "rows": []}


def _export(dataset, where, select):
    url = BASE + dataset + "/exports/json?" + urllib.parse.urlencode({"where": where, "select": select, "limit": -1})
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def _rows():
    """[(origine normalisée, destination normalisée, profil, min, max)] ; rechargé une fois par jour."""
    with _lock:
        if _cache["rows"] and time.time() - _cache["ts"] < TTL:
            return _cache["rows"]
        rows = []
        try:
            for x in _export("tarifs-tgv-inoui-ouigo",
                             "transporteur='TGV INOUI' and classe='2'",
                             "gare_origine,gare_destination,profil_tarifaire,prix_minimum,prix_maximum"):
                p = PROFILES.get(x.get("profil_tarifaire"))
                if p and x.get("prix_minimum") is not None:
                    rows.append((normalize(x["gare_origine"]), normalize(x["gare_destination"]), p,
                                 float(x["prix_minimum"]), float(x["prix_maximum"])))
            for x in _export("tarifs-intercites", "classe='2'",
                             "origine,destination,profil_tarifaire,prix_min,prix_max"):
                p = PROFILES.get(x.get("profil_tarifaire"))
                if p and x.get("prix_min") is not None:
                    rows.append((normalize(x["origine"]), normalize(x["destination"]), p,
                                 float(x["prix_min"]), float(x["prix_max"])))
        except Exception:
            if _cache["rows"]:
                return _cache["rows"]
            raise
        _cache.update(ts=time.time(), rows=rows)
        return rows


def _matches(gare, labels):
    """La gare du jeu de tarifs correspond-elle à l'une de nos gares ? « PARIS (intramuros) » couvre
    toutes les gares parisiennes ; sinon comparaison du nom normalisé (tirets et « saint » gommés)."""
    g = gare.replace("saint ", "st ").replace("-", " ")
    for lab in labels:
        n = normalize(lab).replace("saint ", "st ")
        if "(intramuros)" in lab:
            if g.startswith(n + " ") or g == n:
                return True
        elif g == n or g.startswith(n + " ") or n.startswith(g + " "):
            return True
    return False


def price_range(origins, targets):
    """Prix d'un aller simple en 2de classe entre deux groupes de gares.
    {"normal": {"min", "max", "typical"}, "avantage": {...}} ou None si la liaison n'est pas tarifée
    (liaison avec correspondance, gare hors grandes lignes…)."""
    out = {}
    for o, d, p, lo, hi in _rows():
        # le jeu de données ne liste chaque liaison que dans un sens : le prix vaut pour les deux
        if (_matches(o, origins) and _matches(d, targets)) or (_matches(o, targets) and _matches(d, origins)):
            out.setdefault(p, []).append((lo, hi))
    if "normal" not in out:
        return None
    res = {}
    for p, rng in out.items():
        res[p] = {"min": min(r[0] for r in rng), "max": max(r[1] for r in rng),
                  # prix « typique » : milieu de fourchette, les billets pris à l'avance étant moins chers
                  "typical": round(sum((r[0] + r[1]) / 2 for r in rng) / len(rng), 1)}
    res.setdefault("avantage", res["normal"])
    return res

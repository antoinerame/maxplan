# -*- coding: utf-8 -*-
"""Région administrative d'un point (lat, lon), via les contours simplifiés des 13 régions.

Sert à appliquer la bonne réduction TER régionale (chaque région a son réseau et ses cartes),
indépendamment des noms de réseaux renvoyés par Navitia, qui ne sont pas fiables.
"""

import json
import math
import os
import threading

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "geo", "regions.json")

# code INSEE -> (nom, réseau TER régional)
REGIONS = {
    "84": ("Auvergne-Rhône-Alpes", "TER Auvergne-Rhône-Alpes"),
    "93": ("Provence-Alpes-Côte d'Azur", "ZOU !"),
    "76": ("Occitanie", "liO"),
    "75": ("Nouvelle-Aquitaine", "TER Nouvelle-Aquitaine"),
    "53": ("Bretagne", "BreizhGo"),
    "28": ("Normandie", "Nomad"),
    "32": ("Hauts-de-France", "TER Hauts-de-France"),
    "44": ("Grand Est", "Fluo Grand Est"),
    "52": ("Pays de la Loire", "Aléop"),
    "24": ("Centre-Val de Loire", "Rémi"),
    "27": ("Bourgogne-Franche-Comté", "Mobigo"),
    "11": ("Île-de-France", "Transilien"),
    "94": ("Corse", "Chemins de fer de la Corse"),
}

_POLYS = None
_LOCK = threading.Lock()


def _load():
    global _POLYS
    if _POLYS is None:
        with _LOCK:
            if _POLYS is None:
                with open(PATH, encoding="utf-8") as f:
                    data = json.load(f)
                polys = []
                for feat in data["features"]:
                    code = feat["properties"]["code"]
                    g = feat["geometry"]
                    parts = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
                    for rings in parts:
                        xs = [p[0] for p in rings[0]]
                        ys = [p[1] for p in rings[0]]
                        polys.append((code, (min(xs), min(ys), max(xs), max(ys)), rings))
                _POLYS = polys
    return _POLYS


def _in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def locate(lat, lon):
    """Code INSEE de la région contenant le point, sinon la plus proche (< ~30 km), sinon None."""
    if lat is None or lon is None:
        return None
    x, y = lon, lat
    polys = _load()
    for code, (x0, y0, x1, y1), rings in polys:
        if x0 <= x <= x1 and y0 <= y <= y1 and _in_ring(x, y, rings[0]) \
                and not any(_in_ring(x, y, h) for h in rings[1:]):
            return code
    # repli : gare côtière / frontalière hors du contour simplifié -> sommet le plus proche
    best, bd = None, float("inf")
    kx = math.cos(math.radians(lat))
    for code, (x0, y0, x1, y1), rings in polys:
        if x < x0 - 0.5 or x > x1 + 0.5 or y < y0 - 0.5 or y > y1 + 0.5:
            continue
        for px, py in rings[0]:
            d = ((px - x) * kx) ** 2 + (py - y) ** 2
            if d < bd:
                best, bd = code, d
    return best if bd < 0.3 ** 2 else None


def name(code):
    return REGIONS.get(code, (None, None))[0]


def as_list():
    return [{"code": c, "name": n, "network": b} for c, (n, b) in
            sorted(REGIONS.items(), key=lambda kv: kv[1][0])]

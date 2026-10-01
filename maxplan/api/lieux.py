"""/api/stations (autocomplétion) et /api/nearest (gare Max la plus proche)."""

from maxplan import base
from maxplan.moteur import donnees
from maxplan.ter import gtfs
from maxplan.ter.navitia import navitia
from maxplan.api.commun import BadRequest, _p
from maxplan.api.trajets import display_name, nice_place


def do_stations(qs):
    q, kind = _p(qs, "q"), _p(qs, "kind", "origin")
    out, seen = [], set()
    for label in donnees.search_stations(q, limit=8):
        key = base.normalize(label)
        if key not in seen:
            seen.add(key)
            out.append({"label": label, "name": display_name(label, navitia._cache.get(label) or None),
                        "max": True})
    # destinations : aussi des gares hors réseau Max (ex. Manosque), prises dans les horaires GTFS
    # (gratuit) ; l'API SNCF seulement en secours et quand il y a peu de gares Max
    # départ d'un trajet (« start ») aussi : une ville sans train Max (Annecy, Gap) se rejoint en TER ou
    # en car ; pas pour l'Explorer ni « Rentable ? » (« origin »), qui ne partent que d'une gare Max
    if kind in ("dest", "start") and (gtfs.ready() or len(out) < 3):

        for p in (gtfs.places(q, limit=6) if gtfs.ready() else navitia.places(q, limit=6)):
            key = base.normalize(nice_place(p["name"]))
            if key not in seen:
                seen.add(key)
                out.append({"label": p["name"], "name": nice_place(p["name"]), "max": False,
                            "car": str(p.get("id", "")).startswith("gtfs:")})
    return out[:10]


def do_nearest(qs):
    try:
        lat, lon = float(_p(qs, "lat")), float(_p(qs, "lon"))
    except ValueError:
        raise BadRequest("Position invalide.")
    ranked = []
    for s in donnees.all_stations():
        g = navitia._cache.get(s)
        if g:
            ranked.append((base.haversine_km(lat, lon, g["lat"], g["lon"]), s, g))
    ranked.sort(key=lambda x: x[0])
    return [{"label": s, "name": display_name(s, g), "km": round(d)} for d, s, g in ranked[:3]]

"""/api/explore : toutes les gares atteignables à 0 € depuis une ville, un jour donné."""

from maxplan import base
from maxplan import config
from maxplan.moteur import gares
from maxplan.moteur import parcours
from maxplan.ter import prix
from maxplan.api.commun import SENIOR_NOTICE, _int, _p, _place, check_date, past_min, senior_weekend
from maxplan.api.trajets import access, display_name, edges_for, geocode_many, ticket_price


def do_explore(qs):
    src, date = _place(qs, "from", "paris"), check_date(_p(qs, "date"))
    prefs = prix.prefs_from_qs(qs)
    edges = [] if senior_weekend(prefs, date) else edges_for(date)
    stations = {e["o"] for e in edges} | {e["d"] for e in edges}
    all_origins, near = gares.resolve_area(src, stations)
    # « où aller à 0 € » : pas de départ d'une gare qu'on ne rejoint qu'en payant (Saint-Exupéry et son
    # Rhônexpress quand on part de Lyon, Lorraine TGV et sa navette quand on part de Metz)
    origins = [o for o in all_origins
               if not ticket_price((access(o, all_origins, near) or (0, 0, 0, 0))[3])] or all_origins
    best = parcours.reachable(edges, origins, max_conn=_int(qs, "maxconn", 1, 0, 2), min_dep=past_min(date))
    geo = geocode_many(list(origins) + list(best))
    og = next((geo[o] for o in origins if geo.get(o)), None)
    # la ville de départ elle-même (Lyon depuis Saint-Exupéry, Massy depuis Paris) n'est pas une destination
    home = set(all_origins) | {t for o in all_origins for t, _, _ in gares.TWINS.get(o, ())}
    dests = []
    for label, (nlegs, path) in best.items():
        g = geo.get(label)
        if not g or label in home:
            continue
        pts = [geo.get(path[0]["o"])] + [geo.get(e["d"]) for e in path]
        if nlegs > 1 and all(pts):               # pas de détour absurde (Bourg-en-Bresse via Roissy)
            run = sum(base.haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in zip(pts, pts[1:]))
            if run > config.DETOUR_MAX_EXPLORE * max(1.0, base.haversine_km(
                    pts[0]["lat"], pts[0]["lon"], g["lat"], g["lon"])):
                continue
        dests.append({
            "label": label, "name": display_name(label, g), "lat": g["lat"], "lon": g["lon"],
            "nconn": nlegs - 1, "dep": base.min_to_hhmm(path[0]["dep"]),
            "arr": base.min_to_hhmm(path[-1]["arr"]), "arr_day": path[-1]["arr"] // 1440,
            "via": [display_name(e["d"], geo.get(e["d"])) for e in path[:-1]],
            # parti d'une autre gare que la principale (Marne-la-Vallée quand on explore depuis Paris)
            "from_name": (display_name(path[0]["o"], geo.get(path[0]["o"]))
                          if origins and path[0]["o"] != origins[0] else None),
        })
    dests.sort(key=lambda x: (x["nconn"], base.normalize(x["name"])))
    res = {
        "mode": "explore", "date": date, "weekday": base.weekday(date),
        "origin": {"label": origins[0] if origins else src,
                   "name": display_name(origins[0], og) if origins else src,
                   "lat": og and og["lat"], "lon": og and og["lon"]},
        "destinations": dests,
    }
    if senior_weekend(prefs, date):
        res["notice"] = SENIOR_NOTICE
    return res

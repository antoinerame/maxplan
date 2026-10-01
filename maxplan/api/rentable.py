"""/api/value : « l'abonnement Max est-il rentable pour moi ? »."""

from maxplan import base
from maxplan import config
from maxplan import historique
from maxplan.moteur import donnees
from maxplan.moteur import gares
from maxplan.moteur import parcours
from maxplan.ter import gtfs
from maxplan.ter import prix
from maxplan.ter import tarifs
from maxplan.ter.navitia import navitia
from maxplan.api.commun import BadRequest, _p, _place, coming_dates, senior_weekend, shift, weekday_idx
from maxplan.api.trajets import (
    DAY_POOL, dest_place, detour_ratio, display_name, edges_for, max_trips, od_areas, path_nocturnal, tail_end,
)


def do_value(qs):
    """« Max est-il rentable pour moi ? » : pour une liaison et son retour, la part des jours (sur les
    30 prochains) avec au moins un train à 0 € de jour, les prix officiels des billets payants, et ce
    que dit l'historique des places Max."""
    src, dst = _place(qs, "from"), _place(qs, "to")
    if not src or not dst:
        raise BadRequest("Indique une gare de départ et une gare d'arrivée.")
    kind = _p(qs, "days", "all")
    prefs = prix.prefs_from_qs(qs)
    od_areas(src, dst, set(donnees.all_stations()))   # départ inconnu, même ville : erreur claire
    dates = [d for d in coming_dates()
             if kind == "all" or (weekday_idx(d) >= 5) == (kind == "weekend")]
    known = set(donnees.all_stations())

    def ter_option(date, edges, origins, targets, dest):

        """Les jours sans trajet 100 % Max : peut-on aller en Max jusqu'à une gare proche puis finir en
        TER ? Le TER est vérifié dans les horaires locaux (pas d'appel à l'API SNCF) : on ne retient
        qu'un TER qui existe vraiment ce jour-là, avec son prix estimé sur le trajet réel."""
        if not dest:
            return None
        tset = set(targets)
        o_km = min((base.haversine_km(g["lat"], g["lon"], dest["lat"], dest["lon"])
                    for g in (navitia._cache.get(o) for o in origins) if g), default=None)
        cands = []
        for s, (_, path) in parcours.reachable(edges, origins, max_conn=1).items():
            g = navitia._cache.get(s)
            if s in tset or not g or path_nocturnal(path):
                continue
            km = base.haversine_km(g["lat"], g["lon"], dest["lat"], dest["lon"])
            if km > config.TER_MAX_DISTANCE_KM or (o_km is not None and km >= o_km):
                continue
            # pas de détour que la recherche refuserait (Paris → Valence pour remonter à Lyon)
            if o_km and detour_ratio(origins, s, {}, dest, o_km) > config.DETOUR_MAX:
                continue
            est = prix.estimate([{"mode": "TER", "dist_km": km, "lat": (g["lat"] + dest["lat"]) / 2,
                                     "lon": (g["lon"] + dest["lon"]) / 2}], prefs)["price"]
            cands.append((est, km, s, g, path))
        cands.sort(key=lambda c: c[:2])
        if not (gtfs.ready() and gtfs.covers(date) and gtfs.knows(dest.get("id", ""))):
            return (cands[0][0], display_name(cands[0][2], cands[0][3])) if cands else None
        for est, km, s, g, path in cands[:2]:          # les deux relais les moins chers
            if not gtfs.knows(g["id"]):
                continue
            ready = path[-1]["arr"] + gares.min_connection(s)
            jr = gtfs.journey(g["id"], dest["id"], shift(date, ready // 1440), base.min_to_hhmm(ready))
            if jr and tail_end(jr, ready) <= config.TER_MAX_TAIL_MIN:
                return prix.estimate(jr["sections"], prefs)["price"], display_name(s, g)
        return None

    def count(date, a, b, dest):
        """(trajets 100 % Max, durée du plus rapide direct, (prix TER, gare-relais) si Max + TER possible)."""
        if senior_weekend(prefs, date):
            return 0, None, None
        try:
            edges = edges_for(date)
        except Exception:
            return None
        stations = {e["o"] for e in edges} | {e["d"] for e in edges}
        try:
            origins, o_near, targets, t_near = od_areas(a, b, stations)
        except BadRequest:
            return 0, None, None
        # jusqu'à 3 correspondances, comme le calendrier affiché à côté
        its = max_trips(parcours.search(edges, origins, targets, max_conn=3, max_results=200),
                        origins, targets, o_near, t_near)
        direct = [x["_arr"] - x["_dep"] for x in its if len(x["legs"]) == 1]
        ter = None if its else ter_option(date, edges, origins, targets, dest)
        return len(its), min(direct, default=None), ter

    def direction(a, b):
        dest = dest_place(b, gares.resolve_city(b, known), known)
        got = [c for c in DAY_POOL.map(lambda d: count(d, a, b, dest), dates) if c is not None]
        counts = [c[0] for c in got]
        durations = [c[1] for c in got if c[1]]
        ters = [c[2] for c in got if c[2]]
        origins, targets = gares.resolve_city(a, known), gares.resolve_city(b, known)
        try:
            prices = tarifs.price_range(origins, targets)
        except Exception:
            prices = None
        if prices and durations:
            # Carte Avantage / avantage MAX : prix plafonnés en 2de classe selon la durée du trajet direct
            # (49 € < 1 h 30, 69 € jusqu'à 3 h, 89 € au-delà ; toujours en vigueur en 2026, sans garantie)
            d = min(durations)
            cap = 49 if d < 90 else 69 if d <= 180 else 89
            av = prices["avantage"]
            prices["avantage"] = {k: min(v, cap) for k, v in av.items()}
            prices["cap"] = cap
        ter = None
        if ters:
            relays = [t[1] for t in ters]
            ter = {"days": len(ters), "price": round(sum(t[0] for t in ters) / len(ters), 1),
                   "via": max(sorted(set(relays)), key=relays.count)}
        return {"days": len(counts), "free_days": sum(1 for c in counts if c), "ter": ter,


                "avg_trains": round(sum(counts) / len(counts), 1) if counts else 0,
                "prices": prices, "history": historique.od_stats(origins, targets, kind=kind)}

    return {"from": src, "to": dst, "days_kind": kind, "out": direction(src, dst), "ret": direction(dst, src)}

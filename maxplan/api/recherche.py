"""/api/search : trajets 100 % Max, puis compléments TER / cars jusqu'à la destination."""

import threading
import time
import traceback

from maxplan import base
from maxplan import config
from maxplan.moteur import donnees
from maxplan.moteur import gares
from maxplan.moteur import parcours
from maxplan.ter import gtfs
from maxplan.ter import prix
from maxplan.ter.navitia import navitia
from maxplan.api.commun import (
    BadRequest, SENIOR_NOTICE, TIME_RE, _flag, _int, _p, _place, check_date, check_time, past_min,
    senior_weekend, shift,
)
from maxplan.api.trajets import (
    DAY_POOL, IO_POOL, _access_min, access, nearest_max, od_areas, booking_url, dest_place, detour_ratio, direct_fare,
    display_name, drop_dominated, edges_for, free_place, geocode_many, itinerary_from_path,
    max_legs, nice_mode, nice_place, backtracks, path_detour, path_nocturnal, path_tickets, tail_end, change_tickets, ticket_price,
)


def ter_query_date(ymd):
    """Date à interroger pour les horaires TER. L'API SNCF ne donne les horaires que ~4 semaines à
    l'avance ; au-delà, on prend le même jour de la semaine 1 à 5 semaines plus tôt (les horaires TER
    se répètent d'une semaine à l'autre) et on signale que l'horaire est estimé."""
    if navitia.date_in_range(ymd):
        return ymd, False
    for k in range(1, 6):
        d = shift(ymd, -7 * k)
        if navitia.date_in_range(d):
            return d, True
    return None, False


def tail_too_slow(jr, ready, g, dest):
    """Le trajet local (GTFS) est absent ou anormalement long pour la distance : un car régional hors
    SNCF (absent du GTFS) fait peut-être bien mieux, on demandera à l'API."""
    if jr is None:
        return True
    km = base.haversine_km(g["lat"], g["lon"], dest["lat"], dest["lon"])
    # au-delà de 150 km, un car régional manquant ne changerait pas grand-chose : pas de secours
    return km <= 150 and tail_end(jr, ready) > max(90, 30 + 1.2 * km)


def ter_estimated_notice():

    end = (navitia.coverage() or {}).get("end") or ""
    when = f" (publiés jusqu'au {int(end[6:8])}/{end[4:6]})" if len(end) == 8 else ""
    return ("Horaires TER estimés : l'API de la SNCF ne donne pas encore les horaires de ce jour"
            f"{when}. On reprend ceux du même jour de la semaine précédente ; vérifie sur SNCF Connect.")


def origin_ter_jobs(src, dst, date, edges, stations, origins, targets, opts, win, has_max,
                    max_relays=None, quota=None):
    """TER ou car du lieu de départ jusqu'à une gare Max proche, puis trains Max. Pour chaque train Max
    au départ de la gare-relais, on cherche le TER qui part le plus tard en arrivant à temps (horaires
    locaux, aucune requête à l'API). Renvoie [(relais, chemin Max, géo du relais, trajet TER)]."""
    place = navitia.geocode(origins[0]) if origins else free_place(src)
    if not place or not gtfs.ready() or not gtfs.knows(place.get("id", "")):
        return []
    dest = next((g for g in (navitia._cache.get(t) for t in targets) if g), None) or free_place(dst)
    if not dest:
        return []
    direct = base.haversine_km(place["lat"], place["lon"], dest["lat"], dest["lon"])
    # depuis une ville qui a des trains Max ce jour-là, on ne regarde que les grandes gares toutes proches ;
    # sinon (Annecy un dimanche sans TGV) jusqu'à 150 km (Lyon, Chambéry, Grenoble…)
    reach = config.ORIGIN_TER_KM_MAX_CITY if origins and has_max else config.ORIGIN_TER_KM
    skip = set(origins) | set(targets)
    cands = []
    for s in stations - skip:
        g = navitia._cache.get(s)
        if not g or not gtfs.knows(g.get("id", "")):
            continue
        km = base.haversine_km(place["lat"], place["lon"], g["lat"], g["lon"])
        to_dest = base.haversine_km(g["lat"], g["lon"], dest["lat"], dest["lon"])
        # proche du départ, et sur le chemin (pas Annecy → Genève pour aller à Marseille)
        if km <= reach and km + to_dest <= config.DETOUR_MAX * max(direct, 1.0) and to_dest < direct + 30:
            cands.append((km, s, g))
    cands.sort(key=lambda c: c[0])
    # gares-relais qui ont vraiment des trains Max vers l'arrivée ce jour-là, les plus proches d'abord
    useful = []
    for km, s, g in cands:
        # d'abord (calcul léger) : cette gare a-t-elle des trains Max vers l'arrivée ?
        if not parcours.search(edges, [s], targets, max_conn=opts["maxconn"], max_results=1,
                               min_dep=win["min_dep"] + 20, max_dep=min(1440, win["max_dep"] + 300)):
            continue
        # première arrivée possible en TER à la gare-relais : seuls les trains Max qui partent après comptent
        first = None
        for t0 in range(max(240, win["min_dep"]), min(1380, win["max_dep"]) + 1, 300):   # 4 h, 9 h, 14 h…
            first = gtfs.journey(place["id"], g["id"], date, base.min_to_hhmm(t0))
            if first:
                break
        if not first or first["duration_min"] > config.TER_MAX_TAIL_MIN:
            continue
        ready = first["arr_min"] + gares.min_connection(s)
        paths = parcours.search(edges, [s], targets, max_conn=opts["maxconn"], max_results=40,
                                min_dep=ready, max_dep=min(1440, win["max_dep"] + 300))
        if paths:
            useful.append((s, g, paths))
        if len(useful) >= (max_relays or (config.ORIGIN_TER_CANDIDATES if not (origins and has_max) else 2)):
            break
    jobs = []
    for rank, (s, g, paths) in enumerate(useful):
        n_max = quota or (3, 2, 2, 1)[min(rank, 3)]
        kept, last = [], None
        for p in sorted(paths, key=lambda p: (p[-1]["arr"], -p[0]["dep"])):
            if any(e["d"] in skip and e["d"] not in targets for e in p):
                continue
            if last is None or p[-1]["arr"] - last >= config.TER_ARRIVAL_SPACING_MIN:
                kept.append(p)
                last = p[-1]["arr"]
            if len(kept) >= n_max:
                break
        for p in kept:
            deadline = p[0]["dep"] - gares.min_connection(s)
            jr = gtfs.journey_by(place["id"], g["id"], date, deadline)
            if not jr or jr["duration_min"] > config.TER_MAX_TAIL_MIN:
                continue
            if not (win["min_dep"] <= jr["dep_min"] <= win["max_dep"]):
                continue
            jobs.append((s, p, g, dict(jr, _place=place)))
    return jobs


def head_itinerary(job, date, geo, prefs):
    """Trajet « TER puis Max » : le TER (ou car) du départ, puis les tronçons Max."""
    s, path, g, jr = job
    place = jr["_place"]
    legs = max_legs(path, date, geo)
    price = prix.estimate(jr["sections"], prefs)
    tdep, tarr = jr["dep_min"], jr["arr_min"]
    head = {
        "free": False, "mode": " + ".join(dict.fromkeys(nice_mode(m) for m in jr["modes"])) or "TER",
        "networks": list(dict.fromkeys(jr["networks"])), "train": "",
        "from": place.get("id", ""), "to": s, "from_name": nice_place(place["name"]),
        "to_name": legs[0]["from_name"] if "(intramuros)" in s else display_name(s, g),
        "dep": jr["departure"], "arr": jr["arrival"], "dep_day": tdep // 1440, "arr_day": tarr // 1440,
        "duration_min": tarr - tdep, "transfers": jr["transfers"], "price": price,
        "steps": [{"mode": nice_mode(x["mode"]), "from": nice_place(x["from"]), "to": nice_place(x["to"]),
                   "dep": x["dep"], "arr": x["arr"]} for x in jr["sections"]],
        "path": [pt for x in jr["sections"] for pt in x["coords"]],
        "from_lat": place["lat"], "from_lon": place["lon"], "to_lat": g["lat"], "to_lon": g["lon"],
        "book_url": booking_url(place["name"], place, s, g, date, jr["departure"]),
    }
    return {
        "_dep": tdep, "_arr": path[-1]["arr"], "_tickets": change_tickets(legs),
        "type": "ter+max", "paid": True, "cost_eur": price["price"], "nresa": len(path),
        "changes": len(path) + jr["transfers"],
        "departure": jr["departure"], "arrival": legs[-1]["arr"], "arrival_day": path[-1]["arr"] // 1440,
        "duration_min": path[-1]["arr"] - tdep,
        "nocturnal": path_nocturnal(path) or parcours.night_overlap(tdep, tarr)
                     or parcours.night_overlap(tarr, path[0]["dep"]),
        "legs": [head] + legs,
    }


def search_one_day(src, dst, date, opts):
    prefs = opts["prefs"]
    if senior_weekend(prefs, date):
        return {"itineraries": [], "notice": SENIOR_NOTICE}
    edges = edges_for(date)
    stations = {e["o"] for e in edges} | {e["d"] for e in edges}
    # + gares voisines (Lorraine TGV pour Metz…) ; départ sans train Max (Annecy, Gap) : TER au départ
    origins, o_near, targets, t_near = od_areas(src, dst, stations, no_origin_ok=opts["ter"])
    win = dict(min_dep=opts["min_dep"], max_dep=opts["max_dep"])

    # 1) trajets 100 % Max
    max_paths = parcours.search(edges, origins, targets, max_conn=opts["maxconn"], max_results=200, **win)
    # durée du trajet Max le plus rapide de toute la journée (même si on ne cherche qu'entre 10 h et 15 h) :
    # sert à écarter les détours absurdes, qui sinon s'afficheraient seuls dans une petite plage horaire
    day_paths = max_paths if win == {"min_dep": 0, "max_dep": 1440} else parcours.search(
        edges, origins, targets, max_conn=opts["maxconn"], max_results=200, min_dep=opts["min_dep"])
    day_fastest = min((p[-1]["arr"] - p[0]["dep"] for p in day_paths if not path_nocturnal(p)
                       and not ticket_price(path_tickets(p, origins, targets, o_near, t_near))), default=None)
    # trajets gratuits bien plus longs que le plus rapide du jour : écartés tout de suite (ils le seraient
    # plus bas de toute façon), avant de construire leur affichage
    if day_fastest:
        f = day_fastest
        max_paths = [p for p in max_paths if ticket_price(path_tickets(p, origins, targets, o_near, t_near))
                     or p[-1]["arr"] - p[0]["dep"] <= (max(2 * f, f + 720) if path_nocturnal(p) else max(2 * f, f + 240))]
    labels = set(origins)
    for p in max_paths:
        for e in p:
            labels.update((e["o"], e["d"]))

    # 2) compléments TER : gares atteignables en Max les plus proches de la destination
    ter_itins = []
    dest_geo = dest_place(dst, targets, stations) if opts["ter"] else None
    if dest_geo:
        best = parcours.reachable(edges, origins, max_conn=min(opts["maxconn"], 2), **win)
        tset = set(targets)
        frontier = [s for s in best if s not in tset]
        fgeo = geocode_many(frontier + list(origins))

        def km_to_dest(s):
            g = fgeo.get(s) or navitia._cache.get(s)
            return base.haversine_km(g["lat"], g["lon"], dest_geo["lat"], dest_geo["lon"]) if g else None

        o_km = min((k for k in map(km_to_dest, origins) if k is not None), default=None)
        ranked = []
        for s in frontier:
            km = km_to_dest(s)
            # une gare-relais doit rapprocher de la destination (sinon ce n'est qu'un détour)
            # pas d'aller-retour géographique : partir de Paris jusqu'à Avignon pour remonter à Lyon
            # en TER n'a aucun sens (détour limité à DETOUR_MAX fois la distance directe)
            if km is not None and o_km and detour_ratio(origins, s, fgeo, dest_geo, o_km) > config.DETOUR_MAX:
                continue
            if km is not None and km <= config.TER_MAX_DISTANCE_KM and (o_km is None or km < o_km):
                ranked.append((km, s))
        ranked.sort()

        # Pour les relais les plus proches, plusieurs arrivées dans la journée (pas seulement la 1re).
        jobs = []
        for rank, (km, s) in enumerate(ranked[:config.TER_CANDIDATES]):
            quota = config.TER_ARRIVALS_PER_RELAY[min(rank, len(config.TER_ARRIVALS_PER_RELAY) - 1)]
            paths = parcours.search(edges, origins, [s], max_conn=opts["maxconn"], max_results=40, **win)
            kept, last_arr = [], None
            # même arrivée au relais : la variante sans ticket (Marne-la-Vallée plutôt que Roissy à 14 €)
            for p in sorted(paths, key=lambda p: (p[-1]["arr"], path_tickets(p, origins, [s], o_near, {}),
                                                  -p[0]["dep"])):
                # pas de relais atteint en passant par la destination ou par un relais plus proche
                if any(e["d"] in tset or (km_to_dest(e["d"]) or 1e9) < km for e in p[:-1]):
                    continue
                if last_arr is None or p[-1]["arr"] - last_arr >= config.TER_ARRIVAL_SPACING_MIN:
                    kept.append(p)
                    last_arr = p[-1]["arr"]
                if len(kept) >= quota:
                    break
            jobs += [(s, fgeo[s], p) for p in kept]

        # Inutile de calculer un TER perdu d'avance : si un trajet 100 % Max (de jour) part au plus tôt
        # pareil et arrive avant même la gare-relais, le complément serait de toute façon écarté au tri.
        day_max = [(p[0]["dep"], p[-1]["arr"], len(p)) for p in max_paths if not path_nocturnal(p)]
        jobs = [j for j in jobs if not any(dep >= j[2][0]["dep"] and arr <= j[2][-1]["arr"] and n <= len(j[2]) + 1
                                           for dep, arr, n in day_max)]


        def tail(job):
            s, g, path = job
            ready = path[-1]["arr"] + gares.min_connection(s)       # minutes depuis le jour J (peut dépasser 1440)
            jdate = shift(date, ready // 1440)                      # après un train de nuit : le lendemain !
            # 1) horaires réels calculés en local (GTFS SNCF) : aucune requête à l'API
            local = gtfs.ready() and gtfs.covers(jdate) and gtfs.knows(g["id"]) and gtfs.knows(dest_geo["id"])
            jr = gtfs.journey(g["id"], dest_geo["id"], jdate, base.min_to_hhmm(ready)) if local else None
            if local and not tail_too_slow(jr, ready, g, dest_geo):
                return job, jr, ready, False
            # 2) en secours, l'API SNCF : elle connaît aussi les cars régionaux hors SNCF (ZOU!, etc.)
            #    absents du GTFS. Compté dans les budgets (global et par visiteur).
            if not IP_BUDGET.take(opts.get("ip", ""), 1):
                opts["ter_limited"] = jr is None
                return job, jr, ready, False
            qdate, estimated = ter_query_date(jdate)
            if not qdate:
                return job, jr, ready, False
            api = navitia.journey(g["id"], dest_geo["id"], qdate, base.min_to_hhmm(ready),
                                  max_transfers=opts["ter_transfers"])
            if api and (jr is None or tail_end(api, ready) < tail_end(jr, ready)):
                return job, api, ready, estimated
            return job, jr, ready, False

        for (s, g, path), jr, ready, estimated in IO_POOL.map(tail, jobs):
            if not jr or jr["duration_min"] > config.TER_MAX_TAIL_MIN:
                continue
            ter_itins.append((path, s, g, jr, ready, estimated))
            labels.update(e for leg in path for e in (leg["o"], leg["d"]))

    # 3) TER au départ : depuis une ville sans train Max (Annecy, Gap) ou pour attraper un train Max
    #    d'une grande gare proche (Saint-Étienne → Lyon Part-Dieu), en partant le plus tard possible
    # depuis une ville bien desservie (au moins 4 trajets Max ce jour-là), inutile de chercher plus loin
    day_trips = [p for p in max_paths if not path_nocturnal(p)]
    head_jobs = origin_ter_jobs(src, dst, date, edges, stations, origins, targets, opts, win,
                                bool(max_paths)) if opts["ter"] and len(day_trips) < 4 else []
    for _, path, _, _ in head_jobs:
        labels.update(e for leg in path for e in (leg["o"], leg["d"]))

    geo = geocode_many(list(labels))
    out = [dict(itinerary_from_path(p, date, geo)) for p in max_paths]
    out += [head_itinerary(job, date, geo, prefs) for job in head_jobs]

    homes = [geo[o] for o in origins if geo.get(o)]

    def back_home(g, jr):
        """Le TER repasse-t-il par la ville de départ (Toulouse → Montauban en TGV, puis TER par
        Toulouse jusqu'à Rodez) ? Alors un TER direct depuis le départ ferait mieux."""
        pts = [pt for x in jr["sections"] for pt in x.get("coords", ())]
        return any(base.haversine_km(h["lat"], h["lon"], g["lat"], g["lon"]) > 25
                   and any(base.haversine_km(h["lat"], h["lon"], la, lo) < 8 for la, lo in pts)
                   for h in homes)

    for path, s, g, jr, ready, estimated in ter_itins:
        if back_home(g, jr):
            continue
        legs = max_legs(path, date, geo)
        tickets = change_tickets(legs)                 # métro, Rhônexpress, billet aéroport…
        last_arr = path[-1]["arr"]
        tdep = base.hhmm_to_min(jr["departure"]) if jr.get("departure") else ready % 1440
        ter_dep = (ready // 1440) * 1440 + tdep
        if ter_dep < ready - 1:
            ter_dep += 1440
        ter_arr = ter_dep + jr["duration_min"]
        if jr.get("arrival"):          # l'heure affichée fait foi (la durée de l'API compte la marche)
            gap = (base.hhmm_to_min(jr["arrival"]) - tdep) % 1440
            ter_arr = ter_dep + gap + 1440 * ((jr["duration_min"] - gap + 60) // 1440)
        price = prix.estimate(jr["sections"], prefs)
        dest_name = nice_place(dest_geo["name"])
        legs.append({
            "free": False, "mode": " + ".join(dict.fromkeys(nice_mode(m) for m in jr["modes"])) or "TER",
            "networks": list(dict.fromkeys(jr["networks"])), "train": "",
            # gare réelle d'arrivée du train Max (« Lyon Part-Dieu » et non « Lyon »)
            "from": s, "to": dst, "from_name": legs[-1]["to_name"] if "(intramuros)" in s else display_name(s, g),
            "to_name": dest_name,
            "dep": jr["departure"], "arr": jr["arrival"],
            "dep_day": ter_dep // 1440, "arr_day": ter_arr // 1440,
            "duration_min": ter_arr - ter_dep, "transfers": jr["transfers"], "price": price,
            "estimated_schedule": estimated,
            "steps": [{"mode": nice_mode(x["mode"]), "from": nice_place(x["from"]), "to": nice_place(x["to"]),
                       "dep": x["dep"], "arr": x["arr"]} for x in jr["sections"]],
            "path": [pt for x in jr["sections"] for pt in x["coords"]],
            "from_lat": g["lat"], "from_lon": g["lon"],
            "to_lat": dest_geo["lat"], "to_lon": dest_geo["lon"],
            "book_url": booking_url(s, g, dest_geo["name"], dest_geo, shift(date, ter_dep // 1440),
                                    jr["departure"] or base.min_to_hhmm(ready)),
        })
        out.append({
            "_dep": path[0]["dep"], "_arr": ter_arr,
            "type": "max+ter", "paid": True, "cost_eur": price["price"], "_tickets": tickets, "nresa": len(path),
            "changes": len(path) + jr["transfers"],
            "departure": legs[0]["dep"], "arrival": jr["arrival"], "arrival_day": ter_arr // 1440,
            "duration_min": ter_arr - path[0]["dep"],
            "nocturnal": (path_nocturnal(path) or parcours.night_overlap(last_arr, ter_dep)
                          or parcours.night_overlap(ter_dep, ter_arr)),
            "estimated_schedule": estimated,
            "legs": legs,
        })

    # depuis / vers une gare annexe (Massy quand on a cherché « Paris ») ou voisine (Lorraine TGV pour
    # Metz) : comment y aller ; ce temps et ce prix comptent pour comparer les trajets entre eux
    for it in out:
        first, last = it["legs"][0], it["legs"][-1]
        for side, a in (("from", access(first["from"], origins, o_near)), ("to", access(last["to"], targets, t_near))):
            if not a:
                continue
            if side == "from":
                first["access_from"], it["_pre"] = f"Depuis {a[0]} : {a[1]}", a[2]
            else:
                last["access_to"], it["_post"] = f"Vers {a[0]} : {a[1]}", a[2]
            it["_tickets"] = round(it.get("_tickets", 0) + a[3], 2)
    # tickets en plus du Max (métro, Rhônexpress, billet aéroport, navettes) : au-delà de 5 € au total,
    # le trajet n'est plus « à 0 € » ; en dessous, ils sont indiqués dans le détail sans changer le prix
    for it in out:
        extra = ticket_price(it.pop("_tickets", 0))
        if extra:
            it["cost_eur"] = round(it["cost_eur"] + extra, 2)
            it["transfer_cost"] = extra
            it["paid"] = True
    # Trajets de jour : les meilleurs sans la nuit. Trajets de nuit : ceux qui restent intéressants
    # même face aux trajets de jour (sinon on ne propose pas une nuit en gare pour rien).
    # Détours absurdes : un trajet de jour bien plus long que le plus rapide du jour ne sert à rien.
    # De nuit, on tolère plus long (un train de nuit dure ~10 h), mais pas 20 h avec une nuit en gare.
    # Les trajets 100 % Max se comparent entre eux (comme le calendrier les compte) : un TER payant plus
    # rapide ne fait pas disparaître un trajet gratuit.
    def fastest_of(items):
        return min((it["duration_min"] for it in items if not it["nocturnal"]), default=None) \
            or min((it["duration_min"] for it in items), default=None)

    fast_all, fast_free = fastest_of(out), fastest_of([it for it in out if not it["paid"]])
    if day_fastest:
        fast_free = min(fast_free or day_fastest, day_fastest)
        fast_all = min(fast_all or day_fastest, day_fastest)
    # Max + TER payant alors qu'un trajet gratuit part à peine plus tôt (30 min) et arrive avant :
    # inutile (Paris → Nîmes puis TER retour vers Avignon, quand un Marne-la-Vallée → Avignon existe)
    free_day = [it for it in out if not it["paid"] and not it["nocturnal"]]
    # (temps d'accès compris : Saint-Exupéry 15:55 + Rhônexpress ne vaut pas mieux que Part-Dieu 15:04)
    span = lambda it: (it["_dep"] - it.get("_pre", 0), it["_arr"] + it.get("_post", 0))
    out = [it for it in out if not it["paid"] or not any(
        span(f)[0] >= span(it)[0] - 30 and span(f)[1] <= span(it)[1] for f in free_day)]

    def not_too_long(it):
        f = fast_all if it["paid"] else fast_free
        return not f or it["duration_min"] <= (max(2 * f, f + 720) if it["nocturnal"] else max(2 * f, f + 240))

    out = [it for it in out if not_too_long(it)]
    # Max + TER plus cher qu'un vrai billet direct (tarif officiel habituel) : sans intérêt
    fare = direct_fare(tuple(origins), tuple(targets))
    if fare:
        out = [it for it in out if not it["paid"] or it["cost_eur"] <= config.TER_MAX_SHARE_OF_FARE * fare]
    # trajets très détournés (Paris → Avignon → Lyon) : repliés sous « afficher plus » ; payants et
    # vraiment absurdes (Lille → Paris → Arras pour Amiens) : retirés
    # « détour » est relatif : Bordeaux → Paris → Lyon n'en est pas un si tous les trajets passent par
    # Paris ; repartir en arrière de plus de 100 km (Nantes → Paris → Poitiers → Strasbourg) en est un
    kept = []
    for it in out:
        r = path_detour(it["legs"])
        if r > (config.DETOUR_MAX_PAID if it["paid"] else config.DETOUR_ABSURD):
            continue
        it["_ratio"] = r
        kept.append(it)
    out = kept
    day = drop_dominated([it for it in out if not it["nocturnal"]])
    full = drop_dominated(out)
    night = [it for it in full if it["nocturnal"]]
    shown = full if opts["nights"] else day
    for it in out:
        for k in ("_dep", "_arr", "_pre", "_post"):
            it.pop(k, None)
    def unique(items):
        """Même départ, même arrivée, même prix : une seule ligne (la plus simple : moins de
        changements, puis le moins de détour). Évite trois variantes du même trajet à l'écran."""
        best = {}
        for it in items:
            k = (it["departure"], it["arrival"], it["arrival_day"], it["cost_eur"], it["legs"][0]["from_name"])
            moves = sum(1 for l in it["legs"] if l.get("change_note"))   # changement de gare évitable
            score = (len(it["legs"]), moves, path_detour(it["legs"]))
            if k not in best or score < best[k][0]:
                best[k] = (score, it)
        keep = {id(v[1]) for v in best.values()}
        return [it for it in items if id(it) in keep]
    shown, night = unique(shown), unique(night)
    # drapeau « détour », relatif aux trajets affichés ce jour-là
    best_ratio = min((it["_ratio"] for it in shown if not it["nocturnal"]), default=1.0)
    for it in out:
        r = it.pop("_ratio", 1.0)
        if (r > config.DETOUR_MAX and r > 1.25 * best_ratio) or backtracks(it["legs"]):
            it["detour"] = True
    order = lambda it: (it["paid"], it["departure"])
    res = {"itineraries": sorted(shown, key=order)}
    if not origins and not shown and not night:
        near = nearest_max(src)
        res["notice"] = (f"Pas de train Max au départ de « {src} », et aucun TER ou car ne rejoint à temps une "
                         f"gare Max proche{' (' + ', '.join(near) + ')' if near else ''} ce jour-là.")
    if not opts["nights"] and night:
        res["night_itineraries"] = sorted(night, key=order)
    if any(it.get("estimated_schedule") for it in shown + night):
        res["ter_notice"] = ter_estimated_notice()
    if opts.get("ter_limited"):
        res["ter_notice"] = ("Compléments TER en pause pour toi aujourd'hui : tu as fait beaucoup de recherches "
                             "avec TER. Les trains Max restent affichés ; réessaie demain.")
    if opts.get("ter_limited") or (opts["ter"] and (navitia.over_budget() or not gtfs.ready())):
        res["_nocache"] = True            # (horaires locaux pas encore chargés : réponse incomplète)
    if opts["ter"] and navitia.over_budget():
        res["ter_notice"] = ("Compléments TER indisponibles pour le reste de la journée : le site a atteint "
                             "sa limite quotidienne de requêtes à l'API SNCF. Les trains Max restent affichés.")
    return res


class IPBudget:
    """Requêtes à l'API SNCF consommées par visiteur et par jour (en plus du budget global)."""

    def __init__(self):
        self.day, self.used, self.lock = "", {}, threading.Lock()

    def take(self, ip, n):
        today = time.strftime("%Y-%m-%d")
        with self.lock:
            if today != self.day:
                self.day, self.used = today, {}
            if self.used.get(ip, 0) + n > config.NAVITIA_PER_IP_DAILY:
                return False
            self.used[ip] = self.used.get(ip, 0) + n
            return True


IP_BUDGET = IPBudget()


def do_search(qs):
    src, dst = _place(qs, "from"), _place(qs, "to")
    if not src or not dst:
        raise BadRequest("Indique une gare de départ et une gare d'arrivée.")
    fd = check_date(_p(qs, "from_date"))
    td = check_date(_p(qs, "to_date") or fd)
    if td < fd:
        fd, td = td, fd
    dates = list(base.daterange(fd, td))
    if len(dates) > config.MAX_RANGE_DAYS:
        raise BadRequest(f"Période trop longue : {config.MAX_RANGE_DAYS} jours maximum.")
    start_min, end_min = check_time(_p(qs, "start"), "de début"), check_time(_p(qs, "end"), "de fin")
    if fd == td and start_min is not None and end_min is not None and start_min > end_min:
        raise BadRequest("L'heure de début est après l'heure de fin.")
    known = set(donnees.all_stations())
    # départ inconnu, même ville : erreur tout de suite (départ sans train Max : possible avec le TER)
    _, _, all_targets, _ = od_areas(src, dst, known, no_origin_ok=_flag(qs, "ter", True))
    prefs = prix.prefs_from_qs(qs)
    common = {
        "prefs": prefs, "maxconn": _int(qs, "maxconn", 3, 0, 3),
        "ter": _flag(qs, "ter", True), "ter_transfers": 3, "ip": _p(qs, "_ip"),

        "nights": _flag(qs, "nights", False),
    }

    def one(day):
        opts = dict(common,
                    min_dep=max(past_min(day), start_min if (day == fd and start_min is not None) else 0),
                    max_dep=end_min if (day == td and end_min is not None) else 1440)
        try:
            r = search_one_day(src, dst, day, opts)
        except BadRequest as e:
            r = {"itineraries": [], "error": str(e)}
        except Exception:
            traceback.print_exc()
            r = {"itineraries": [], "error": "Données indisponibles pour ce jour, réessaie plus tard."}
        return dict(r, date=day, weekday=base.weekday(day))

    days = list(DAY_POOL.map(one, dates)) if len(dates) > 1 else [one(dates[0])]
    nocache = any([d.pop("_nocache", False) for d in days])

    dest_geo = dest_place(dst, all_targets, known)     # centre de la carte : la gare Max d'arrivée
    return {
        "mode": "search", "from": src, "to": dst, "prefs": prefs, "days": days,
        "to_coord": dest_geo and {"lat": dest_geo["lat"], "lon": dest_geo["lon"],
                                  "name": nice_place(dest_geo["name"])},
        "_nocache": nocache,
    }

"""/api/calendar (trains à 0 € par jour), /api/trends (historique) et /api/ideas (idées du jour)."""

from maxplan import base
from maxplan import historique
from maxplan.moteur import donnees
from maxplan.moteur import gares
from maxplan.moteur import parcours
from maxplan.ter import prix
from maxplan.api.commun import (
    BadRequest, _flag, _int, _p, _place, check_date, coming_dates, past_min, senior_weekend,
)
from maxplan.api.recherche import search_one_day
from maxplan.api.trajets import DAY_POOL, edges_for, max_trips, od_areas, ter_coverage


def do_trends(qs):
    """Tendances d'une liaison d'après l'historique des places Max (statistiques)."""
    src, dst = _place(qs, "from"), _place(qs, "to")
    if not src or not dst:
        raise BadRequest("Indique une gare de départ et une gare d'arrivée.")
    known = set(donnees.all_stations())
    return historique.od_trends(gares.resolve_city(src, known), gares.resolve_city(dst, known))


def do_calprices(qs):
    """/api/calprices?from&to&dates=AAAA-MM-JJ,… (5 jours au plus) : pour des jours sans train à 0 €, le
    prix le plus bas avec un TER ou un car. L'interface les demande par petits lots, une fois le
    calendrier affiché, et remplit les cases au fur et à mesure."""
    src, dst = _place(qs, "from"), _place(qs, "to")
    if not src or not dst:
        raise BadRequest("Indique une gare de départ et une gare d'arrivée.")
    dates = [check_date(d) for d in _p(qs, "dates").split(",") if d][:5]
    prefs = prix.prefs_from_qs(qs)
    return calendar_prices(src, dst, prefs, _int(qs, "maxconn", 3, 0, 3), qs, dates)


def calendar_prices(src, dst, prefs, maxconn, qs, dates=None):
    """Les jours sans train à 0 € : le prix le plus bas avec un TER ou un car (au départ ou à l'arrivée),
    tel que la recherche le trouve (horaires locaux seulement, sans appel à l'API SNCF, recherche
    allégée : le prix le plus bas suffit, pas toutes les variantes)."""
    def one(date):
        if senior_weekend(prefs, date):
            return None
        opts = {"prefs": prefs, "maxconn": maxconn, "ter": True, "ter_transfers": 3, "nights": False,
                "ip": _p(qs, "_ip"), "local_only": True, "light": True, "min_dep": past_min(date), "max_dep": 1440}
        try:
            its = search_one_day(src, dst, date, opts)["itineraries"]
        except Exception:
            return None
        if not its or any(not it["paid"] for it in its):     # jour à 0 € ou sans rien : case inchangée
            return {"date": date, "n": 0}
        return {"date": date, "n": len(its), "price": min(it["cost_eur"] for it in its)}

    return {"from": src, "to": dst, "days": list(DAY_POOL.map(one, dates or coming_dates()))}


def do_calendar(qs):
    """Nombre de trajets 100 % Max (sans TER) pour chaque jour de l'open data : le calendrier du mois."""
    src, dst = _place(qs, "from"), _place(qs, "to")
    if not src or not dst:
        raise BadRequest("Indique une gare de départ et une gare d'arrivée.")
    prefs = prix.prefs_from_qs(qs)
    maxconn, nights = _int(qs, "maxconn", 3, 0, 3), _flag(qs, "nights", False)
    # départ inconnu, même ville : erreur claire (départ sans train Max : jours à 0 vides, prix avec TER)
    od_areas(src, dst, set(donnees.all_stations()), no_origin_ok=True)

    def one(date):
        if senior_weekend(prefs, date):
            return {"date": date, "n": 0, "blocked": True}
        try:
            edges = edges_for(date)
        except Exception:
            return {"date": date, "n": None}
        stations = {e["o"] for e in edges} | {e["d"] for e in edges}
        try:
            o, o_near, t, t_near = od_areas(src, dst, stations, no_origin_ok=True)
        except BadRequest:
            return {"date": date, "n": 0}
        if not o:
            return {"date": date, "n": 0}
        paths = parcours.search(edges, o, t, max_conn=maxconn, max_results=200, min_dep=past_min(date))
        its = max_trips(paths, o, t, o_near, t_near, nights=nights)   # comme la recherche les affiche
        if not its:
            return {"date": date, "n": 0}
        return {"date": date, "n": len(its), "direct": any(len(x["legs"]) == 1 for x in its),
                "first": base.min_to_hhmm(min(x["_dep"] for x in its)),
                "best_min": min(x["_arr"] - x["_dep"] for x in its)}

    return {"from": src, "to": dst, "days": list(DAY_POOL.map(one, coming_dates())),
            "ter_coverage": ter_coverage()}


# Idées de l'accueil : grandes liaisons, gardées seulement si des trains à 0 € existent vraiment ce jour-là.
IDEA_CITIES = {"paris": "Paris", "lyon": "Lyon", "marseille": "Marseille", "bordeaux": "Bordeaux",
               "toulouse": "Toulouse", "lille": "Lille", "nantes": "Nantes", "strasbourg": "Strasbourg",
               "montpellier": "Montpellier", "nice": "Nice", "rennes": "Rennes", "grenoble": "Grenoble",
               "avignon": "Avignon", "annecy": "Annecy", "la rochelle": "La Rochelle", "dijon": "Dijon"}
IDEA_PAIRS = [("paris", "lyon"), ("paris", "marseille"), ("paris", "bordeaux"), ("paris", "toulouse"),
              ("paris", "nantes"), ("paris", "strasbourg"), ("paris", "montpellier"), ("paris", "nice"),
              ("paris", "rennes"), ("paris", "lille"), ("paris", "annecy"), ("paris", "la rochelle"),
              ("lyon", "marseille"), ("lyon", "montpellier"), ("lyon", "lille"), ("lyon", "strasbourg"),
              ("lille", "marseille"), ("lille", "bordeaux"), ("bordeaux", "toulouse"), ("marseille", "nice"),
              ("nantes", "lyon"), ("strasbourg", "marseille"), ("rennes", "lyon"), ("paris", "grenoble")]


def do_ideas(qs):
    date = check_date(_p(qs, "date"))
    prefs = prix.prefs_from_qs(qs)
    if senior_weekend(prefs, date):
        return {"date": date, "ideas": []}
    edges = edges_for(date)
    stations = {e["o"] for e in edges} | {e["d"] for e in edges}
    pairs = list(IDEA_PAIRS)
    origin = base.normalize(_p(qs, "from"))
    if origin in IDEA_CITIES:        # d'abord des idées au départ de la ville de l'utilisateur
        pairs = [(origin, c) for c in IDEA_CITIES if c != origin] + pairs
    ideas, seen = [], set()
    for o, d in pairs:
        if (o, d) in seen:
            continue
        seen.add((o, d))
        (oo, o_near), (tt, t_near) = gares.resolve_area(o, stations), gares.resolve_area(d, stations)
        its = max_trips(parcours.search(edges, oo, tt, max_conn=1, max_results=200), oo, tt, o_near, t_near)
        if its:
            ideas.append({"from": o, "to": d, "from_name": IDEA_CITIES[o], "to_name": IDEA_CITIES[d],
                          "n": len(its), "direct": any(len(x["legs"]) == 1 for x in its),
                          "first": base.min_to_hhmm(min(x["_dep"] for x in its)),
                          "fastest": min(x["_arr"] - x["_dep"] for x in its)})
        if len(ideas) >= 6:
            break
    return {"date": date, "ideas": ideas}

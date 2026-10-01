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
from maxplan.api.trajets import DAY_POOL, edges_for, max_trips, od_areas, ter_coverage


def do_trends(qs):
    """Tendances d'une liaison d'après l'historique des places Max (statistiques)."""
    src, dst = _place(qs, "from"), _place(qs, "to")
    if not src or not dst:
        raise BadRequest("Indique une gare de départ et une gare d'arrivée.")
    known = set(donnees.all_stations())
    return historique.od_trends(gares.resolve_city(src, known), gares.resolve_city(dst, known))


def do_calendar(qs):
    """Nombre de trajets 100 % Max (sans TER) pour chaque jour de l'open data : le calendrier du mois."""
    src, dst = _place(qs, "from"), _place(qs, "to")
    if not src or not dst:
        raise BadRequest("Indique une gare de départ et une gare d'arrivée.")
    prefs = prix.prefs_from_qs(qs)
    maxconn, nights = _int(qs, "maxconn", 3, 0, 3), _flag(qs, "nights", False)
    od_areas(src, dst, set(donnees.all_stations()))   # départ inconnu, même ville : erreur claire

    def one(date):
        if senior_weekend(prefs, date):
            return {"date": date, "n": 0, "blocked": True}
        try:
            edges = edges_for(date)
        except Exception:
            return {"date": date, "n": None}
        stations = {e["o"] for e in edges} | {e["d"] for e in edges}
        try:
            o, o_near, t, t_near = od_areas(src, dst, stations)
        except BadRequest:
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

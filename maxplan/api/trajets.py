"""Mise en forme et tri des trajets : tronçons Max, noms de gares, liens SNCF Connect, trajets
dominés, détours, places Max du jour (cache) et géocodage."""

import re
import threading
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from maxplan import base
from maxplan import config
from maxplan.moteur import donnees
from maxplan.moteur import gares
from maxplan.moteur import parcours
from maxplan.ter import gtfs
from maxplan.ter import tarifs
from maxplan.ter.navitia import navitia
from maxplan.api.commun import BadRequest, shift


IO_POOL = ThreadPoolExecutor(max_workers=16)   # géocodage + calculs TER
DAY_POOL = ThreadPoolExecutor(max_workers=4)   # plusieurs jours d'une même recherche


# ======================================================================= places Max du jour et géocodage
_EDGES = {}
_EDGE_LOCKS = defaultdict(threading.Lock)


def edges_for(date):
    """Segments Max du jour, mis en cache quelques heures (l'open data change 1×/jour)."""
    hit = _EDGES.get(date)
    if hit and time.time() - hit[0] < config.EDGES_TTL:
        return hit[1]
    with _EDGE_LOCKS[date]:  # une seule récupération même si plusieurs visiteurs arrivent ensemble
        hit = _EDGES.get(date)
        if hit and time.time() - hit[0] < config.EDGES_TTL:
            return hit[1]
        edges = donnees.fetch_oui_edges(date)
        now = time.time()
        _EDGES[date] = (now, edges)
        for d, (t, _) in list(_EDGES.items()):
            if now - t > 2 * config.EDGES_TTL:
                _EDGES.pop(d, None)
        return edges


def geocode_many(labels):
    labels = [l for l in dict.fromkeys(labels) if l]
    return dict(zip(labels, IO_POOL.map(navitia.geocode, labels))) if labels else {}


# ======================================================================= noms affichés
_SMALL = {"de", "du", "des", "la", "le", "les", "sur", "sous", "en", "et", "aux", "au"}


def nice_place(name):
    """« Lyon Part Dieu (Lyon) » -> « Lyon Part Dieu »."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", name or "").strip()


def pretty(label):
    s = label.replace("(intramuros)", "").strip().rstrip(".")
    out = []
    for i, w in enumerate(s.split()):
        lw = w.lower()
        if w in ("TGV", "TER", "CDG", "SNCF", "HBF"):
            out.append(w)
        elif lw == "st":
            out.append("Saint")
        elif lw == "ste":
            out.append("Sainte")
        elif i and lw in _SMALL:
            out.append(lw)
        else:
            out.append(lw.capitalize())
    return " ".join(out)


_MODES = {"REGIONAURA": "TER", "TER NA": "TER", "TER": "TER", "LEX": "Léman Express", "NOMAD": "Nomad",
          "LIO": "liO", "ALÉOP": "Aléop", "ALEOP": "Aléop", "RÉMI": "Rémi", "REMI": "Rémi", "FLUO": "Fluo",
          "MOBIGO": "Mobigo", "BREIZHGO": "BreizhGo", "ZOU !": "ZOU !", "TGV INOUI": "TGV INOUI",
          "INTERCITÉS": "Intercités", "INTERCITES": "Intercités", "OUIGO": "OUIGO", "CAR": "Car",
          "AUTOCAR": "Car", "BUS": "Bus", "TRAMWAY": "Tram", "TRANSILIEN": "Transilien", "RER": "RER"}


def nice_mode(mode):
    """Codes réseau Navitia -> libellé lisible (« REGIONAURA » -> « TER »)."""
    m = (mode or "").strip()
    return _MODES.get(m.upper(), "TER" if m.isupper() and len(m) > 4 else m or "Train")


def display_name(label, geo=None):
    if "(intramuros)" in label:
        return pretty(label)            # « PARIS (intramuros) » -> « Paris » (toutes gares)
    if geo and geo.get("name"):
        return nice_place(geo["name"])  # nom Navitia, accentué
    return pretty(label)


_MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
         "septembre", "octobre", "novembre", "décembre")


def booking_url(o_label, o_geo, d_label, d_geo, date, hhmm):
    """SNCF Connect comprend une phrase libre (`userInput`) : « Lyon Part-Dieu Marseille Saint-Charles
    le 1 octobre à 07h04 » ouvre directement la liste des trains de ce jour à partir de cette heure.
    Le chemin /app/ est déclaré en lien universel : sur téléphone, l'appli SNCF Connect s'ouvre."""
    y, m, d = (int(x) for x in date.split("-"))
    text = (f"{display_name(o_label, o_geo)} {display_name(d_label, d_geo)} "
            f"le {d} {_MOIS[m - 1]} à {hhmm.replace(':', 'h')}")
    return "https://www.sncf-connect.com/app/home/search?" + urllib.parse.urlencode({"userInput": text})


# ======================================================================= itinéraires
def train_mode(axe):
    """Axe open data -> type de train (« IC ARO », « IC SRO » : Intercités ; « IC NUIT » : de nuit)."""
    axe = (axe or "").upper()
    if axe == "IC NUIT":
        return "Intercités de nuit"
    if axe.startswith("IC"):
        return "Intercités"
    if axe.startswith("AUTOCAR"):
        return "Car SNCF"
    return "TGV INOUI"


# noms des horaires SNCF -> noms courts affichés (et utilisés pour décrire les changements de gare)
GTFS_NAMES = {"Paris Gare de Lyon Hall 1 - 2": "Paris Gare de Lyon", "Paris Montparnasse Hall 1 - 2": "Paris Montparnasse",
              "Paris Bercy Bourg. Pays d'Auv.": "Paris Bercy", "Paris Gare du Nord": "Paris Nord",
              "Lyon Part Dieu": "Lyon Part-Dieu"}


def real_station(label, edge, date, when):
    """Vraie gare d'un libellé « intramuros » (Paris, Lyon, Lille) pour ce train : d'abord les horaires
    SNCF (on sait si le TGV part de Lyon Part-Dieu ou de Perrache), sinon l'axe du train (Paris)."""
    if "(intramuros)" not in label:
        return None
    minute = edge["dep"] if when == "dep" else edge["arr"]
    st = gtfs.train_stop(edge["train"], date, minute, when) if gtfs.ready() else None
    if st:
        name = nice_place(st["name"])
        return dict(st, name=GTFS_NAMES.get(name, name))
    s = gares.city_station(label, edge)
    if s:
        la, lo = gares.PARIS_COORDS[s]
        return {"name": s, "lat": la, "lon": lo}
    return None


def max_leg(edge, date, geo):
    o, d = edge["o"], edge["d"]
    og, dg = geo.get(o), geo.get(d)
    # vraie gare (Lyon Part-Dieu ou Perrache, Paris Gare de Lyon ou Bercy…) quand l'open data dit « intramuros »
    ro, rd = real_station(o, edge, date, "dep"), real_station(d, edge, date, "arr")
    so, sd = ro and ro["name"], rd and rd["name"]
    og, dg = ro or og, rd or dg
    dep = base.min_to_hhmm(edge["dep"])
    return {
        "free": True, "mode": train_mode(edge.get("axe", "")),
        "train": edge["train"], "axe": edge.get("axe", ""),
        "entity": edge.get("entity", ""),
        "from": o, "to": d, "from_name": so or display_name(o, og), "to_name": sd or display_name(d, dg),
        "dep": dep, "arr": base.min_to_hhmm(edge["arr"]),
        "dep_day": edge["dep"] // 1440, "arr_day": edge["arr"] // 1440,
        "from_lat": og and og["lat"], "from_lon": og and og["lon"],
        "to_lat": dg and dg["lat"], "to_lon": dg and dg["lon"],
        "book_url": booking_url(so or o, None if so else og, sd or d, None if sd else dg,
                                shift(date, edge["dep"] // 1440), dep),

    }


def path_nocturnal(path):
    """Un trajet touche-t-il la nuit (train ou attente de correspondance ~23 h–6 h) ?"""
    if any(parcours.night_overlap(e["dep"], e["arr"]) for e in path):
        return True
    return any(parcours.night_overlap(a["arr"], b["dep"]) for a, b in zip(path, path[1:]))


def dest_place(dst, targets, stations):
    """Lieu d'arrivée pour le calcul TER. Si l'arrivée est une gare Max (« Lyon » -> LYON (intramuros)),
    on géocode ce libellé (surcharges comprises) plutôt que le texte libre, que l'API SNCF peut
    confondre (« Lyon » -> « Paris - Gare de Lyon »)."""
    for t in targets:
        if t in stations:
            g = navitia.geocode(t)
            if g:
                return g
    return free_place(dst)


def free_place(label):
    """Lieu saisi librement (village, gare hors réseau Max) : d'abord dans les horaires GTFS
    (aucune requête à l'API SNCF), sinon géocodage par l'API."""
    if gtfs.ready():
        hits = gtfs.places(nice_place(label), limit=1)
        # un simple arrêt de bus dont le nom contient le mot (« Lycée A. Londres » pour « Londres ») ne
        # vaut pas une ville : on demande à l'API, et on ne garde l'arrêt qu'en dernier recours
        if hits and (hits[0].get("rail") or gtfs.fold(hits[0]["name"]).startswith(gtfs.fold(nice_place(label)))):
            return hits[0]
        return navitia.geocode(label) or (hits[0] if hits else None)
    return navitia.geocode(label)


def ter_coverage():
    return gtfs.coverage() or navitia.coverage()


def _access_min(station):
    """Minutes pour rejoindre une gare annexe depuis le centre (Massy, Marne-la-Vallée…), 0 sinon."""
    a = gares.ANNEX.get(station)
    m = a and re.search(r"environ (\d+) min", a[2])
    return int(m.group(1)) if m else (30 if a else 0)


def note_cost(note):
    """Prix annoncé pour rejoindre une gare (« ticket 2,50 € », « ≈ 17 € »), 0 si rien."""
    m = re.search(r"(\d+(?:,\d+)?) €", note or "")
    return float(m.group(1).replace(",", ".")) if m else 0.0


def access(station, ends, near):
    """Rejoindre une gare annexe (Massy quand on a cherché « Paris ») ou voisine (Lorraine TGV pour
    Metz) : (ville, comment y aller, minutes, prix), ou None si c'est une gare de la ville cherchée."""
    a = gares.ANNEX.get(station)
    if a and a[0] in ends and a[0] not in near:
        return a[1], a[2], _access_min(station), note_cost(a[2])
    if station in near:
        s0, mins, note = near[station]
        return display_name(s0, navitia._cache.get(s0)), note, gares.note_minutes(note, mins), note_cost(note)
    return None


def drop_dominated(itins):
    """Retire un trajet quand un autre part au plus tôt pareil, arrive au plus tard pareil et coûte au plus
    autant (ex. Max + TER payant alors qu'un TGV Max direct part après et arrive avant).
    Une gare annexe compte son temps et son prix d'accès : un train depuis Massy ne cache pas celui de
    Montparnasse parti 10 min plus tôt, ni un départ de Saint-Exupéry (Rhônexpress ≈ 17 €) celui de
    Marne-la-Vallée. Une nuit en gare ne se justifie pas pour quelques centimes d'économie."""
    def ends(it):
        return it["_dep"] - it.get("_pre", 0), it["_arr"] + it.get("_post", 0)

    span = [ends(it) for it in itins]
    cost = [it["cost_eur"] + it.get("_acc_cost", 0) for it in itins]
    first = [(it["legs"][0].get("from") or it["legs"][0].get("o")) for it in itins]

    def beats(j, i):
        y, x = itins[j], itins[i]
        (yd, ya), (xd, xa) = span[j], span[i]
        tol = 2 if x.get("nocturnal") and not y.get("nocturnal") else 0
        no_worse = yd >= xd and ya <= xa and cost[j] <= cost[i] + tol and len(y["legs"]) <= len(x["legs"])
        better = yd > xd or ya < xa or cost[j] < cost[i] or len(y["legs"]) < len(x["legs"]) or bool(tol)
        return no_worse and better

    # même voyage en double : mêmes heures, même prix, même gare de départ (un train qui dessert deux
    # gares de la même ville, Part-Dieu puis Perrache, toutes deux « LYON (intramuros) », ou un train
    # à deux numéros) : on n'en garde qu'un, comme la recherche
    # à doublon égal, on garde la variante sans changement de gare (Part-Dieu → Part-Dieu plutôt que
    # Part-Dieu → Perrache pour le même train)
    moves = [sum(1 for l in it["legs"] if l.get("change_note")) for it in itins]

    def same(j, i):
        return span[j] == span[i] and cost[j] == cost[i] and first[j] == first[i]             and len(itins[j]["legs"]) == len(itins[i]["legs"]) and (moves[j], j) < (moves[i], i)

    n = len(itins)
    return [x for i, x in enumerate(itins)
            if not any(beats(j, i) or same(j, i) for j in range(n) if j != i)]


def od_areas(src, dst, stations):
    """Gares de départ et d'arrivée (avec leurs gares voisines). Les voisines ajoutées d'un côté ne
    doivent pas être des gares de l'autre (Massy → Paris : Paris n'est pas une « voisine » de départ).
    Si départ et arrivée se recoupent quand même, c'est la même ville : pas de trajet en train Max."""
    (o, o_near), (t, t_near) = gares.resolve_area(src, stations), gares.resolve_area(dst, stations)
    if not any(s in known for s in o for known in (stations, set(donnees.all_stations()))):
        raise BadRequest(f"Aucune gare Max ne correspond à « {src} » au départ : choisis une gare dans la liste.")
    shared = set(o_near) & set(t_near)            # Metz → Nancy : Lorraine TGV n'est ni l'un ni l'autre
    o = [s for s in o if s not in shared]
    t = [s for s in t if s not in shared]
    o_near = {k: v for k, v in o_near.items() if k not in shared}
    t_near = {k: v for k, v in t_near.items() if k not in shared}
    o_base, t_base = [s for s in o if s not in o_near], [s for s in t if s not in t_near]
    o = [s for s in o if s not in t_base]
    o_near = {k: v for k, v in o_near.items() if k not in t_base}
    t = [s for s in t if s not in o_base]
    t_near = {k: v for k, v in t_near.items() if k not in o_base}
    if not o or not t or set(o) & set(t):
        raise BadRequest("Le départ et l'arrivée sont dans la même ville (ou deux gares voisines) : "
                         "pas de trajet en train Max entre elles.")
    return o, o_near, t, t_near


def path_ratio(path):
    """Distance parcourue / distance à vol d'oiseau d'un trajet Max (gares géocodées en cache)."""
    pts = [navitia._cache.get(path[0]["o"])] + [navitia._cache.get(e["d"]) for e in path]
    if len(pts) < 3 or not all(pts):
        return 1.0
    run = sum(base.haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in zip(pts, pts[1:]))
    return run / max(1.0, base.haversine_km(pts[0]["lat"], pts[0]["lon"], pts[-1]["lat"], pts[-1]["lon"]))


def max_trips(paths, origins, targets, o_near=None, t_near=None, nights=False):
    """Trajets 100 % Max d'un jour, filtrés exactement comme la recherche les affiche (sans TER) :
    pas de nuit (sauf demandée), pas de trajet bien plus long que le plus rapide ni de détour absurde,
    pas de trajet dominé ni de doublon. Sert au calendrier, à « Rentable ? » et aux idées du jour, pour
    qu'ils comptent ce que la recherche montre."""
    its = []
    for p in paths:
        if path_ratio(p) > config.DETOUR_ABSURD:
            continue
        extra = round(sum(c for c in (note_cost(gares.twin_note(a["d"], b["o"], a, b)) for a, b in zip(p, p[1:])
                                      if a["d"] != b["o"]) if c >= config.TRANSFER_PAID_MIN), 2)
        it = {"_dep": p[0]["dep"], "_arr": p[-1]["arr"], "cost_eur": extra, "legs": p,
              "nocturnal": path_nocturnal(p)}
        for k, a in (("_pre", access(p[0]["o"], origins, o_near or {})), ("_post", access(p[-1]["d"], targets, t_near or {}))):
            if a:
                it[k] = a[2]
                if a[3] >= config.TRANSFER_PAID_MIN:       # comme la recherche : ce trajet n'est pas à 0 €
                    it["cost_eur"] = round(it["cost_eur"] + a[3], 2)
                else:
                    it["_acc_cost"] = it.get("_acc_cost", 0) + a[3]
        its.append(it)
    dur = lambda x: x["_arr"] - x["_dep"]
    free = [x for x in its if not x["cost_eur"]]        # comme la recherche : le plus rapide des gratuits
    fastest = min((dur(x) for x in free if not x["nocturnal"]), default=None) or min(map(dur, free), default=None)
    if fastest:
        its = [x for x in its if dur(x) <= (max(2 * fastest, fastest + 720) if x["nocturnal"]
                                            else max(2 * fastest, fastest + 240))]
    kept = drop_dominated(its if nights else [x for x in its if not x["nocturnal"]])
    return [x for x in kept if not x["cost_eur"]]      # « trains à 0 € » : sans changement payant


def detour_ratio(origins, relay, fgeo, dest, direct_km):
    """(départ → relais + relais → destination) / (départ → destination), au mieux parmi les gares de départ."""
    g = fgeo.get(relay) or navitia._cache.get(relay)
    if not g:
        return 0
    best = None
    for o in origins:
        og = fgeo.get(o) or navitia._cache.get(o)
        if og:
            via = base.haversine_km(og["lat"], og["lon"], g["lat"], g["lon"]) + \
                base.haversine_km(g["lat"], g["lon"], dest["lat"], dest["lon"])
            r = via / max(1.0, base.haversine_km(og["lat"], og["lon"], dest["lat"], dest["lon"]))
            best = r if best is None else min(best, r)
    return best or 0


def path_detour(legs):
    """Distance parcourue / distance à vol d'oiseau entre le départ et l'arrivée d'un trajet."""
    pts = [(l.get("from_lat"), l.get("from_lon")) for l in legs] + [(legs[-1].get("to_lat"), legs[-1].get("to_lon"))]
    pts = [p for p in pts if p[0] is not None]
    if len(pts) < 3:
        return 1.0
    run = sum(base.haversine_km(*a, *b) for a, b in zip(pts, pts[1:]))
    return run / max(1.0, base.haversine_km(*pts[0], *pts[-1]))


_FARES = {}


def direct_fare(origins, targets):
    """Prix habituel (milieu de fourchette, tarif Avantage) d'un billet direct entre deux villes."""
    if (origins, targets) not in _FARES:
        try:
            p = tarifs.price_range(list(origins), list(targets))
            _FARES[(origins, targets)] = p and p["avantage"]["typical"]
        except Exception:
            return None
    return _FARES[(origins, targets)]


def max_legs(path, date, geo):
    """Tronçons Max d'un trajet ; quand on change de gare jumelle (Massy → Marne-la-Vallée…),
    le tronçon suivant dit comment faire."""
    legs = [max_leg(e, date, geo) for e in path]
    for prev, e, pleg, leg in zip(path, path[1:], legs, legs[1:]):
        if e["o"] != prev["d"]:
            note = gares.twin_note(prev["d"], e["o"], prev, e)
            if note and pleg["to_name"] == "Lyon Perrache" and "Part-Dieu" in note:
                note = "tram T1 ou métro jusqu'à Lyon Part-Dieu, puis " + note
        elif pretty(e["o"]) not in (pleg["to_name"], leg["from_name"]):
            # même libellé, autre gare réelle (TGV arrivé à Part-Dieu, suivant au départ de Perrache) ;
            # si l'une des deux gares est inconnue (« Lyon »), on ne devine pas
            note = gares.city_change_note(pleg["to_name"], leg["from_name"])
        else:
            note = None
        if note:
            leg["change_note"] = note
            leg["change_cost"] = note_cost(note)
    return legs


def transfer_cost(legs):
    """Changements de gare vraiment payants dans un trajet (Rhônexpress ≈ 17 €, billet aéroport ≈ 14 €) :
    le trajet n'est alors plus « à 0 € ». Les petits tickets (métro, navette à 2-3 €) sont signalés
    dans le détail sans changer le prix affiché."""
    return round(sum(c for c in (l.get("change_cost", 0) for l in legs) if c >= config.TRANSFER_PAID_MIN), 2)


def itinerary_from_path(path, date, geo):

    legs = max_legs(path, date, geo)
    extra = transfer_cost(legs)
    return {
        "_dep": path[0]["dep"], "_arr": path[-1]["arr"],
        "type": "max", "paid": extra > 0, "cost_eur": extra, "transfer_cost": extra,
        "nresa": len(legs), "changes": len(legs) - 1,
        "departure": legs[0]["dep"], "arrival": legs[-1]["arr"],
        "arrival_day": path[-1]["arr"] // 1440,
        "duration_min": path[-1]["arr"] - path[0]["dep"],
        "nocturnal": path_nocturnal(path), "legs": legs,
    }


def tail_end(jr, ready):
    """Minutes entre la fin du train Max (+ correspondance) et l'arrivée du TER."""
    wait = (base.hhmm_to_min(jr["departure"]) - ready % 1440) % 1440
    return wait + jr["duration_min"]

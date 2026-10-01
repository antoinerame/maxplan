"""Gares : villes à plusieurs gares, gares annexes et jumelles, gares parisiennes réelles,
temps de correspondance et gares voisines ajoutées à une recherche."""

import re

from maxplan import config
from maxplan.base import normalize


# Villes multi-gares regroupées sous "<VILLE> (intramuros)" dans le dataset.
CITY_ALIASES = {
    "paris": ["PARIS (intramuros)", "MARNE LA VALLEE CHESSY", "MASSY TGV", "MASSY PALAISEAU",
              "AEROPORT ROISSY CDG 2 TGV", "VERSAILLES CHANTIERS"],
    "lyon": ["LYON (intramuros)", "LYON ST EXUPERY TGV."],
    "marseille": ["MARSEILLE ST CHARLES", "MARSEILLE BLANCARDE"],
    "lille": ["LILLE (intramuros)"],
    "avignon": ["AVIGNON TGV", "AVIGNON CENTRE"],
    "aix": ["AIX EN PROVENCE TGV"],
    "aix-en-provence": ["AIX EN PROVENCE TGV"],
    "bourg-en-bresse": ["BOURG EN BRESSE"],
    "bordeaux": ["BORDEAUX ST JEAN"],
    "nantes": ["NANTES"],
    "rennes": ["RENNES"],
    "strasbourg": ["STRASBOURG"],
    "montpellier": ["MONTPELLIER SAINT ROCH", "MONTPELLIER SUD DE FRANCE"],
    "nimes": ["NIMES CENTRE", "NIMES PONT DU GARD"],
    "valence": ["VALENCE VILLE", "VALENCE TGV AUVERGNE RHONE ALPES"],
    "besancon": ["BESANCON VIOTTE", "BESANCON FRANCHE COMTE TGV"],
    "reims": ["REIMS", "CHAMPAGNE ARDENNE TGV"],
    "nice": ["NICE VILLE"],
    "toulouse": ["TOULOUSE MATABIAU"],
    "grenoble": ["GRENOBLE"],
}


# Gares annexes proposées quand on cherche la ville (gare principale, ville, comment y aller)
ANNEX = {
    "MARNE LA VALLEE CHESSY": ("PARIS (intramuros)", "Paris", "RER A, environ 40 min depuis Châtelet, ticket 2,50 €"),
    "MASSY TGV": ("PARIS (intramuros)", "Paris", "RER B ou C, environ 30 min, ticket 2,50 €"),
    "MASSY PALAISEAU": ("PARIS (intramuros)", "Paris", "RER B ou C, environ 30 min, ticket 2,50 €"),
    "AEROPORT ROISSY CDG 2 TGV": ("PARIS (intramuros)", "Paris", "RER B, environ 35 min depuis Gare du Nord, billet aéroport ≈ 13 €"),
    "VERSAILLES CHANTIERS": ("PARIS (intramuros)", "Paris", "train ou RER C, environ 20 min depuis Montparnasse, ticket 2,50 €"),
    "LYON ST EXUPERY TGV.": ("LYON (intramuros)", "Lyon", "tram Rhônexpress depuis Part-Dieu, environ 30 min, ≈ 17 €"),
    "AVIGNON TGV": ("AVIGNON CENTRE", "Avignon centre", "navette TER, environ 5 min"),
    "NIMES PONT DU GARD": ("NIMES CENTRE", "Nîmes centre", "navette ou TER, environ 15 min"),
    "MONTPELLIER SUD DE FRANCE": ("MONTPELLIER SAINT ROCH", "Montpellier centre", "navette ou tram, environ 20 min"),
    "VALENCE TGV AUVERGNE RHONE ALPES": ("VALENCE VILLE", "Valence centre", "TER, environ 10 min"),
    "CHAMPAGNE ARDENNE TGV": ("REIMS", "Reims centre", "TER ou tram, environ 10 min"),
    "BESANCON FRANCHE COMTE TGV": ("BESANCON VIOTTE", "Besançon centre", "TER, environ 15 min"),
}
IDF_ACCESS = {k: v[2] for k, v in ANNEX.items() if v[0] == "PARIS (intramuros)"}
MAIN_STATION_KEY = {"PARIS (intramuros)": "paris", "LYON (intramuros)": "lyon"}


# Gares jumelles : on peut arriver à l'une et repartir de l'autre (minutes de changement, marge
# comprise, et comment faire). Paris intra-muros : voir transfer_min (gares déduites de l'axe).
_TWIN_PAIRS = [
    ("PARIS (intramuros)", "MARNE LA VALLEE CHESSY", 60, "RER A, environ 40 min"),
    ("PARIS (intramuros)", "MASSY TGV", 60, "RER B ou C, environ 35 min"),
    ("PARIS (intramuros)", "MASSY PALAISEAU", 60, "RER B ou C, environ 35 min"),
    ("PARIS (intramuros)", "AEROPORT ROISSY CDG 2 TGV", 60, "RER B, environ 35 min"),
    ("PARIS (intramuros)", "VERSAILLES CHANTIERS", 50, "train ou RER C, environ 25 min"),
    ("MASSY TGV", "MASSY PALAISEAU", 20, "à pied, environ 10 min"),
    ("MASSY TGV", "MARNE LA VALLEE CHESSY", 100, "RER B et RER A, environ 1 h 15"),
    ("MASSY TGV", "AEROPORT ROISSY CDG 2 TGV", 90, "RER B, environ 1 h 05"),
    ("MARNE LA VALLEE CHESSY", "AEROPORT ROISSY CDG 2 TGV", 90, "RER A et RER B, environ 1 h 10"),
    ("LYON (intramuros)", "LYON ST EXUPERY TGV.", 60, "tram Rhônexpress, environ 30 min, ≈ 17 €"),
    ("AVIGNON TGV", "AVIGNON CENTRE", 25, "navette TER, environ 5 min"),
    ("MONTPELLIER SAINT ROCH", "MONTPELLIER SUD DE FRANCE", 40, "navette ou tram, environ 20 min"),
    ("NIMES CENTRE", "NIMES PONT DU GARD", 35, "navette ou TER, environ 15 min"),
    ("VALENCE VILLE", "VALENCE TGV AUVERGNE RHONE ALPES", 25, "TER, environ 10 min"),
    ("REIMS", "CHAMPAGNE ARDENNE TGV", 25, "TER ou tram, environ 10 min"),
    ("BESANCON VIOTTE", "BESANCON FRANCHE COMTE TGV", 30, "TER, environ 15 min"),
    ("METZ VILLE", "LORRAINE TGV", 50, "navette en car, environ 30 min"),
    ("NANCY", "LORRAINE TGV", 50, "navette en car, environ 35 min"),
]
TWINS = {}
for _a, _b, _m, _n in _TWIN_PAIRS:
    TWINS.setdefault(_a, []).append((_b, _m, _n))
    TWINS.setdefault(_b, []).append((_a, _m, _n))


# Paris intra-muros <-> gare TGV d'Île-de-France : tout dépend de la gare parisienne réelle
# (Montparnasse -> Roissy, c'est 1 h, pas 35 min). Minutes de changement (marge comprise), comment faire.
_CDG = "billet aéroport ≈ 13 €"
PARIS_ANNEX = {
    ("Paris Nord", "AEROPORT ROISSY CDG 2 TGV"): (50, f"RER B direct, environ 35 min, {_CDG}"),
    ("Paris Est", "AEROPORT ROISSY CDG 2 TGV"): (55, f"RER B et 5 min à pied entre Paris Est et Paris Nord, environ 40 min, {_CDG}"),
    ("Paris Gare de Lyon", "AEROPORT ROISSY CDG 2 TGV"): (65, f"RER D et RER B, environ 50 min, {_CDG}"),
    ("Paris Bercy", "AEROPORT ROISSY CDG 2 TGV"): (70, f"métro et RER B, environ 55 min, {_CDG}"),
    ("Paris Austerlitz", "AEROPORT ROISSY CDG 2 TGV"): (75, f"RER C et RER B, environ 1 h, {_CDG}"),
    ("Paris Montparnasse", "AEROPORT ROISSY CDG 2 TGV"): (80, f"métro 4 et RER B, environ 1 h, {_CDG}"),
    ("Paris Gare de Lyon", "MARNE LA VALLEE CHESSY"): (55, "RER A direct, environ 40 min"),
    ("Paris Bercy", "MARNE LA VALLEE CHESSY"): (60, "RER A et 10 min à pied entre Bercy et Gare de Lyon, environ 45 min"),
    ("Paris Austerlitz", "MARNE LA VALLEE CHESSY"): (65, "métro et RER A, environ 50 min"),
    ("Paris Nord", "MARNE LA VALLEE CHESSY"): (70, "RER B ou D et RER A, environ 55 min"),
    ("Paris Est", "MARNE LA VALLEE CHESSY"): (75, "métro et RER A, environ 1 h"),
    ("Paris Montparnasse", "MARNE LA VALLEE CHESSY"): (80, "métro et RER A, environ 1 h"),
    ("Paris Austerlitz", "MASSY TGV"): (55, "RER C direct, environ 40 min"),
    ("Paris Nord", "MASSY TGV"): (55, "RER B direct, environ 40 min"),
    ("Paris Montparnasse", "MASSY TGV"): (55, "métro 4 et RER B, environ 40 min"),
    ("Paris Gare de Lyon", "MASSY TGV"): (65, "RER D et RER B, environ 50 min"),
    ("Paris Bercy", "MASSY TGV"): (70, "métro et RER B ou C, environ 55 min"),
    ("Paris Est", "MASSY TGV"): (65, "RER B et 5 min à pied entre Paris Est et Paris Nord, environ 50 min"),
    ("Paris Montparnasse", "VERSAILLES CHANTIERS"): (40, "train direct, environ 15 min"),
    ("Paris Austerlitz", "VERSAILLES CHANTIERS"): (60, "RER C direct, environ 45 min"),
}
for (_p, _x), _v in list(PARIS_ANNEX.items()):
    if _x == "MASSY TGV":
        PARIS_ANNEX[(_p, "MASSY PALAISEAU")] = _v
for _p in ("Paris Nord", "Paris Est", "Paris Gare de Lyon", "Paris Bercy"):
    PARIS_ANNEX.setdefault((_p, "VERSAILLES CHANTIERS"), (75, "métro et train via Montparnasse, environ 1 h"))


def twin_change(a, b, arriving=None, departing=None):
    """Passer de la gare a (arrivée par le train `arriving`) à sa jumelle b (départ par `departing`) :
    (minutes de changement, comment faire), ou None si a et b ne sont pas jumelles."""
    base = next(((m, n) for x, m, n in TWINS.get(a, ()) if x == b), None)
    if base is None:
        return None
    if a == "PARIS (intramuros)" and arriving is not None:
        return PARIS_ANNEX.get((city_station(a, arriving), b), base)
    if b == "PARIS (intramuros)" and departing is not None:
        return PARIS_ANNEX.get((city_station(b, departing), a), base)
    return base


def twin_note(a, b, arriving=None, departing=None):
    """Comment passer de la gare a à la gare b (gares jumelles), ou None."""
    t = twin_change(a, b, arriving, departing)
    return t and t[1]


# Gare jumelle ajoutée d'office à une recherche si on la rejoint en moins d'une heure (marge comprise) :
# chercher « Metz » propose aussi Lorraine TGV, « Avignon TGV » aussi Avignon Centre, « Massy » aussi Paris.
NEARBY_MAX_MIN = 60


def resolve_area(city, stations):
    """(gares, voisines) : les gares de la ville cherchée, puis leurs gares jumelles proches.
    voisines : gare ajoutée -> (gare cherchée la plus proche, minutes, comment y aller)."""
    base = _match_city(city, stations)
    extra = {}
    for s in base:
        for t, mins, note in TWINS.get(s, ()):
            if mins <= NEARBY_MAX_MIN and t not in base and t not in extra and (not stations or t in stations):
                extra[t] = (s, mins, note)
    return base + list(extra), extra


def resolve_city(city, stations):
    """Libellés de gare du dataset pour `city` : la ville (alias, exact, ou contient) et ses gares voisines."""
    return resolve_area(city, stations)[0]


def note_minutes(note, default):
    """« RER B direct, environ 40 min » -> 40 (temps de trajet annoncé), sinon default."""
    m = re.search(r"environ (\d+) h(?: (\d+))?|environ (\d+) min", note or "")
    if not m:
        return default
    return int(m.group(3)) if m.group(3) else int(m.group(1)) * 60 + int(m.group(2) or 0)


def _match_city(city, stations):
    """Libellés de gare du dataset correspondant à `city` (alias, exact, ou contient)."""
    key = city.strip().lower()
    if city.strip() in MAIN_STATION_KEY:          # gare choisie dans la liste : la ville et ses gares annexes
        key = MAIN_STATION_KEY[city.strip()]
    if key in CITY_ALIASES:
        hit = [s for s in CITY_ALIASES[key] if s in stations]
        return hit or CITY_ALIASES[key]
    nq = normalize(key)
    exact = sorted(s for s in stations if normalize(s) == nq)
    if exact:
        return exact
    if len(nq) < 3:                       # « e », « pa »… : trop vague, ferait exploser la recherche
        return [city.upper()]
    contains = sorted((s for s in stations if word_start(nq, normalize(s))), key=len)[:6]
    if contains:
        return contains
    # gare hors réseau Max choisie dans la liste (« Lyon Part Dieu », « Paris Montparnasse Hall 1 - 2 ») :
    # on retombe sur la ville (« lyon », « paris ») pour garder ses trains Max
    words = nq.split()
    for n in range(len(words) - 1, 0, -1):
        sub = " ".join(words[:n])
        if len(sub) >= 3 and (sub in CITY_ALIASES or any(normalize(s) == sub for s in stations)):
            return _match_city(sub, stations)
    return [city.upper()]


def word_start(q, name):
    """q apparaît-il au début d'un mot de name ? (« aix » trouve Aix-les-Bains, pas Morlaix)"""
    return name.startswith(q) or (" " + q) in name


# Paris : le jeu de données regroupe toutes les gares sous « PARIS (intramuros) ». L'axe du train
# indique la gare réelle ; changer de gare demande de traverser Paris (métro / RER).
PARIS_BY_AXE = {"SUD EST": "Paris Gare de Lyon", "ATLANTIQUE": "Paris Montparnasse", "NORD": "Paris Nord",
                "EST": "Paris Est", "IC NUIT": "Paris Austerlitz", "INTERNATIONAL": "Paris Gare de Lyon"}
PARIS_COORDS = {"Paris Gare de Lyon": (48.8443, 2.3744), "Paris Montparnasse": (48.8412, 2.3209),
                "Paris Nord": (48.8809, 2.3553), "Paris Est": (48.8766, 2.3592),
                "Paris Austerlitz": (48.8420, 2.3653), "Paris Bercy": (48.8390, 2.3826)}
PARIS_CHANGE = {frozenset(("Paris Gare de Lyon", "Paris Bercy")): 25, frozenset(("Paris Nord", "Paris Est")): 25,
                frozenset(("Paris Gare de Lyon", "Paris Austerlitz")): 40,
                frozenset(("Paris Austerlitz", "Paris Bercy")): 40}
PARIS_CHANGE_DEFAULT = 60        # traverser Paris en métro / RER, avec une marge


def city_station(label, edge):
    """Gare réelle d'un train dans une ville multi-gares (Paris seulement : ailleurs, inconnue)."""
    if label != "PARIS (intramuros)":
        return None
    axe, ent = edge.get("axe", ""), edge.get("entity", "")
    if axe.startswith("IC") and axe != "IC NUIT":
        return "Paris Bercy" if "CLERMONT" in ent else "Paris Austerlitz"
    return PARIS_BY_AXE.get(axe)


def transfer_min(station, arriving, departing):
    """Temps de correspondance mini entre deux trains Max à une gare (changement de gare compris)."""
    a, b = city_station(station, arriving), city_station(station, departing)
    if a and b:
        return config.MIN_CONNECTION_MIN if a == b else PARIS_CHANGE.get(frozenset((a, b)), PARIS_CHANGE_DEFAULT)
    return min_connection(station)


def min_connection(station):
    return config.MIN_CONNECTION_INTRAMUROS if "(intramuros)" in station else config.MIN_CONNECTION_MIN

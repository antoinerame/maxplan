"""Recherche des trajets Max : parcours en profondeur horodaté sur les trains du jour
(index par heure de départ, élagage par accessibilité, changements de gare jumelle)."""

import bisect
import threading

from maxplan import config
from maxplan.moteur.gares import TWINS, transfer_min, twin_change


_IDX = {}            # id(liste de trains du jour) -> (liste, index) : construit une fois par jour
_IDX_LOCK = threading.Lock()


def _index(edges):
    """Trains par gare de départ, triés par heure (pour ne lire que ceux de la fenêtre utile)."""
    hit = _IDX.get(id(edges))
    if hit and hit[0] is edges:
        return hit[1]
    by = {}
    for i, e in enumerate(edges):
        by.setdefault(e["o"], []).append((e["dep"], i, e))
    idx = {}
    for st, v in by.items():
        v.sort(key=lambda x: (x[0], x[1]))
        idx[st] = ([x[0] for x in v], [(x[1], x[2]) for x in v])
    rev = {}
    for e in edges:
        rev.setdefault(e["d"], set()).add(e["o"])
    idx[None] = rev                      # clé spéciale : graphe inverse, pour _reach_levels
    with _IDX_LOCK:
        if len(_IDX) >= 70:                  # tout le calendrier (~2 mois) tient dedans
            _IDX.pop(next(iter(_IDX)))
        _IDX[id(edges)] = (edges, idx)
    return idx


def _window(idx, station, lo, hi):
    """Trains partant de station entre lo et hi, dans l'ordre de l'open data."""
    hit = idx.get(station)
    if not hit:
        return ()
    deps, items = hit
    sel = items[bisect.bisect_left(deps, lo):bisect.bisect_right(deps, hi)]
    sel.sort(key=lambda x: x[0])
    return [e for _, e in sel]


def _departures(idx, station, path, lo, hi):
    """Trains au départ de la gare… ou de sa jumelle (changement de gare) : (train, attente mini).
    Premier train : départ entre lo et hi ; ensuite : dans l'attente maximale de correspondance."""
    if not path:
        for e in _window(idx, station, lo, hi):
            yield e, 0
        return
    arrived = path[-1]["arr"]
    hi = arrived + config.MAX_LAYOVER_MIN
    for e in _window(idx, station, arrived, hi):
        yield e, None                        # attente mini calculée seulement si besoin (coûteuse)
    for other, mins, _ in TWINS.get(station, ()):
        paris = "PARIS (intramuros)" in (station, other)
        for e in _window(idx, other, arrived, hi):
            yield e, (twin_change(station, other, path[-1], e)[0] if paris else mins)


def night_overlap(start, end):
    """[start,end] (minutes absolues : train ou attente en gare) empiète-t-il vraiment sur la nuit ?
    On regarde le cœur de la nuit (0 h 30 – 5 h) avec au moins 30 min de chevauchement : une arrivée
    à 23 h 20 ou un départ à 5 h 59 ne font pas un « trajet de nuit »."""
    for k in range(0, 5):  # autour de chaque minuit (0, 1440, 2880, ...)
        w0, w1 = k * 1440 + 30, k * 1440 + 300
        if min(end, w1) - max(start, w0) >= 30:
            return True
    return False


def _reach_levels(edges, targets, k):
    """levels[i] = gares d'où l'on peut atteindre `targets` en au plus i trains (sans tenir compte
    des horaires). Sert à élaguer la recherche : inutile de suivre un train vers une gare d'où la
    destination est hors de portée avec les correspondances restantes."""
    rev = _index(edges)[None]             # gare -> gares d'où un train y va (calculé une fois par jour)
    def with_twins(s):                    # une gare jumelle « vaut » l'autre (changement de gare)
        return s | {t for x in s for t, _, _ in TWINS.get(x, ())}

    levels = [with_twins(set(targets))]
    for _ in range(k):
        cur = levels[-1]
        nxt = set(cur)
        for s in cur:
            nxt |= rev.get(s, set())
        levels.append(with_twins(nxt))
    return levels


def search(edges, origins, targets, max_conn=3, max_results=40, min_dep=0, max_dep=1440):
    """DFS horodaté O -> targets, <= max_conn correspondances, sans repasser par une gare."""
    idx = _index(edges)
    origins, targets = set(origins), set(targets)
    levels = _reach_levels(edges, targets, max_conn + 1)
    found = []

    def dfs(station, arrived_at, path, visited):
        if len(path) > max_conn + 1:
            return
        left = max_conn - len(path)            # trains encore possibles après celui-ci
        lvl = levels[max(0, left)]
        for e, need in _departures(idx, station, path, min_dep, max_dep):
            if e["d"] in visited or e["d"] not in lvl:
                continue
            if path:
                if need is None:
                    need = transfer_min(station, path[-1], e)
                if e["dep"] - arrived_at < need:
                    continue
            total = (e["arr"] - path[0]["dep"]) if path else (e["arr"] - e["dep"])
            if total > config.MAX_TOTAL_MIN:
                continue
            newpath = path + [e]
            if e["d"] in targets:
                found.append(newpath)
                continue                        # arrivé : inutile de repartir
            if len(newpath) <= max_conn:
                dfs(e["d"], e["arr"], newpath, visited | {e["d"], e["o"]})

    for o in sorted(origins):             # ordre stable (résultats identiques d'un lancement à l'autre)
        dfs(o, 0, [], {o})

    seen, uniq = set(), []
    for p in found:
        # même train, autre gare de montée (ou autre horaire, ex. Perrache / Part-Dieu) : trajet distinct
        sig = tuple((l["train"], l["o"], l["d"], l["dep"]) for l in p)
        if sig not in seen:
            seen.add(sig)
            uniq.append(p)
    uniq.sort(key=lambda p: (p[-1]["arr"] - p[0]["dep"], len(p)))
    # les directs sont toujours gardés (un train de nuit direct est long mais imbattable)
    direct = [p for p in uniq if len(p) == 1]
    rest = [p for p in uniq if len(p) > 1][:max(0, max_results - len(direct))]
    return sorted(direct + rest, key=lambda p: (p[-1]["arr"] - p[0]["dep"], len(p)))


def reachable(edges, origins, max_conn=1, min_dep=0, max_dep=1440):
    """Gares atteignables en Max depuis origins, avec le nb mini de trains et un exemple."""
    idx = _index(edges)
    origins_list = list(origins)
    best = {}

    def dfs(station, arrived_at, path, visited):
        for e, need in _departures(idx, station, path, min_dep, max_dep):
            if e["d"] in visited:
                continue
            if path:
                if need is None:
                    need = transfer_min(station, path[-1], e)
                if e["dep"] - arrived_at < need:
                    continue
            newpath = path + [e]
            cur = best.get(e["d"])
            if cur is None or len(newpath) < cur[0]:
                best[e["d"]] = (len(newpath), newpath)
            if len(newpath) <= max_conn:
                dfs(e["d"], e["arr"], newpath, visited | {e["d"], e["o"]})

    for o in dict.fromkeys(origins_list):  # gare principale d'abord : l'exemple de trajet part d'elle
        dfs(o, 0, [], {o})
    return best

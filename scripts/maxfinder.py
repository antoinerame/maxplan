#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
maxfinder — Trouve des trajets TGV Max (gratuits avec l'abonnement Max Jeune),
y compris en recomposant des correspondances que l'app SNCF Connect ne propose pas.

Source de données : open data SNCF "tgvmax" (licence ODbL), sans clé d'API.
  https://ressources.data.sncf.com/explore/dataset/tgvmax/
Le dataset liste, pour ~30 jours glissants, chaque train avec od_happy_card=OUI/NON
(= place Max gratuite disponible ou non). Rafraîchi 1x/jour le matin : la dispo est
INDICATIVE (à reconfirmer au moment de réserver sur SNCF Connect).

Le moteur :
  - recompose des chaînes de TGV Max gratuits (0, 1 ou 2 correspondances) ;
  - pour les destinations sans Max direct (ex. Aix), passe par un hub Max puis
    propose un dernier segment TER/navette PAYANT (le TER n'est pas inclus dans Max Jeune) ;
  - trie par durée totale et affiche le détail + le coût des segments payants.

Aucune réservation automatique (interdit par les CGV Max Jeune). Sortie = info + à toi de réserver.
"""

import argparse
import json
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import date as Date, timedelta

try:  # console Windows : éviter UnicodeEncodeError sur les emojis
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

API = "https://ressources.data.sncf.com/api/explore/v2.1/catalog/datasets/tgvmax"

# --- Alias ville -> libellé(s) de gare tels qu'écrits dans le dataset --------------
# (le dataset regroupe les villes multi-gares sous "<VILLE> (intramuros)")
CITY_ALIASES = {
    "paris": ["PARIS (intramuros)"],
    "lyon": ["LYON (intramuros)"],
    "marseille": ["MARSEILLE ST CHARLES", "MARSEILLE BLANCARDE"],
    "lille": ["LILLE (intramuros)"],
    "avignon": ["AVIGNON TGV", "AVIGNON CENTRE"],
    "aix": ["AIX EN PROVENCE TGV"],
    "aix-en-provence": ["AIX EN PROVENCE TGV"],
    "bourg-en-bresse": ["BOURG EN BRESSE"],
}

# Pour une ville-destination sans Max direct : gares "passerelles" atteignables en Max,
# + le dernier segment PAYANT (TER/navette) pour rejoindre le centre.
# Utilisé en fallback statique quand aucune clé Navitia n'est fournie.
DEST_GATEWAYS = {
    "aix-en-provence": {
        "free_targets": ["AIX EN PROVENCE TGV", "MARSEILLE ST CHARLES", "AVIGNON TGV", "AVIGNON CENTRE"],
        "tail": {
            "AIX EN PROVENCE TGV": dict(mode="Navette/bus", to="Aix centre", dur=20, price="~4 €"),
            "MARSEILLE ST CHARLES": dict(mode="TER", to="Aix-en-Provence Centre", dur=40, price="~9 €"),
            "AVIGNON CENTRE": dict(mode="TER", to="Aix-en-Provence Centre", dur=70, price="~13 €"),
            "AVIGNON TGV": dict(mode="TER/bus", to="Aix-en-Provence", dur=80, price="~15 €"),
        },
    },
}


def normalize(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return s.lower().replace("-", " ").replace("(intramuros)", "").strip()


def resolve_city(city, stations):
    """Retourne les libellés de gare du dataset correspondant à `city`."""
    key = city.strip().lower()
    if key in CITY_ALIASES:
        return [s for s in CITY_ALIASES[key] if s in stations] or CITY_ALIASES[key]
    nq = normalize(key)
    exact = [s for s in stations if normalize(s) == nq]
    if exact:
        return exact
    contains = sorted(s for s in stations if nq in normalize(s))
    return contains or [city.upper()]


def hhmm_to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def min_to_hhmm(x):
    x %= 1440
    return f"{x // 60:02d}:{x % 60:02d}"


def date_filter(d):
    """d = 'YYYY-MM-DD' -> clause ODSQL (le champ `date` est de type date)."""
    y, m, dd = d.split("-")
    return f"year(date)={int(y)} and month(date)={int(m)} and day(date)={int(dd)}"


def fetch_oui_edges(d):
    """Tous les segments avec place Max (od_happy_card=OUI) pour la date d, en un appel."""
    where = date_filter(d) + " and od_happy_card='OUI'"
    params = {
        "where": where,
        "select": "train_no,entity,axe,origine,destination,heure_depart,heure_arrivee",
        "limit": -1,  # endpoint /exports : pas de limite
    }
    url = API + "/exports/json?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.load(r)
    rows = data if isinstance(data, list) else data.get("results", [])
    edges = []
    for x in rows:
        dep = hhmm_to_min(x["heure_depart"])
        arr = hhmm_to_min(x["heure_arrivee"])
        if arr < dep:
            arr += 1440  # arrivée le lendemain
        edges.append({
            "o": x["origine"], "d": x["destination"],
            "dep": dep, "arr": arr,
            "train": x["train_no"], "entity": x.get("entity", ""), "axe": x.get("axe", ""),
        })
    return edges


def min_connection(station):
    # gares "intramuros" = changement possible entre gares physiques différentes -> marge plus large
    return 30 if "(intramuros)" in station else 15


def search(edges, origins, targets, max_conn=2, max_results=40, max_total_min=16 * 60, max_layover_min=4 * 60):
    """DFS horodaté O -> targets, <= max_conn correspondances, sans repasser par une gare."""
    by_origin = {}
    for e in edges:
        by_origin.setdefault(e["o"], []).append(e)

    origins = set(origins)
    targets = set(targets)
    found = []

    def dfs(station, arrived_at, path, visited):
        if len(path) > max_conn + 1:
            return
        for e in by_origin.get(station, []):
            if e["d"] in visited:
                continue
            if path:  # contrainte de correspondance
                wait = e["dep"] - arrived_at
                if wait < min_connection(station) or wait > max_layover_min:
                    continue
            total = e["arr"] - path[0]["dep"] if path else e["arr"] - e["dep"]
            if total > max_total_min:
                continue
            newpath = path + [e]
            if e["d"] in targets:
                found.append(newpath)
            if len(newpath) <= max_conn:  # continuer à étendre
                dfs(e["d"], e["arr"], newpath, visited | {e["d"]})

    for o in origins:
        dfs(o, 0, [], {o})

    # dédup par signature (trains) + tri par durée totale puis nb de segments
    seen = set()
    uniq = []
    for p in found:
        sig = tuple(l["train"] for l in p)
        if sig in seen:
            continue
        seen.add(sig)
        uniq.append(p)
    uniq.sort(key=lambda p: (p[-1]["arr"] - p[0]["dep"], len(p)))
    return uniq[:max_results]


def itinerary_lines(path, dest_city):
    """Construit l'affichage d'un itinéraire + un éventuel dernier segment TER payant."""
    legs = []
    for l in path:
        legs.append({
            "free": True, "o": l["o"], "d": l["d"],
            "dep": min_to_hhmm(l["dep"]), "arr": min_to_hhmm(l["arr"]),
            "info": f"TGV Max {l['train']}", "price": "GRATUIT",
        })
    # dernier segment payant si on n'arrive pas pile à la gare "finale"
    paid = None
    gw = DEST_GATEWAYS.get(dest_city, {}).get("tail", {})
    last_station = path[-1]["d"]
    if last_station in gw:
        t = gw[last_station]
        if t["mode"] != "Navette/bus" or True:
            paid = {
                "free": False, "o": last_station, "d": t["to"],
                "dep": "", "arr": "", "info": f"{t['mode']} (~{t['dur']} min)", "price": t["price"],
            }
    if paid:
        legs.append(paid)
    return legs


def fmt_itinerary(legs, idx):
    dep0 = next((l["dep"] for l in legs if l["dep"]), "")
    nb_resa = sum(1 for l in legs if l["free"])
    paid_legs = [l for l in legs if not l["free"]]
    head = f"  [{idx}] départ {dep0}  •  {nb_resa} résa Max"
    if paid_legs:
        head += "  •  + " + ", ".join(l["price"] for l in paid_legs) + " (TER payant)"
    else:
        head += "  •  100% gratuit"
    out = [head]
    for l in legs:
        arrow = "🆓" if l["free"] else "💶"
        times = f"{l['dep']}→{l['arr']}" if l["dep"] else "       "
        out.append(f"        {arrow} {times}  {l['o']:<24} → {l['d']:<24}  {l['info']}")
    return "\n".join(out)


def reachable(edges, origins, max_conn=1):
    """Toutes les gares atteignables en Max depuis `origins`, avec le nb mini de trains."""
    by_origin = {}
    for e in edges:
        by_origin.setdefault(e["o"], []).append(e)
    origins = set(origins)
    best = {}  # station -> (nb_legs, path)

    def dfs(station, arrived_at, path, visited):
        for e in by_origin.get(station, []):
            if e["d"] in visited:
                continue
            if path and e["dep"] < arrived_at + min_connection(station):
                continue
            newpath = path + [e]
            cur = best.get(e["d"])
            if cur is None or len(newpath) < cur[0]:
                best[e["d"]] = (len(newpath), newpath)
            if len(newpath) <= max_conn:
                dfs(e["d"], e["arr"], newpath, visited | {e["d"]})

    for o in origins:
        dfs(o, 0, [], {o})
    return best


def daterange(start, end):
    s = Date.fromisoformat(start)
    e = Date.fromisoformat(end)
    cur = s
    while cur <= e:
        yield cur.isoformat()
        cur += timedelta(days=1)


WEEKDAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def run_search(args, origins_city, dst_city):
    to_date = args.to_date or args.from_date
    print(f"\n🚄  TGV Max : {args.src}  →  {args.dst}   ({args.from_date} → {to_date})")
    print(f"    correspondances ≤ {args.max_conn}   |   source : open data SNCF tgvmax (ODbL, dispo indicative)\n")

    grand_total = 0
    for d in daterange(args.from_date, to_date):
        try:
            edges = fetch_oui_edges(d)
        except Exception as e:
            print(f"── {d} : erreur de récupération ({e})")
            continue
        stations = {e["o"] for e in edges} | {e["d"] for e in edges}
        origins = resolve_city(origins_city, stations)
        targets = list(resolve_city(dst_city, stations))
        gw = DEST_GATEWAYS.get(dst_city)
        if gw:
            targets = list(dict.fromkeys([t for t in gw["free_targets"] if t in stations] + targets))

        itins = search(edges, origins, targets, max_conn=args.max_conn, max_results=args.max_results)
        weekday = WEEKDAYS[Date.fromisoformat(d).weekday()]
        if not itins:
            print(f"── {d} ({weekday}) : aucun trajet Max trouvé (autre date, ou +1 correspondance ?)")
            continue
        print(f"── {d} ({weekday}) : {len(itins)} itinéraire(s) Max\n")
        for i, p in enumerate(itins, 1):
            legs = itinerary_lines(p, dst_city)
            print(fmt_itinerary(legs, i))
            print()
        grand_total += len(itins)
    print(f"Total : {grand_total} itinéraire(s) sur la période.")
    print("⚠️  Dispo indicative (open data MAJ 1x/jour). Reconfirme et réserve sur SNCF Connect.\n")


def run_explore(args, origins_city):
    to_date = args.to_date or args.from_date
    print(f"\n🧭  Où aller en TGV Max depuis « {args.src} »   ({args.from_date} → {to_date}, ≤ {args.max_conn} corresp.)\n")
    for d in daterange(args.from_date, to_date):
        try:
            edges = fetch_oui_edges(d)
        except Exception as e:
            print(f"── {d} : erreur ({e})")
            continue
        stations = {e["o"] for e in edges} | {e["d"] for e in edges}
        origins = resolve_city(origins_city, stations)
        best = reachable(edges, origins, max_conn=args.max_conn)
        weekday = WEEKDAYS[Date.fromisoformat(d).weekday()]
        direct = sorted(s for s, (n, _) in best.items() if n == 1)
        corr = sorted(s for s, (n, _) in best.items() if n >= 2)
        print(f"── {d} ({weekday}) : {len(direct)} en direct, {len(corr)} via correspondance")
        print("     directs : " + (", ".join(direct) if direct else "—"))
        if corr:
            print("     +1 corr : " + ", ".join(corr))
        print()


def main():
    ap = argparse.ArgumentParser(description="Trouve des trajets TGV Max (+ correspondances) via l'open data SNCF.")
    ap.add_argument("--from", dest="src", required=True, help="ville/gare de départ (ex: paris)")
    ap.add_argument("--to", dest="dst", help="ville/gare d'arrivée (ex: aix-en-provence)")
    ap.add_argument("--from-date", required=True, help="date de début AAAA-MM-JJ")
    ap.add_argument("--to-date", help="date de fin AAAA-MM-JJ (défaut: = from-date)")
    ap.add_argument("--max-conn", type=int, default=2, help="correspondances max (défaut 2 ; explore: 1)")
    ap.add_argument("--max-results", type=int, default=8, help="itinéraires max par jour")
    ap.add_argument("--explore", action="store_true", help="liste TOUT ce qui est atteignable en Max depuis --from")
    args = ap.parse_args()

    if args.explore:
        if args.max_conn == 2 and "--max-conn" not in sys.argv:
            args.max_conn = 1
        run_explore(args, args.src.strip().lower())
    else:
        if not args.dst:
            ap.error("--to est requis (sauf en mode --explore)")
        run_search(args, args.src.strip().lower(), args.dst.strip().lower())


if __name__ == "__main__":
    main()

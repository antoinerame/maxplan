"""Pages par liaison pour les moteurs de recherche : /tgv-max/ (toutes les liaisons), /tgv-max/paris-lyon
(trains directs à 0 € des 30 prochains jours, horaires, meilleurs jours) et /sitemap.xml.

Pages HTML rendues par le serveur (lisibles sans JavaScript), recalculées au plus une fois par heure
à partir des places Max déjà chargées pour la recherche : aucune requête de plus à la SNCF."""

import html
import json
import re
import threading
import time
import unicodedata
import urllib.parse
from datetime import date as Date

from maxplan import historique
from maxplan.moteur import donnees, gares
from maxplan.api.commun import past_min
from maxplan.api.trajets import edges_for, pretty, train_mode

SITE = "https://maxplan.fr"
# villes proposées (nom affiché) : celles qui ont des trains Max, gares voisines comprises (Paris : Massy,
# Marne-la-Vallée, Roissy ; Lyon : Saint-Exupéry…)
CITIES = [
    "Paris", "Lyon", "Marseille", "Bordeaux", "Toulouse", "Lille", "Nantes", "Strasbourg", "Montpellier",
    "Nice", "Rennes", "Grenoble", "Avignon", "Annecy", "La Rochelle", "Dijon", "Metz", "Nancy", "Reims",
    "Tours", "Angers", "Le Mans", "Brest", "Quimper", "Toulon", "Nîmes", "Perpignan", "Besançon",
    "Mulhouse", "Poitiers", "Angoulême", "Valence", "Aix-en-Provence", "Cannes", "Chambéry",
    "Saint-Étienne", "Clermont-Ferrand", "Limoges", "Bayonne", "Biarritz", "Pau", "Tarbes", "Arras",
    "Rouen", "Le Havre", "Saint-Malo", "Vannes", "Lorient", "Laval", "Orléans", "Narbonne", "Béziers",
    "Sète", "Agen", "Montauban", "Dax", "Arcachon", "Les Sables-d'Olonne", "Saint-Nazaire", "La Baule",
    "Colmar", "Belfort", "Mâcon", "Chalon-sur-Saône", "Lourdes", "Hendaye", "Saint-Raphaël", "Antibes",
    "Aix-les-Bains", "Évian-les-Bains", "Thonon-les-Bains", "Brive-la-Gaillarde",
]
SITEMAP_MIN = 10       # trains (jour × train) sur la période pour qu'une liaison aille dans le sitemap
TTL = 3600
WD = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
WD_S = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]

_lock = threading.Lock()
_cache = {"t": 0.0, "data": None}


def slug(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


SLUGS = {slug(c): c for c in CITIES}


def _hm(m):
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _dur(m):
    return f"{m // 60} h {m % 60:02d}" if m >= 60 else f"{m} min"


def _num(x):
    """1 décimale à la française, sans « ,0 » inutile."""
    return f"{x:.1f}".replace(".0", "").replace(".", ",") if x % 1 else f"{x:.0f}"


def _day(iso, weekday=True):
    d = Date.fromisoformat(iso)
    return f"{WD[d.weekday()] + ' ' if weekday else ''}{d.day}{'er' if d.day == 1 else ''} {MONTHS[d.month - 1]}"


def _data():
    """{(ville, ville): {date: {train: (départ, arrivée, gare de départ, gare d'arrivée, type)}}}, recalculé
    au plus une fois par heure."""
    with _lock:
        if _cache["data"] is not None and time.time() - _cache["t"] < TTL:
            return _cache["data"]
        stations = set(donnees.all_stations())
        area, city_of = {}, {}
        for c in CITIES:
            area[c] = [s for s in gares.resolve_area(c, stations)[0] if s in stations]
            for s in area[c]:
                city_of.setdefault(s, set()).add(c)
        dates = donnees.dataset_dates()
        pairs = {}
        for d in dates:
            try:
                edges = edges_for(d)
            except Exception:
                continue
            for e in edges:
                for co in city_of.get(e["o"], ()):
                    for cd in city_of.get(e["d"], ()):
                        if co == cd:
                            continue
                        day = pairs.setdefault((co, cd), {}).setdefault(d, {})
                        old = day.get(e["train"])
                        if not old or e["dep"] < old[0]:   # même train vu depuis deux gares : la première
                            day[e["train"]] = (e["dep"], e["arr"], e["o"], e["d"], train_mode(e["axe"]))
        # rames couplées (deux numéros, même départ, même gare) : un seul train pour le voyageur
        for days in pairs.values():
            for d, day in days.items():
                seen = set()
                for t, v in sorted(day.items(), key=lambda kv: kv[0]):
                    if (v[0], v[2]) in seen:
                        del day[t]
                    seen.add((v[0], v[2]))
        data = {"pairs": pairs, "dates": dates, "area": area, "built": time.time()}
        _cache.update(t=time.time(), data=data)
        return data


def _count(days):
    return sum(len(v) for v in days.values())


def sitemap_pairs():
    pairs = _data()["pairs"]
    return sorted((p for p, days in pairs.items() if _count(days) >= SITEMAP_MIN),
                  key=lambda p: (CITIES.index(p[0]), CITIES.index(p[1])))


def parse_route(s):
    """« paris-lyon » -> ("Paris", "Lyon") ; None si ce n'est pas une liaison connue."""
    parts = s.split("-")
    for k in range(1, len(parts)):
        a, b = "-".join(parts[:k]), "-".join(parts[k:])
        if a in SLUGS and b in SLUGS and a != b:
            return SLUGS[a], SLUGS[b]
    return None


def route_url(a, b):
    return f"/tgv-max/{slug(a)}-{slug(b)}"


def search_url(a, b, d=None):
    q = {"f": a, "fl": a.lower(), "t": b, "tl": b.lower()}
    if d:
        q.update(du=d, au=d)
    return "/?" + urllib.parse.urlencode(q)


# ============================================================================================ rendu HTML
def _e(s):
    return html.escape(str(s), quote=True)


def _page(title, description, canonical, body, jsonld=None, noindex=False):
    ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>\n' if jsonld else ""
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{_e(title)}</title>
<meta name="description" content="{_e(description)}">
<link rel="canonical" href="{SITE}{canonical}">
{'<meta name="robots" content="noindex, follow">' if noindex else '<meta name="robots" content="index, follow">'}
<meta name="theme-color" content="#0C131F">
<meta property="og:type" content="website">
<meta property="og:site_name" content="MaxPlan">
<meta property="og:locale" content="fr_FR">
<meta property="og:url" content="{SITE}{canonical}">
<meta property="og:title" content="{_e(title)}">
<meta property="og:description" content="{_e(description)}">
<meta property="og:image" content="{SITE}/og-image.png">
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="stylesheet" href="/app.css">
{ld}</head>
<body>
<div class="app legal-page route-page">
  <header class="bar">
    <a class="brand" href="/" aria-label="MaxPlan, accueil"><span class="brand-name">Max<em>Plan</em></span></a>
    <span class="bar-status"></span>
    <a class="bar-btn" href="/">Rechercher</a>
  </header>
  <main class="legal">
{body}
    <p class="rp-foot">Données : open data SNCF « tgvmax », mise à jour chaque matin. Une place affichée peut être
    partie depuis : la réservation se fait sur SNCF Connect. MaxPlan est un site indépendant, non officiel.
    <a href="/tgv-max/">Toutes les liaisons</a> · <a href="/mentions-legales.html">Mentions légales et sources</a></p>
  </main>
</div>
</body>
</html>"""


def _crumbs(*items):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": SITE + u} for i, (n, u) in enumerate(items)]}


def route_page(a, b):
    data = _data()
    dates, days = data["dates"], data["pairs"].get((a, b), {})
    rows = []
    for d in dates:
        gone = past_min(d)            # aujourd'hui : sans les trains déjà partis
        trains = sorted(((t, v) for t, v in days.get(d, {}).items() if v[0] >= gone), key=lambda kv: kv[1][0])
        rows.append((d, trains))
    with_trains = [r for r in rows if r[1]]
    n_days, n_with = len(rows), len(with_trains)
    total = sum(len(t) for _, t in rows)
    all_trains = [v for _, t in rows for _, v in t]
    durs = sorted(v[1] - v[0] for v in all_trains)
    deps = sorted(v[0] % 1440 for v in all_trains)
    o_st = sorted({pretty(v[2]) for v in all_trains})
    d_st = sorted({pretty(v[3]) for v in all_trains})
    kinds = sorted({v[4] for v in all_trains})
    wd_sum, wd_n = [0] * 7, [0] * 7
    for d, t in rows:
        w = Date.fromisoformat(d).weekday()
        wd_sum[w] += len(t)
        wd_n[w] += 1
    wd_avg = [(wd_sum[i] / wd_n[i]) if wd_n[i] else 0 for i in range(7)]
    hist = {}
    try:
        h = historique.od_trends(data["area"][a], data["area"][b])
        if h.get("days", 0) >= 14 and h.get("trains"):
            hist = h
    except Exception:
        pass

    title = f"TGV Max {a} → {b} : trains à 0 € avec Max Jeune et Max Senior · MaxPlan"
    if total:
        desc = (f"{a} → {b} avec Max Jeune ou Max Senior : {n_with} jours sur {n_days} ont au moins un train direct "
                f"à 0 € en ce moment, {_num(total / n_days)} trains par jour en moyenne. Horaires, meilleurs jours, "
                f"correspondances et TER.")
    else:
        desc = (f"{a} → {b} avec Max Jeune ou Max Senior : pas de train direct à 0 € en ce moment. MaxPlan "
                f"cherche aussi les trajets avec correspondance et le complément TER.")
    canonical = route_url(a, b)
    next_day = with_trains[0][0] if with_trains else None
    p = []
    p.append(f'<nav class="rp-crumbs" aria-label="Fil d\'Ariane"><a href="/">MaxPlan</a> › '
             f'<a href="/tgv-max/">Liaisons TGV Max</a> › {_e(a)} → {_e(b)}</nav>')
    p.append(f"<h1>TGV Max {_e(a)} → {_e(b)} à 0 €</h1>")
    if total:
        upd = time.strftime("%d/%m", time.localtime(data["built"]))
        p.append(f'<p class="legal-lead">Sur les {n_days} prochains jours couverts par la SNCF, <strong>{n_with} jours '
                 f'ont au moins un train direct à 0 €</strong> de {_e(a)} à {_e(b)} pour les abonnés Max Jeune et '
                 f'Max Senior, avec <strong>{total} trains</strong> au total. Relevé du {upd}.</p>')
    else:
        p.append(f'<p class="legal-lead">Pas de train <strong>direct</strong> à 0 € de {_e(a)} à {_e(b)} sur les '
                 f'{n_days} prochains jours. MaxPlan peut quand même trouver un trajet en enchaînant deux ou trois '
                 f'trains Max, ou en finissant en TER.</p>')
    p.append(f'<p><a class="rp-cta" href="{_e(search_url(a, b, next_day))}">Voir les trains {_e(a)} → {_e(b)} '
             f'avec correspondances et TER</a></p>')

    if total:
        tiles = [
            (f"{n_with}/{n_days}", "jours avec un train direct à 0 €"),
            (_num(total / n_days), "trains à 0 € par jour en moyenne"),
            (_dur(durs[0]), "le trajet le plus rapide"),
            (f"{_hm(deps[0])} – {_hm(deps[-1])}", "premier et dernier départ"),
        ]
        p.append('<div class="rp-tiles">' + "".join(
            f'<div class="rp-tile"><b>{_e(v)}</b><span>{_e(k)}</span></div>' for v, k in tiles) + "</div>")

        best = max(range(7), key=lambda i: wd_avg[i])
        worst = min(range(7), key=lambda i: wd_avg[i])
        top = max(wd_avg) or 1
        bars = "".join(
            f'<li><span>{WD_S[i]}</span><i style="--w:{wd_avg[i] / top * 100:.0f}%"></i>'
            f'<b>{_num(wd_avg[i])}</b></li>' for i in range(7))
        p.append(f'<section><h2>Les meilleurs jours pour partir</h2><p>En moyenne, c\'est le <strong>{WD[best]}</strong> '
                 f'qu\'il y a le plus de trains à 0 € de {_e(a)} à {_e(b)}, et le {WD[worst]} le moins.</p>'
                 f'<ul class="rp-bars" aria-label="Trains à 0 € par jour de la semaine">{bars}</ul></section>')

        trs = []
        for d, t in rows:
            if t:
                times = " · ".join(_hm(v[0]) for _, v in t[:8]) + (" …" if len(t) > 8 else "")
                trs.append(f'<tr><td><a href="{_e(search_url(a, b, d))}">{_e(_day(d))}</a></td>'
                           f'<td class="n">{len(t)}</td><td class="h">{times}</td></tr>')
            else:
                trs.append(f'<tr class="none"><td>{_e(_day(d))}</td><td class="n">0</td><td class="h">—</td></tr>')
        p.append('<section><h2>Les trains directs à 0 €, jour par jour</h2>'
                 '<p>Heures de départ des trains ouverts au Max. Touche un jour pour voir le détail, '
                 'les correspondances et les trajets avec TER.</p>'
                 '<div class="rp-table"><table><thead><tr><th>Jour</th><th class="n">Trains</th>'
                 f'<th>Départs</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div></section>')

        dmed = durs[len(durs) // 2]
        info = [f"Durée : {_dur(dmed)} en général, {_dur(durs[0])} pour le plus rapide."]
        info.append(f"Gares de départ : {', '.join(_e(x) for x in o_st)}.")
        info.append(f"Gares d'arrivée : {', '.join(_e(x) for x in d_st)}.")
        info.append(f"Trains : {', '.join(_e(x) for x in kinds)}, en 2de classe.")
        if hist.get("open_lead"):
            info.append(f"D'après notre historique, les places Max de cette liaison s'ouvrent en général "
                        f"{hist['open_lead']} jours avant le départ.")
        if hist.get("still_open_share") is not None:
            info.append(f"{round(hist['still_open_share'] * 100)} % des trains avaient encore des places Max "
                        f"la veille du départ.")
        p.append("<section><h2>Bon à savoir</h2><ul>" + "".join(f"<li>{x}</li>" for x in info) +
                 "<li>Chaque train se réserve à part sur SNCF Connect avec ta carte Max : une place peut partir "
                 "entre le relevé du matin et ta réservation.</li></ul></section>")

    links = [(f"{b} → {a}", route_url(b, a))]
    pairs = data["pairs"]
    others_from = sorted((c for (x, c) in pairs if x == a and c != b), key=lambda c: -_count(pairs[(a, c)]))[:8]
    others_to = sorted((c for (c, y) in pairs if y == b and c != a), key=lambda c: -_count(pairs[(c, b)]))[:8]
    p.append('<section><h2>Autres liaisons</h2><ul class="rp-links">' +
             "".join(f'<li><a href="{_e(u)}">{_e(n)}</a></li>' for n, u in links) +
             "".join(f'<li><a href="{_e(route_url(a, c))}">{_e(a)} → {_e(c)}</a></li>' for c in others_from) +
             "".join(f'<li><a href="{_e(route_url(c, b))}">{_e(c)} → {_e(b)}</a></li>' for c in others_to) +
             "</ul></section>")

    hist_any = bool(hist)
    return _page(title, desc, canonical, "\n".join(p),
                 _crumbs(("MaxPlan", "/"), ("Liaisons TGV Max", "/tgv-max/"), (f"{a} → {b}", canonical)),
                 noindex=not total and not hist_any)


def hub_page():
    data = _data()
    pairs = data["pairs"]
    listed = set(sitemap_pairs())
    groups = []
    for a in CITIES:
        dests = sorted((b for (x, b) in listed if x == a), key=lambda b: -_count(pairs[(a, b)]))
        if dests:
            groups.append(f'<section><h2>Au départ de {_e(a)}</h2><ul class="rp-links">' + "".join(
                f'<li><a href="{_e(route_url(a, b))}">{_e(a)} → {_e(b)}</a> <small>{_count(pairs[(a, b)])} trains</small></li>'
                for b in dests) + "</ul></section>")
    body = ('<nav class="rp-crumbs" aria-label="Fil d\'Ariane"><a href="/">MaxPlan</a> › Liaisons TGV Max</nav>'
            "<h1>Les liaisons TGV Max à 0 €</h1>"
            f'<p class="legal-lead">Toutes les liaisons avec des trains directs à 0 € pour Max Jeune et Max Senior '
            f'sur les {len(data["dates"])} prochains jours, et le nombre de trains ouverts au Max. Pour un trajet '
            f'avec correspondance ou un complément TER, <a href="/">lance une recherche</a>.</p>' + "".join(groups))
    return _page("Liaisons TGV Max à 0 € : toutes les villes · MaxPlan",
                 "Toutes les liaisons TGV INOUI et Intercités à 0 € pour Max Jeune et Max Senior, ville par ville, "
                 "avec le nombre de trains ouverts au Max sur les 30 prochains jours.",
                 "/tgv-max/", body, _crumbs(("MaxPlan", "/"), ("Liaisons TGV Max", "/tgv-max/")))


def sitemap():
    today = Date.today().isoformat()
    urls = [("/", "daily", "1.0"), ("/tgv-max/", "daily", "0.8")]
    urls += [(route_url(a, b), "daily", "0.6") for a, b in sitemap_pairs()]
    urls.append(("/mentions-legales.html", "monthly", "0.3"))
    body = "".join(f"  <url><loc>{SITE}{u}</loc><lastmod>{today}</lastmod><changefreq>{f}</changefreq>"
                   f"<priority>{p}</priority></url>\n" for u, f, p in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}</urlset>\n')

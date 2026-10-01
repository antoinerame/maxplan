"""/api/insights (onglet Infos : places Max par jour, vacances scolaires) et /api/meta."""

import json
import time
import urllib.request
from datetime import date as Date, datetime, timedelta

from maxplan import VERSION
from maxplan import historique
from maxplan import regions
from maxplan.moteur import donnees
from maxplan.api.trajets import ter_coverage


# Page « Infos » : ce qu'on observe en direct dans les données (une requête légère, mise en cache)
HOLIDAYS_API = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/fr-en-calendrier-scolaire/records"
_HOLI = {"ts": 0.0, "v": []}


def school_holidays():
    """Vacances scolaires de métropole (zones A, B, C) des deux prochains mois (open data Éducation
    nationale). Un jour de vacances : début <= jour < reprise. Mis en cache une journée."""
    if time.time() - _HOLI["ts"] < 86400 and _HOLI["ts"]:
        return _HOLI["v"]
    today = Date.today()
    where = (f"zones in ('Zone A','Zone B','Zone C') and end_date >= '{today.isoformat()}' "
             f"and start_date <= '{(today + timedelta(days=75)).isoformat()}'")
    url = HOLIDAYS_API + "?" + urllib.parse.urlencode({
        "select": "description,start_date,end_date,zones", "where": where,
        "group_by": "description,start_date,end_date,zones", "limit": 50, "order_by": "start_date"})
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            rows = json.load(r).get("results", [])
    except Exception:
        return _HOLI["v"]
    merged = {}
    for x in rows:
        # dates publiées en UTC (« 2026-10-16T22:00:00+00:00 » = 17 octobre à minuit à Paris)
        day = lambda s: (datetime.fromisoformat(s) + timedelta(hours=12)).date().isoformat()
        key = (x["description"], day(x["start_date"]), day(x["end_date"]))
        merged.setdefault(key, []).append(x["zones"].replace("Zone ", ""))
    _HOLI.update(ts=time.time(), v=[{"name": k[0], "start": k[1], "end": k[2], "zones": sorted(z)}
                                    for k, z in sorted(merged.items(), key=lambda kv: kv[0][1])])
    return _HOLI["v"]


def do_insights(qs):
    """Part des trajets (TGV INOUI / Intercités) ouverts au Max chaque jour, vacances, mises à jour."""
    url = donnees.API + "/records?" + urllib.parse.urlencode({
        "select": "date,od_happy_card,count(*) as n", "group_by": "date,od_happy_card",
        "limit": 100, "order_by": "date"})
    with urllib.request.urlopen(url, timeout=30) as r:
        rows = json.load(r).get("results", [])
    per = {}
    for x in rows:
        d = per.setdefault(x["date"][:10], {"oui": 0, "total": 0})
        d["total"] += x["n"]
        if x["od_happy_card"] == "OUI":
            d["oui"] += x["n"]
    days = [{"date": d, "oui": v["oui"], "total": v["total"],
             "pct": round(100 * v["oui"] / v["total"], 1) if v["total"] else 0} for d, v in sorted(per.items())]
    return {"days": days, "holidays": school_holidays(), "updates": historique.update_stats(),
            "history": historique.size_info()}


def do_meta(qs):
    dates = donnees.dataset_dates()
    return {
        "version": VERSION,
        "dates": {"start": dates[0] if dates else None, "end": dates[-1] if dates else None},
        "ter_coverage": ter_coverage(),
        "updates": historique.update_stats(),
        "regions": regions.as_list(),

    }

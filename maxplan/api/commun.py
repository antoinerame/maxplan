"""Outils communs aux points d'API : lecture des paramètres, erreurs, dates."""

import re
from datetime import date as Date, datetime, timedelta
from zoneinfo import ZoneInfo

from maxplan.moteur import donnees


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


class BadRequest(Exception):
    pass


def weekday_idx(d):
    return Date.fromisoformat(d).weekday()


def shift(d, days):
    return (Date.fromisoformat(d) + timedelta(days=days)).isoformat()


def senior_weekend(prefs, date):
    return prefs["sub"] == "senior" and weekday_idx(date) >= 5


SENIOR_NOTICE = "Max Senior : pas de place à 0 € le samedi ni le dimanche."


# ======================================================================= paramètres des requêtes
def _p(qs, name, default=""):
    return (qs.get(name, [default])[0] or default).strip()[:200]


def _place(qs, name, default=""):
    """Nom de gare ou de ville saisi : borné (longueur, nombre de mots) pour que personne ne puisse
    déclencher des dizaines de requêtes de géocodage avec un texte à rallonge."""
    v = _p(qs, name, default)
    if len(v) > 80 or len(v.split()) > 8:
        raise BadRequest("Nom de gare trop long.")
    return v
PARIS_TZ = ZoneInfo("Europe/Paris")


def past_min(day):
    """Aujourd'hui (heure de Paris) : minutes déjà écoulées, pour ne pas proposer un train parti."""
    now = datetime.now(PARIS_TZ)
    return now.hour * 60 + now.minute if day == now.strftime("%Y-%m-%d") else 0


def check_date(d):
    """Date au bon format ET couverte par l'open data (sinon on remplirait les caches pour rien)."""
    if not DATE_RE.match(d):
        raise BadRequest("Date invalide (format attendu AAAA-MM-JJ).")
    dates = donnees.dataset_dates()
    if dates and not (dates[0] <= d <= dates[-1]):
        raise BadRequest(f"Pas de données Max pour le {d} : elles vont du {dates[0]} au {dates[-1]}.")
    if d < today():                      # après minuit, la veille reste dans l'open data jusqu'à sa mise à jour
        raise BadRequest("Cette date est passée : choisis aujourd'hui ou un jour suivant.")
    return d


def today():
    """Date du jour à Paris (AAAA-MM-JJ)."""
    return datetime.now(PARIS_TZ).strftime("%Y-%m-%d")


def coming_dates():
    """Jours de l'open data à partir d'aujourd'hui (calendrier, « Rentable ? »)."""
    t = today()
    return [d for d in donnees.dataset_dates() if d >= t]


def check_time(s, what):
    """Heure HH:MM valide, ou None si vide."""
    if not s:
        return None
    if not TIME_RE.match(s) or int(s.split(":")[0]) > 23 or int(s.split(":")[1]) > 59:
        raise BadRequest(f"Heure {what} invalide (format attendu HH:MM).")
    return int(s.split(":")[0]) * 60 + int(s.split(":")[1])


def _int(qs, name, default, lo, hi):
    try:
        return max(lo, min(hi, int(_p(qs, name, str(default)))))
    except ValueError:
        return default


def _flag(qs, name, default):
    v = _p(qs, name, "1" if default else "0").lower()
    return v not in ("0", "false", "no", "")

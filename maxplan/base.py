"""Petites fonctions partagées : heures, distances, dates, noms de gares normalisés."""

import math
import unicodedata
from datetime import date as Date, timedelta


def normalize(s):
    """Nom comparable : sans accents ni tirets, et « saint » écrit « st » comme dans l'open data
    (« ST BRIEUC », « ST MALO »… ; on doit les trouver en tapant « Saint-Brieuc »)."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = " " + s.lower().replace("-", " ").replace("'", " ").replace("(intramuros)", "").replace(".", "") + " "
    return " ".join(s.replace(" sainte ", " ste ").replace(" saint ", " st ").split())


def hhmm_to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def min_to_hhmm(x):
    x %= 1440
    return f"{x // 60:02d}:{x % 60:02d}"


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def daterange(start, end):
    s, e = Date.fromisoformat(start), Date.fromisoformat(end)
    cur = s
    while cur <= e:
        yield cur.isoformat()
        cur += timedelta(days=1)


WEEKDAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def weekday(d):
    return WEEKDAYS[Date.fromisoformat(d).weekday()]

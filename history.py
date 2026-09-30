# -*- coding: utf-8 -*-
"""Historique des places Max : une « photo » par jour de l'open data, gardée en SQLite.

L'open data ne dit que si un train a des places Max ouvertes (OUI/NON) sur les 30 prochains jours,
pas combien, et il ne garde pas le passé. En photographiant chaque jour les trains ouverts, on
construit un historique : combien de trains à 0 € il y a eu tel jour sur telle liaison, combien de
jours à l'avance ils étaient ouverts, et s'ils ont fini complets avant le départ.

Stockage compact : une ligne par (jour de voyage, train, gare de départ, gare d'arrivée), avec le
premier et le dernier jour où la place était ouverte. ~5 000 lignes par jour de voyage, soit
~2 millions de lignes (~150 Mo) par an.
"""

import os
import sqlite3
import threading
import time
from datetime import date as Date

import config

DB_FILE = os.path.join(config.DATA_DIR, "history.sqlite")
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations(id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS seats(
  travel_date TEXT NOT NULL, train TEXT NOT NULL, o INTEGER NOT NULL, d INTEGER NOT NULL,
  dep INTEGER, arr INTEGER, axe TEXT,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, days_seen INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(travel_date, train, o, d)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS seats_od ON seats(o, d, travel_date);
CREATE TABLE IF NOT EXISTS runs(day TEXT PRIMARY KEY, travel_dates INTEGER, rows INTEGER, seconds REAL);
"""


def _db():
    con = sqlite3.connect(DB_FILE, timeout=30)
    con.executescript(SCHEMA)
    return con


def _station_ids(con, labels):
    con.executemany("INSERT OR IGNORE INTO stations(label) VALUES (?)", [(l,) for l in labels])
    return dict(con.execute("SELECT label, id FROM stations").fetchall())


def last_run():
    with _lock, _db() as con:
        r = con.execute("SELECT day FROM runs ORDER BY day DESC LIMIT 1").fetchone()
        return r[0] if r else None


def snapshot(edges_by_date, today=None):
    """Enregistre la photo du jour. edges_by_date : {date de voyage: [segments OUI]}."""
    today = today or Date.today().isoformat()
    t0 = time.time()
    n = 0
    with _lock, _db() as con:
        if con.execute("SELECT 1 FROM runs WHERE day=?", (today,)).fetchone():
            return 0
        labels = {x for edges in edges_by_date.values() for e in edges for x in (e["o"], e["d"])}
        ids = _station_ids(con, labels)
        for travel_date, edges in edges_by_date.items():
            rows = [(travel_date, e["train"], ids[e["o"]], ids[e["d"]], e["dep"], e["arr"], e.get("axe", ""),
                     today, today) for e in edges]
            con.executemany("""
                INSERT INTO seats(travel_date, train, o, d, dep, arr, axe, first_seen, last_seen)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(travel_date, train, o, d) DO UPDATE SET
                  last_seen=excluded.last_seen, days_seen=seats.days_seen+1
                WHERE seats.last_seen < excluded.last_seen""", rows)
            n += len(rows)
        con.execute("INSERT INTO runs VALUES (?,?,?,?)", (today, len(edges_by_date), n, round(time.time() - t0, 1)))
    return n


def od_stats(origins, targets, since=None):
    """Statistiques passées d'une liaison (trains directs Max) : par jour de voyage déjà écoulé,
    le nombre de trains ouverts à 0 € à un moment ou un autre."""
    with _lock, _db() as con:
        runs = [r[0] for r in con.execute("SELECT day FROM runs ORDER BY day")]
        if not runs:
            return {"days": 0}
        ids = dict(con.execute("SELECT label, id FROM stations").fetchall())
        o_ids = [ids[x] for x in origins if x in ids]
        d_ids = [ids[x] for x in targets if x in ids]
        first_run, today = runs[0], Date.today().isoformat()
        if not o_ids or not d_ids:
            return {"days": 0, "since": first_run}
        q = (f"SELECT travel_date, COUNT(DISTINCT train) FROM seats WHERE o IN ({','.join('?' * len(o_ids))}) "
             f"AND d IN ({','.join('?' * len(d_ids))}) AND travel_date >= ? AND travel_date < ? GROUP BY travel_date")
        per_day = dict(con.execute(q, [*o_ids, *d_ids, since or first_run, today]).fetchall())
    # jours de voyage observés = du premier relevé à hier
    days = []
    d = Date.fromisoformat(since or first_run)
    end = Date.fromisoformat(today)
    while d < end:
        days.append(d.isoformat())
        d = Date.fromordinal(d.toordinal() + 1)
    counts = [per_day.get(x, 0) for x in days]
    by_wd = {}
    for x, c in zip(days, counts):
        by_wd.setdefault(Date.fromisoformat(x).weekday(), []).append(c)
    return {
        "since": first_run, "days": len(days), "days_with_free": sum(1 for c in counts if c),
        "avg_trains": round(sum(counts) / len(counts), 1) if counts else 0,
        "by_weekday": {wd: round(sum(v) / len(v), 1) for wd, v in sorted(by_wd.items())},
    }


def size_info():
    with _lock, _db() as con:
        rows = con.execute("SELECT COUNT(*) FROM seats").fetchone()[0]
        runs = con.execute("SELECT COUNT(*), MIN(day), MAX(day) FROM runs").fetchone()
    return {"rows": rows, "runs": runs[0], "first": runs[1], "last": runs[2],
            "mb": round(os.path.getsize(DB_FILE) / 1e6, 1) if os.path.exists(DB_FILE) else 0}

"""Tâches de fond : préchauffage au démarrage et relevé quotidien de l'historique des places Max."""

import json
import time
import urllib.request

from maxplan import historique
from maxplan.moteur import donnees
from maxplan.ter.navitia import navitia
from maxplan.api.trajets import DAY_POOL, _EDGES, annotate, edges_for, geocode_many


def warmup():
    """Au démarrage : récupère la liste des gares et les géocode (sert à « gare la plus proche »)."""
    try:
        stations = donnees.all_stations()
        navitia.known = set(stations)
        geocode_many(stations)
        list(DAY_POOL.map(edges_for, donnees.dataset_dates()))   # places Max des 30 jours (calendrier)
        print(f"    Préchauffage terminé : {len(stations)} gares Max géocodées.", flush=True)
    except Exception as e:
        print("    Préchauffage incomplet :", e, flush=True)


def dataset_processed():
    """Horodatage de la dernière mise à jour du jeu de données tgvmax par la SNCF."""
    with urllib.request.urlopen(donnees.API, timeout=30) as r:
        m = json.load(r).get("metas", {}).get("default", {})
    return m.get("data_processed") or m.get("modified")


def history_loop():
    """Guette la mise à jour de l'open data (toutes les 15 min, une requête légère sur ses
    métadonnées) : dès qu'elle arrive, les places du jour sont rechargées et la photo quotidienne de
    l'historique est prise. Les heures de mise à jour sont gardées (statistiques). Filet de sécurité :
    photo à 8 h UTC si aucune mise à jour n'a été vue."""
    while True:
        try:
            today = time.strftime("%Y-%m-%d", time.gmtime())
            fresh = False
            try:
                processed = dataset_processed()
                if processed and historique.record_update(processed):
                    fresh = True
                    _EDGES.clear()                           # nouvelles places : on les relit
                    donnees._DATES = (0.0, [])
                    print(f"    Open data Max mise à jour par la SNCF : {processed}.", flush=True)
            except Exception:
                pass
            if (fresh or time.gmtime().tm_hour >= 8) and historique.last_run() != today:
                data = {}
                for d in donnees.dataset_dates():
                    edges = annotate(donnees.fetch_oui_edges(d), d)
                    _EDGES[d] = (time.time(), edges)       # rafraîchit le cache au passage
                    data[d] = edges
                n = historique.snapshot(data, today)
                print(f"    Historique : {n} places Max enregistrées ({today}).", flush=True)
        except Exception as e:
            print("    Historique : relevé impossible pour l'instant :", e, flush=True)
        time.sleep(900)

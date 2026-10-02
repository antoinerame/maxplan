"""MaxPlan : trains à 0 € Max Jeune / Max Senior, correspondances et compléments TER.

Organisation du code :
  moteur/   places Max (open data), gares (jumelles, annexes, Paris) et recherche des trajets Max
  ter/      horaires locaux TER et cars (GTFS), API SNCF de secours, prix et tarifs officiels
  api/      un module par point d'API (recherche, explorer, calendrier, rentable, infos, gares, retours)
  serveur   serveur HTTP : routes, fichiers statiques, cache, limites de requêtes
  taches    tâches de fond : préchauffage, historique quotidien des places Max
"""

VERSION = "3.9"

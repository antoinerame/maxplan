# -*- coding: utf-8 -*-
"""Estimation transparente du prix des segments payants, selon le profil de l'utilisateur.

Aucune API publique ne donne le tarif TER exact : le prix est ESTIMÉ à partir de la distance,
tronçon par tronçon, puis chaque tronçon reçoit la réduction qui s'y applique :
  - TGV / INTERCITÉS (grandes lignes) : −30 % « Max Avantage » si abonné Max Jeune ou Max Senior ;
  - TER : la réduction que l'utilisateur a déclarée pour la RÉGION du tronçon
    (carte jeune régionale, abonnement… — chaque région a ses propres offres).
Le prix réel reste celui affiché par SNCF Connect.
"""

import math

from maxplan import regions

MIN_FARE = 2.0              # prix plancher d'un trajet
REGIONAL_COACH_FARE = 3.0   # car régional : la plupart des réseaux ont un tarif unique de 2 à 4 €

GRANDES_LIGNES = ("tgv", "inoui", "intercit", "ouigo", "lyria", "eurostar", "ice ")
SUBSCRIPTIONS = ("jeune", "senior", "none")


def normal_fare(km):
    """Tarif normal TER (plein tarif 2de classe) estimé pour un billet de `km` km.
    Forme « a + b × distance » des barèmes TER, dégressive avec la distance ; calée sur des prix
    publiés (Saint-Étienne–Lyon, ~50 km à vol d'oiseau : 14,20 € plein tarif sur SNCF Connect en 2026,
    soit 7,10 € avec une carte −50 %)."""
    km = max(0.0, km)
    fare = 2.4 + 0.236 * min(km, 64)
    if km > 64:
        fare += 0.206 * (min(km, 150) - 64)
    if km > 150:
        fare += 0.17 * (km - 150)
    return max(MIN_FARE, fare)


def _up(x):
    """Arrondi au décime supérieur, comme les réductions TER (CGV TER)."""
    return math.ceil(round(x * 10, 6)) / 10


def _is_grande_ligne(mode):
    m = (mode or "").lower() + " "
    return any(k in m for k in GRANDES_LIGNES)


def estimate(sections, prefs):
    """sections : [{mode, dist_km, lat, lon}] ; prefs : {"sub": ..., "ter": {code_region: pct}}."""
    # Un billet TER se paie sur la distance totale (tarif dégressif) ; chaque tronçon garde la
    # réduction de SA région, pondérée par sa longueur. Les réductions s'appliquent au tarif normal.
    km_sum = disc_km = flat = 0.0
    parts = []
    for s in sections:
        km = max(0.0, s.get("dist_km", 0))
        if s.get("flat_fare"):
            # cars régionaux (ZOU!, liO, Aléop…) : tarif unique par trajet, pas au kilomètre
            flat += REGIONAL_COACH_FARE
            parts.append({"kind": "car", "mode": s.get("network") or s.get("mode")})
            continue
        if _is_grande_ligne(s.get("mode")):
            pct = 30 if prefs["sub"] in ("jeune", "senior") else 0
            parts.append({"kind": "gl", "mode": s.get("mode"), "pct": pct})
        else:
            code = regions.locate(s.get("lat"), s.get("lon"))
            pct = int(prefs["ter"].get(code, 0)) if code else 0
            parts.append({"kind": "ter", "region": code, "pct": pct})
        km_sum += km
        disc_km += km * (1 - pct / 100)

    if km_sum <= 0 and not flat:
        return {"price": 0, "base": 0, "discount_pct": 0, "label": "prix inconnu",
                "regions": [], "distance_km": 0, "estimated": True}

    ratio = disc_km / km_sum if km_sum else 1.0      # part restant à payer
    base_total = normal_fare(km_sum) if km_sum else 0.0
    price = 0.0 if (km_sum and ratio < 0.005) else (max(0.5, _up(base_total * ratio)) if km_sum else 0.0)
    price = round(price + flat, 1)
    base_total += flat

    # libellé lisible : réseaux + réductions appliquées
    labels, seen = [], set()
    for p in parts:
        if p["kind"] == "car":
            key = ("car", p["mode"])
            txt = f"{p['mode']} ≈ {REGIONAL_COACH_FARE:g} € (car régional, tarif unique)"
        elif p["kind"] == "gl":
            key = ("gl", p["pct"])
            txt = f"{p['mode']} −{p['pct']} % (Max Avantage)" if p["pct"] else f"{p['mode']} plein tarif"
        else:
            key = ("ter", p["region"], p["pct"])
            net = regions.REGIONS.get(p["region"], (None, "TER"))[1] if p["region"] else "TER"
            txt = f"{net} −{p['pct']} % sur le tarif normal" if p["pct"] else f"{net} plein tarif"
        if key not in seen:
            seen.add(key)
            labels.append(txt)

    region_names = []
    for p in parts:
        n = regions.name(p.get("region"))
        if n and n not in region_names:
            region_names.append(n)

    return {
        "price": price,
        "base": _up(base_total),
        "discount_pct": round((1 - ratio) * 100),
        "label": " · ".join(labels),
        "regions": region_names,
        "distance_km": round(sum(s.get("dist_km", 0) for s in sections)),
        "estimated": True,
    }


def prefs_from_qs(qs):
    """Profil depuis les paramètres : ?sub=jeune|senior|none&ter_disc=84:50,93:25
    (compatibilité : ?max_jeune=0 / ?illico=1&illico_pct=50)."""
    sub = (qs.get("sub", [""])[0] or "").lower()
    if sub not in SUBSCRIPTIONS:
        sub = "none" if qs.get("max_jeune", ["1"])[0] in ("0", "false") else "jeune"

    ter = {}
    raw = qs.get("ter_disc", [""])[0]
    for item in raw.split(","):
        if ":" in item:
            code, pct = item.split(":", 1)
            code = code.strip()
            if code in regions.REGIONS:
                try:
                    ter[code] = max(0, min(100, int(float(pct))))
                except ValueError:
                    pass
    if not raw and qs.get("illico", ["0"])[0] not in ("0", "false", ""):
        try:
            ter["84"] = max(0, min(100, int(float(qs.get("illico_pct", ["50"])[0]))))
        except ValueError:
            ter["84"] = 50
    return {"sub": sub, "ter": ter}

# -*- coding: utf-8 -*-
"""Estimation transparente du prix des segments payants, selon le profil de l'utilisateur.

Aucune API publique ne donne le tarif TER exact : le prix est ESTIMÉ à partir de la distance,
tronçon par tronçon, puis chaque tronçon reçoit la réduction qui s'y applique :
  - TGV / INTERCITÉS (grandes lignes) : −30 % « Max Avantage » si abonné Max Jeune ou Max Senior ;
  - TER : la réduction que l'utilisateur a déclarée pour la RÉGION du tronçon
    (carte jeune régionale, abonnement… — chaque région a ses propres offres).
Le prix réel reste celui affiché par SNCF Connect.
"""

import regions

RATE_PER_KM = 0.17          # €/km, ordre de grandeur d'un billet TER plein tarif
MIN_FARE = 2.0              # prix plancher d'un trajet
ROUND = 0.5
GRANDES_LIGNES = ("tgv", "inoui", "intercit", "ouigo", "lyria", "eurostar", "ice ")
SUBSCRIPTIONS = ("jeune", "senior", "none")


def _round(x):
    return round(x / ROUND) * ROUND


def _is_grande_ligne(mode):
    m = (mode or "").lower() + " "
    return any(k in m for k in GRANDES_LIGNES)


def estimate(sections, prefs):
    """sections : [{mode, dist_km, lat, lon}] ; prefs : {"sub": ..., "ter": {code_region: pct}}."""
    base_sum = disc_sum = 0.0
    parts = []
    for s in sections:
        base = max(0.0, s.get("dist_km", 0)) * RATE_PER_KM
        if _is_grande_ligne(s.get("mode")):
            pct = 30 if prefs["sub"] in ("jeune", "senior") else 0
            parts.append({"kind": "gl", "mode": s.get("mode"), "pct": pct})
        else:
            code = regions.locate(s.get("lat"), s.get("lon"))
            pct = int(prefs["ter"].get(code, 0)) if code else 0
            parts.append({"kind": "ter", "region": code, "pct": pct})
        base_sum += base
        disc_sum += base * (1 - pct / 100)

    if base_sum <= 0:
        return {"price": 0, "base": 0, "discount_pct": 0, "label": "prix inconnu",
                "regions": [], "distance_km": 0, "estimated": True}

    ratio = disc_sum / base_sum                      # part restant à payer
    base_total = max(MIN_FARE, base_sum)
    price = 0.0 if ratio < 0.005 else max(0.5, _round(base_total * ratio))

    # libellé lisible : réseaux + réductions appliquées
    labels, seen = [], set()
    for p in parts:
        if p["kind"] == "gl":
            key = ("gl", p["pct"])
            txt = f"{p['mode']} −{p['pct']} % (Max Avantage)" if p["pct"] else f"{p['mode']} plein tarif"
        else:
            key = ("ter", p["region"], p["pct"])
            net = regions.REGIONS.get(p["region"], (None, "TER"))[1] if p["region"] else "TER"
            txt = f"{net} −{p['pct']} %" if p["pct"] else f"{net} plein tarif"
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
        "base": _round(base_total),
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

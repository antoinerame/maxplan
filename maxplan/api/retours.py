"""Retours des visiteurs (bouton « Signaler ») : enregistrement et page d'administration."""

import json
import os
import threading
import time

from maxplan import VERSION
from maxplan import config
from maxplan.api.commun import BadRequest


FEEDBACK_FILE = os.path.join(config.DATA_DIR, "feedback.jsonl")
FEEDBACK_KINDS = {"bug": "Problème", "idee": "Idée / amélioration", "donnees": "Trajet ou prix faux", "autre": "Autre"}
_FEEDBACK_LOCK = threading.Lock()


def save_feedback(data):
    """Enregistre un signalement (une ligne JSON) dans le dossier de données."""
    if not isinstance(data, dict):
        raise BadRequest("Message illisible.")
    msg = str(data.get("message") or "").strip()
    if len(msg) < 3:
        raise BadRequest("Écris quelques mots pour décrire le problème ou l'idée.")
    kind = str(data.get("kind") or "autre")
    rec = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind if kind in FEEDBACK_KINDS else "autre",
        "message": msg[:2000],
        "contact": str(data.get("contact") or "").strip()[:200],
        "page": str(data.get("page") or "")[:600],
        "version": VERSION,
    }
    with _FEEDBACK_LOCK:
        if os.path.exists(FEEDBACK_FILE) and os.path.getsize(FEEDBACK_FILE) > 5_000_000:
            raise BadRequest("La boîte à messages est pleine pour le moment, réessaie plus tard.")
        with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True}


def feedback_page():
    import html
    rows = []
    if os.path.exists(FEEDBACK_FILE):
        with open(FEEDBACK_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    items = "".join(
        f"<article><header><b>{html.escape(FEEDBACK_KINDS.get(r.get('kind'), 'Autre'))}</b>"
        f"<time>{html.escape(r.get('ts', ''))}</time></header><p>{html.escape(r.get('message', ''))}</p>"
        + (f"<small>Contact : {html.escape(r['contact'])}</small>" if r.get("contact") else "")
        + (f"<small>Page : <a href=\"{html.escape(r['page'])}\">{html.escape(r['page'])}</a></small>"
           if str(r.get("page", "")).startswith("/") and not str(r.get("page", "")).startswith("//") else "")
        + "</article>" for r in reversed(rows))
    return ("<!DOCTYPE html><html lang=fr><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            "<meta name=robots content=noindex><title>Retours · MaxPlan</title><style>"
            "body{font:15px/1.5 system-ui,sans-serif;max-width:760px;margin:0 auto;padding:24px 16px;background:#F2F2F7;color:#0C131F}"
            "article{background:#fff;border-radius:12px;padding:12px 16px;margin:10px 0;box-shadow:0 1px 3px rgba(0,0,0,.08)}"
            "header{display:flex;justify-content:space-between;gap:10px}time{color:#676D7E;font-size:13px}"
            "p{white-space:pre-wrap;margin:6px 0}small{display:block;color:#676D7E;word-break:break-all}"
            f"</style><h1>Retours des visiteurs ({len(rows)})</h1>"
            + (items or "<p>Aucun retour pour l'instant.</p>") + "</html>")

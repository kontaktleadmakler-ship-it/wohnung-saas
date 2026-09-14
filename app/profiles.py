"""Lädt Suchprofile aus profiles.json. Bewusst simpel gehalten (lt. Auftrag:
"leicht erweiterbar") - jedes Profil ist ein dict, neue Felder brauchen
keine Migration wie bei einer DB-Tabelle."""
from __future__ import annotations

import json
import logging
import os

from . import config

log = logging.getLogger("profiles")

REQUIRED_FIELDS = ("name", "max_price", "min_size", "min_rooms")


def load_profiles() -> list[dict]:
    if not os.path.exists(config.PROFILES_PATH):
        log.warning("Profildatei %s nicht gefunden - keine Profile aktiv", config.PROFILES_PATH)
        return []

    with open(config.PROFILES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    profiles = []
    for p in data:
        if not all(k in p for k in REQUIRED_FIELDS):
            log.warning("Profil übersprungen (Pflichtfelder fehlen): %s", p)
            continue
        p.setdefault("plz_list", [])
        p.setdefault("radius_km", None)
        p.setdefault("must_have", [])
        p.setdefault("nice_to_have", [])
        p.setdefault("sources", ["kleinanzeigen", "immoscout24", "immowelt", "wg_gesucht"])
        p.setdefault("locations", [])
        p.setdefault("active", True)
        profiles.append(p)

    log.info("%d Profil(e) geladen (%d aktiv)", len(profiles), sum(1 for p in profiles if p["active"]))
    return [p for p in profiles if p["active"]]

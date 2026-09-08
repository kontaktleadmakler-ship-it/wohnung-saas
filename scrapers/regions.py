# scrapers/regions.py
BUNDESLAENDER = {
    "BW": "Baden-Württemberg", "BY": "Bayern", "BE": "Berlin", "BB": "Brandenburg",
    "HB": "Bremen", "HH": "Hamburg", "HE": "Hessen", "MV": "Mecklenburg-Vorpommern",
    "NI": "Niedersachsen", "NW": "Nordrhein-Westfalen", "RP": "Rheinland-Pfalz",
    "SL": "Saarland", "SN": "Sachsen", "ST": "Sachsen-Anhalt",
    "SH": "Schleswig-Holstein", "TH": "Thüringen",
}

NATIONWIDE = "DE"  # Sentinel: kein regionales Filtern, komplettes Bundesgebiet

# Kuratierte Städteliste je Bundesland, für Plattformen ohne "ganz DE"-Suchparameter
# (SUPPORTS_NATIONWIDE = False), z.B. meinestadt.de, WG-Gesucht.
# Bewusst grob (1-3 Großstädte je Land) -- Ziel ist Näherung an bundesweite Abdeckung,
# nicht Vollständigkeit; bei Bedarf pro Land erweiterbar.
CITY_SAMPLES = {
    "BW": ["stuttgart", "mannheim", "karlsruhe"],
    "BY": ["muenchen", "nuernberg", "augsburg"],
    "BE": ["berlin"],
    "BB": ["potsdam", "cottbus"],
    "HB": ["bremen"],
    "HH": ["hamburg"],
    "HE": ["frankfurt-am-main", "wiesbaden", "kassel"],
    "MV": ["rostock", "schwerin"],
    "NI": ["hannover", "braunschweig", "oldenburg"],
    "NW": ["koeln", "duesseldorf", "dortmund", "essen"],
    "RP": ["mainz", "ludwigshafen-am-rhein", "koblenz"],
    "SL": ["saarbruecken"],
    "SN": ["leipzig", "dresden", "chemnitz"],
    "ST": ["magdeburg", "halle-saale"],
    "SH": ["kiel", "luebeck"],
    "TH": ["erfurt", "jena"],
}


def resolve_region_codes(region_codes: list[str]) -> list[str]:
    """Leere Liste oder enthält 'DE' -> bundesweit (eine Region: NATIONWIDE)."""
    if not region_codes or NATIONWIDE in region_codes:
        return [NATIONWIDE]
    return [r for r in region_codes if r in BUNDESLAENDER]

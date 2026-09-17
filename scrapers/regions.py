BUNDESLAENDER={
    'BE':'Berlin','BB':'Brandenburg','HH':'Hamburg','HB':'Bremen',
    'BW':'Baden-Württemberg','BY':'Bayern','HE':'Hessen','MV':'Mecklenburg-Vorpommern',
    'NI':'Niedersachsen','NW':'Nordrhein-Westfalen','RP':'Rheinland-Pfalz','SL':'Saarland',
    'SN':'Sachsen','ST':'Sachsen-Anhalt','SH':'Schleswig-Holstein','TH':'Thüringen'
}
NATIONWIDE='DE'

# Große Städte je Bundesland liefern belastbare Suchanker, wenn kein einzelner
# Landkreis/Stadtbezirk gewählt wurde; so bleiben regionale Profile praktisch nutzbar.
STATE_CITY_SAMPLES={
    'BE':['Berlin'],
    'BB':['Potsdam','Cottbus','Brandenburg an der Havel'],
    'HH':['Hamburg'],
    'HB':['Bremen','Bremerhaven'],
    'BW':['Stuttgart','Karlsruhe','Mannheim'],
    'BY':['München','Nürnberg','Augsburg'],
    'HE':['Frankfurt am Main','Wiesbaden','Kassel'],
    'MV':['Rostock','Schwerin','Neubrandenburg'],
    'NI':['Hannover','Braunschweig','Oldenburg'],
    'NW':['Köln','Düsseldorf','Dortmund'],
    'RP':['Mainz','Koblenz','Ludwigshafen am Rhein'],
    'SL':['Saarbrücken','Neunkirchen','Homburg'],
    'SN':['Dresden','Leipzig','Chemnitz'],
    'ST':['Magdeburg','Halle (Saale)','Dessau-Roßlau'],
    'SH':['Kiel','Lübeck','Flensburg'],
    'TH':['Erfurt','Jena','Gera'],
}

# Häufig in Profilen verwendete Bezirke/Stadtteile. Für die Portal-Suche
# werden sie auf eine echte Stadt zurückgeführt; der Originalwert bleibt im
# Profil-Matching erhalten.
LOCATION_CITY_ALIASES = {
    # Berlin
    **{k: "Berlin" for k in [
        "mitte", "friedrichshain", "kreuzberg", "friedrichshain-kreuzberg",
        "pankow", "prenlauer berg", "neukölln", "neukoelln", "tempelhof",
        "schöneberg", "schoeneberg", "tempelhof-schöneberg",
        "charlottenburg", "wilmersdorf", "charlottenburg-wilmersdorf",
        "spandau", "reinickendorf", "lichtenberg", "marzahn",
        "marzahn-hellersdorf", "hellersdorf", "treptow", "köpenick",
        "treptow-köpenick", "steglitz", "zehlendorf", "steglitz-zehlendorf",
        "moabit", "wedding", "tiergarten", "kreuzberg", "schöneberg",
    ]},
    # München
    **{k: "München" for k in ["münchen", "munchen", "maxvorstadt", "schwabing", "sendling", "glockenbachviertel", "haimhausen"]},
    # Hamburg
    **{k: "Hamburg" for k in ["hamburg", "altona", "eimsbüttel", "eimsbuettel", "wandsbek", "harburg", "hamburg-nord"]},
    # Köln
    **{k: "Köln" for k in ["köln", "koeln", "innenstadt", "ehrenfeld", "deutz", "lindenthal", "nippes"]},
    # Frankfurt
    **{k: "Frankfurt am Main" for k in ["frankfurt", "frankfurt am main", "sachsenhausen", "bornheim", "bockenheim"]},
}

# Basis-Image bringt Chromium + alle System-Abhängigkeiten bereits mit
# (als root im Image-Build installiert -- deshalb kein "playwright install
# --with-deps" mehr nötig, das auf Render sonst mit "su: Authentication
# failure" fehlschlägt, weil Renders native Python-Runtime keinen Root-
# Zugriff erlaubt).
#
# WICHTIG: Der Versions-Tag hier muss zur "playwright"-Version in
# requirements.txt passen, sonst findet Python das Browser-Binary nicht.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

WORKDIR /app

# Erst nur requirements.txt kopieren, damit der pip-Install-Layer gecacht
# werden kann, solange sich nur der Anwendungscode ändert.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Restlichen Code kopieren
COPY . .

# Wird von render.yaml pro Service per "dockerCommand" überschrieben
# (web -> gunicorn, cron -> python scraper.py --once). Dieser CMD ist nur
# der Fallback, falls das Image ohne dockerCommand gestartet wird.
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "120"]

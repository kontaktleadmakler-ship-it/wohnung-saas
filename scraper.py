import sqlite3
import hashlib
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# =========================
# CUSTOMERS
# =========================
customers = [
    {"name": "K1", "max": 600, "rooms": 1.5, "min_size": 30},
    {"name": "K2", "max": 1500, "rooms": 4, "min_size": 80},
    {"name": "K3", "max": 1200, "rooms": 2, "min_size": 50},
    {"name": "K4", "max": 1800, "rooms": 3, "min_size": 70},
]

# =========================
# HELPERS
# =========================
def uid(text):
    return hashlib.md5(text.encode()).hexdigest()

def price(t):
    m = re.search(r"([\d\.]+)\s?€", t)
    return int(m.group(1).replace(".", "")) if m else 0

def rooms(t):
    m = re.search(r"(\d+(?:,\d+)?)\s?Zi", t)
    return float(m.group(1).replace(",", ".")) if m else 0

def size(t):
    m = re.search(r"(\d+(?:,\d+)?)\s?m²", t)
    return float(m.group(1).replace(",", ".")) if m else 0


# =========================
# SCORING
# =========================
def score(l, c):
    s = 0

    if l["price"] <= c["max"]:
        s += 40
    if l["rooms"] >= c["rooms"]:
        s += 30
    if l["size"] >= c["min_size"]:
        s += 20
    if l["price"] < c["max"] * 0.8:
        s += 10

    return min(s, 100)


def best_match(l):
    best = ""
    best_score = 0

    for c in customers:
        s = score(l, c)
        if s > best_score:
            best_score = s
            best = c["name"]

    return best, best_score


# =========================
# DB
# =========================
def save(l):

    conn = sqlite3.connect("leads.db")
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id TEXT PRIMARY KEY,
        title TEXT,
        price INTEGER,
        rooms REAL,
        size REAL,
        link TEXT,
        source TEXT,
        customer TEXT,
        score INTEGER
    )
    """)

    cur.execute("""
    INSERT OR REPLACE INTO leads VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        l["id"],
        l["title"],
        l["price"],
        l["rooms"],
        l["size"],
        l["link"],
        l["source"],
        l["customer"],
        l["score"]
    ))

    conn.commit()
    conn.close()


# =========================
# IMMOWELT
# =========================
def scrape_immowelt():
    url = "https://www.immowelt.de/liste/berlin/wohnungen/mieten"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(url, timeout=60000)
        page.wait_for_timeout(5000)

        soup = BeautifulSoup(page.content(), "html.parser")

        for a in soup.find_all("a"):
            text = a.get_text(" ", strip=True)

            if "€" not in text:
                continue

            link = a.get("href") or ""
            if link.startswith("/"):
                link = "https://www.immowelt.de" + link

            lead = {
                "id": uid(text + link),
                "title": text[:120],
                "price": price(text),
                "rooms": rooms(text),
                "size": size(text),
                "link": link,
                "source": "immowelt"
            }

            lead["customer"], lead["score"] = best_match(lead)
            save(lead)

        browser.close()


# =========================
# WG-GESUCHT
# =========================
def scrape_wg():
    url = "https://www.wg-gesucht.de/wohnungen-in-Berlin.8.2.1.0.html"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto(url, timeout=60000)
        page.wait_for_timeout(5000)

        soup = BeautifulSoup(page.content(), "html.parser")

        for a in soup.find_all("a"):
            text = a.get_text(" ", strip=True)

            if "€" not in text:
                continue

            link = a.get("href") or ""
            if link.startswith("/"):
                link = "https://www.wg-gesucht.de" + link

            lead = {
                "id": uid(text + link),
                "title": text[:120],
                "price": price(text),
                "rooms": rooms(text),
                "size": size(text),
                "link": link,
                "source": "wg-gesucht"
            }

            lead["customer"], lead["score"] = best_match(lead)
            save(lead)

        browser.close()


# =========================
# RUN SCRAPER
# =========================
def run_scraper():
    print("🚀 SCRAPER START")

    scrape_immowelt()
    scrape_wg()

    print("✅ DONE")

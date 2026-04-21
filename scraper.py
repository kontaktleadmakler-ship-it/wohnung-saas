import asyncio
import sqlite3
import hashlib
import re
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

# =========================
# 👤 CUSTOMERS
# =========================
customers = [
    {"name":"K1","max":600,"rooms":1.5,"min_size":30},
    {"name":"K2","max":1500,"rooms":4,"min_size":80},
    {"name":"K3","max":1200,"rooms":2,"min_size":50},
    {"name":"K4","max":1800,"rooms":3,"min_size":70},
]

# =========================
# 🧠 HELPERS
# =========================
def uid(t):
    return hashlib.md5(t.encode()).hexdigest()

def price(t):
    m = re.search(r"([\d\.]+)\s?€", t)
    return int(m.group(1).replace(".","")) if m else 0

def rooms(t):
    m = re.search(r"(\d+(?:,\d+)?)\s?Zi", t)
    return float(m.group(1).replace(",", ".")) if m else 0

def size(t):
    m = re.search(r"(\d+(?:,\d+)?)\s?m²", t)
    return float(m.group(1).replace(",", ".")) if m else 0

# =========================
# 🧠 SCORING
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
# 💾 DB
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
# 🟡 IMMOWELT
# =========================
async def immowelt(page):

    await page.goto("https://www.immowelt.de/liste/berlin/wohnungen/mieten")
    await page.wait_for_timeout(5000)

    soup = BeautifulSoup(await page.content(), "html.parser")

    for d in soup.find_all("div"):

        text = d.get_text(" ", strip=True)

        if "€" not in text:
            continue

        a = d.find("a")
        link = a.get("href") if a else ""

        lead = {
            "id": uid(text + (link or "")),
            "title": text[:120],
            "price": price(text),
            "rooms": rooms(text),
            "size": size(text),
            "link": link,
            "source": "immowelt"
        }

        lead["customer"], lead["score"] = best_match(lead)

        save(lead)

# =========================
# 🟣 WG GESUCHT
# =========================
async def wg(page):

    await page.goto("https://www.wg-gesucht.de/wohnungen-in-Berlin.8.2.1.0.html")
    await page.wait_for_timeout(6000)

    soup = BeautifulSoup(await page.content(), "html.parser")

    for a in soup.find_all("a"):

        text = a.get_text(" ", strip=True)

        if "€" not in text:
            continue

        link = "https://www.wg-gesucht.de" + (a.get("href") or "")

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

# =========================
# 🚀 MAIN
# =========================
async def main():

    async with async_playwright() as p:

        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        while True:

            print("🔄 SCRAPING V5...")

            await immowelt(page)
            await wg(page)

            await asyncio.sleep(180)

asyncio.run(main())
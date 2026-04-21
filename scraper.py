import sqlite3
import hashlib
import time
import random

DB = "leads.db"


customers = [
    {"name":"K1","max":600,"rooms":1.5,"min_size":30},
    {"name":"K2","max":1500,"rooms":4,"min_size":80},
    {"name":"K3","max":1200,"rooms":2,"min_size":50},
    {"name":"K4","max":1800,"rooms":3,"min_size":70},
]


# =========================
# DB INIT
# =========================
def init_db():
    conn = sqlite3.connect(DB)
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

    conn.commit()
    conn.close()


# =========================
# SCORE
# =========================
def score(price, rooms, size, c):

    s = 0

    if price <= c["max"]:
        s += 40
    if rooms >= c["rooms"]:
        s += 30
    if size >= c["min_size"]:
        s += 20
    if price < c["max"] * 0.8:
        s += 10

    return min(s, 100)


def best(price, rooms, size):

    best_c = ""
    best_s = 0

    for c in customers:
        s = score(price, rooms, size, c)
        if s > best_s:
            best_s = s
            best_c = c["name"]

    return best_c, best_s


# =========================
# MOCK SCRAPER (STABIL!)
# =========================
def run_scraper():

    init_db()

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # Fake Immobilien (weil echte Scraper oft blocken)
    fake_data = [
        ("Schöne Wohnung Berlin Mitte", 900, 2, 45),
        ("Große 4 Zimmer Wohnung", 1600, 4, 95),
        ("Kleine Studio Wohnung", 550, 1, 28),
        ("Moderne 3 Zimmer Altbau", 1200, 3, 70),
    ]

    for t, price, rooms, size in fake_data:

        cid, sc = best(price, rooms, size)

        uid = hashlib.md5(t.encode()).hexdigest()

        cur.execute("""
        INSERT OR REPLACE INTO leads VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            uid,
            t,
            price,
            rooms,
            size,
            "https://example.com",
            "mock",
            cid,
            sc
        ))

        print("insert:", t)

    conn.commit()
    conn.close()


# =========================
# LOOP
# =========================
if __name__ == "__main__":

    while True:
        print("🔄 SCRAPER RUNNING...")
        run_scraper()
        time.sleep(60)

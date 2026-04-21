import os
import time
import hashlib
import psycopg2
import random

DATABASE_URL = os.environ.get("DATABASE_URL")


customers = [
    {"name":"K1","max":600,"rooms":1.5,"min_size":30},
    {"name":"K2","max":1500,"rooms":4,"min_size":80},
    {"name":"K3","max":1200,"rooms":2,"min_size":50},
]


def db():
    return psycopg2.connect(DATABASE_URL, sslmode='require')


def score(price, rooms, size, c):
    s = 0
    if price <= c["max"]:
        s += 40
    if rooms >= c["rooms"]:
        s += 30
    if size >= c["min_size"]:
        s += 20
    return s


def best(price, rooms, size):
    best_c = ""
    best_s = 0

    for c in customers:
        s = score(price, rooms, size, c)
        if s > best_s:
            best_s = s
            best_c = c["name"]

    return best_c, best_s


def run():

    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id TEXT PRIMARY KEY,
        title TEXT,
        price INT,
        rooms FLOAT,
        size FLOAT,
        link TEXT,
        source TEXT,
        customer TEXT,
        score INT
    )
    """)

    fake = [
        ("Berlin Mitte Luxus", 900, 2, 50),
        ("Altbau Wohnung", 1300, 3, 75),
        ("Studenten Wohnung", 500, 1, 25),
    ]

    for t, price, rooms, size in fake:

        cid, sc = best(price, rooms, size)

        uid = hashlib.md5(t.encode()).hexdigest()

        cur.execute("""
        INSERT INTO leads VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (id) DO NOTHING
        """, (
            uid, t, price, rooms, size,
            "https://example.com",
            "worker",
            cid,
            sc
        ))

        print("inserted:", t)

    conn.commit()
    conn.close()


while True:
    print("SCRAPER RUNNING...")
    run()
    time.sleep(30)

import sqlite3

def init_db():
    conn = sqlite3.connect("leads.db")
    cur = conn.cursor()

    # USERS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        password TEXT
    )
    """)

    # LEADS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id TEXT PRIMARY KEY,
        title TEXT,
        price INTEGER,
        rooms REAL,
        size REAL,
        link TEXT,
        source TEXT
    )
    """)

    # Demo User (nur beim ersten Start)
    cur.execute("SELECT * FROM users WHERE username='admin'")
    if not cur.fetchone():
        cur.execute("INSERT INTO users (username, password) VALUES (?,?)",
                    ("admin", "1234"))

    conn.commit()
    conn.close()
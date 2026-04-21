import os
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    if not DATABASE_URL:
        print("❌ DATABASE_URL fehlt")
        return None

    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    conn = get_conn()
    if not conn:
        return

    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id SERIAL PRIMARY KEY,
            title TEXT,
            price TEXT,
            rooms TEXT,
            size TEXT,
            location TEXT,
            url TEXT UNIQUE
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("✅ DB ready")

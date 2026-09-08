import os
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL fehlt")
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Profile werden jetzt in der DB verwaltet statt hart im Code (customers-Liste)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            min_price INT DEFAULT 0,
            max_price INT NOT NULL,
            min_rooms FLOAT DEFAULT 0,
            max_rooms FLOAT,
            min_size FLOAT DEFAULT 0,
            districts TEXT,          -- kommagetrennte Liste, z.B. "Mitte,Kreuzberg,Neukölln"
            keywords_exclude TEXT,   -- kommagetrennte Ausschlussbegriffe, z.B. "WG,Tausch,Zwischenmiete"
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Listings: eine Zeile pro real gefundenem Inserat, dedupliziert über external_id/url
    cur.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id SERIAL PRIMARY KEY,
            external_id TEXT UNIQUE,
            title TEXT,
            price NUMERIC,
            rooms FLOAT,
            size FLOAT,
            location TEXT,
            url TEXT UNIQUE,
            source TEXT,
            first_seen TIMESTAMP DEFAULT NOW(),
            last_seen TIMESTAMP DEFAULT NOW()
        );
    """)

    # Matches: n:m zwischen Listings und Profilen statt einer einzelnen "customer"-Spalte,
    # damit ein Inserat mehrere Profile gleichzeitig treffen kann
    cur.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            listing_id INT REFERENCES listings(id) ON DELETE CASCADE,
            profile_id INT REFERENCES profiles(id) ON DELETE CASCADE,
            score INT NOT NULL,
            notified BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (listing_id, profile_id)
        );
    """)

    conn.commit()
    cur.close()
    conn.close()


def get_active_profiles():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM profiles WHERE active = TRUE;")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def upsert_listing(external_id, title, price, rooms, size, location, url, source):
    """Legt ein Listing an oder aktualisiert last_seen. Gibt (listing_id, is_new) zurück."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO listings (external_id, title, price, rooms, size, location, url, source)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (external_id) DO UPDATE SET last_seen = NOW()
        RETURNING id, (xmax = 0) AS is_new;
    """, (external_id, title, price, rooms, size, location, url, source))
    listing_id, is_new = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return listing_id, is_new


def save_match(listing_id, profile_id, score):
    """Speichert/aktualisiert einen Match-Score. Gibt True zurück, wenn er noch nicht benachrichtigt wurde."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO matches (listing_id, profile_id, score)
        VALUES (%s,%s,%s)
        ON CONFLICT (listing_id, profile_id) DO UPDATE SET score = EXCLUDED.score
        RETURNING notified;
    """, (listing_id, profile_id, score))
    notified = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return not notified


def mark_notified(listing_id, profile_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE matches SET notified = TRUE WHERE listing_id=%s AND profile_id=%s;",
        (listing_id, profile_id),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_dashboard_rows(min_score=0, profile_id=None):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    query = """
        SELECT l.id, l.title, l.price, l.rooms, l.size, l.location, l.url, l.source,
               m.score, p.name AS profile_name, l.first_seen
        FROM matches m
        JOIN listings l ON l.id = m.listing_id
        JOIN profiles p ON p.id = m.profile_id
        WHERE m.score >= %s
    """
    params = [min_score]
    if profile_id:
        query += " AND p.id = %s"
        params.append(profile_id)
    query += " ORDER BY l.first_seen DESC, m.score DESC LIMIT 200;"
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def add_profile(data):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO profiles (name, min_price, max_price, min_rooms, max_rooms, min_size, districts, keywords_exclude)
        VALUES (%(name)s,%(min_price)s,%(max_price)s,%(min_rooms)s,%(max_rooms)s,%(min_size)s,%(districts)s,%(keywords_exclude)s);
    """, data)
    conn.commit()
    cur.close()
    conn.close()


def delete_profile(profile_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM profiles WHERE id=%s;", (profile_id,))
    conn.commit()
    cur.close()
    conn.close()

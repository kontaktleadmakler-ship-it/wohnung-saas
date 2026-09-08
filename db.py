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

    # Listings: eine Zeile pro real gefundenem Inserat, dedupliziert über (source, external_id)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id SERIAL PRIMARY KEY,
            external_id TEXT,
            title TEXT,
            price NUMERIC,
            rooms FLOAT,
            size FLOAT,
            location TEXT,
            url TEXT,
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

    # Migration 001: Quellen pro Profil (n:m)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS profile_sources (
            profile_id INT REFERENCES profiles(id) ON DELETE CASCADE,
            source TEXT NOT NULL,               -- Registry-Key, z.B. 'immoscout24'
            PRIMARY KEY (profile_id, source)
        );
    """)

    # Migration 002: Regionen pro Profil (n:m). Kein Eintrag = bundesweit.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS profile_regions (
            profile_id INT REFERENCES profiles(id) ON DELETE CASCADE,
            region_code TEXT NOT NULL,          -- z.B. 'BY', 'BE', 'NW' (ISO 3166-2:DE ohne Präfix)
            PRIMARY KEY (profile_id, region_code)
        );
    """)

    # Migration 003: listings erweitern + Unique-Constraint korrigieren
    cur.execute("""
        ALTER TABLE listings
            ADD COLUMN IF NOT EXISTS description TEXT,
            ADD COLUMN IF NOT EXISTS price_total NUMERIC,
            ADD COLUMN IF NOT EXISTS postal_code TEXT,
            ADD COLUMN IF NOT EXISTS region_code TEXT,
            ADD COLUMN IF NOT EXISTS contact_name TEXT,
            ADD COLUMN IF NOT EXISTS contact_phone TEXT,
            ADD COLUMN IF NOT EXISTS published_at TIMESTAMP;
    """)

    # external_id ist NICHT plattformübergreifend eindeutig (zwei Portale können zufällig
    # dieselbe ID vergeben) -> composite unique statt globalem UNIQUE auf external_id.
    cur.execute("ALTER TABLE listings DROP CONSTRAINT IF EXISTS listings_external_id_key;")
    cur.execute("ALTER TABLE listings DROP CONSTRAINT IF EXISTS listings_url_key;")
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'listings_source_external_id_key'
            ) THEN
                ALTER TABLE listings
                    ADD CONSTRAINT listings_source_external_id_key UNIQUE (source, external_id);
            END IF;
        END $$;
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


def get_profile_sources(profile_id) -> list[str]:
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT source FROM profile_sources WHERE profile_id=%s;", (profile_id,))
    rows = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def get_profile_regions(profile_id) -> list[str]:
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT region_code FROM profile_regions WHERE profile_id=%s;", (profile_id,))
    rows = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()
    return rows


def set_profile_sources(profile_id, sources: list[str]):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM profile_sources WHERE profile_id=%s;", (profile_id,))
    cur.executemany(
        "INSERT INTO profile_sources (profile_id, source) VALUES (%s,%s);",
        [(profile_id, s) for s in sources],
    )
    conn.commit(); cur.close(); conn.close()


def set_profile_regions(profile_id, region_codes: list[str]):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("DELETE FROM profile_regions WHERE profile_id=%s;", (profile_id,))
    cur.executemany(
        "INSERT INTO profile_regions (profile_id, region_code) VALUES (%s,%s);",
        [(profile_id, r) for r in region_codes],
    )
    conn.commit(); cur.close(); conn.close()


def get_active_profiles_with_sources():
    """Wie get_active_profiles(), aber inkl. sources[]/regions[] als Arrays."""
    conn = get_conn(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT p.*,
               COALESCE(array_agg(DISTINCT ps.source) FILTER (WHERE ps.source IS NOT NULL), '{}') AS sources,
               COALESCE(array_agg(DISTINCT pr.region_code) FILTER (WHERE pr.region_code IS NOT NULL), '{}') AS regions
        FROM profiles p
        LEFT JOIN profile_sources ps ON ps.profile_id = p.id
        LEFT JOIN profile_regions pr ON pr.profile_id = p.id
        WHERE p.active = TRUE
        GROUP BY p.id;
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows


def upsert_listing(listing) -> tuple[int, bool]:
    """listing: scrapers.models.Listing. Upsert über (source, external_id)."""
    conn = get_conn(); cur = conn.cursor()
    data = dict(listing.__dict__)
    data["address"] = data.get("address")  # -> Spalte "location"
    cur.execute("""
        INSERT INTO listings (external_id, title, description, price, price_total, rooms, size,
                               location, postal_code, region_code, url, source,
                               contact_name, contact_phone, published_at)
        VALUES (%(external_id)s,%(title)s,%(description)s,%(price)s,%(price_total)s,%(rooms)s,%(size)s,
                %(address)s,%(postal_code)s,%(region_code)s,%(url)s,%(source)s,
                %(contact_name)s,%(contact_phone)s,%(published_at)s)
        ON CONFLICT (source, external_id) DO UPDATE SET last_seen = NOW()
        RETURNING id, (xmax = 0) AS is_new;
    """, data)
    listing_id, is_new = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
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


def add_profile(data) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO profiles (name, min_price, max_price, min_rooms, max_rooms, min_size, districts, keywords_exclude)
        VALUES (%(name)s,%(min_price)s,%(max_price)s,%(min_rooms)s,%(max_rooms)s,%(min_size)s,%(districts)s,%(keywords_exclude)s)
        RETURNING id;
    """, data)
    profile_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return profile_id


def delete_profile(profile_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM profiles WHERE id=%s;", (profile_id,))
    conn.commit()
    cur.close()
    conn.close()

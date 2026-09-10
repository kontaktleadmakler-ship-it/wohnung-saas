from __future__ import annotations
import os
from contextlib import contextmanager
import psycopg2
import psycopg2.extras

DATABASE_URL = os.getenv("DATABASE_URL")
LOCK_KEY = 738291

@contextmanager
def connection():
    if not DATABASE_URL: raise RuntimeError("DATABASE_URL fehlt")
    conn=psycopg2.connect(DATABASE_URL, sslmode="require")
    try: yield conn
    finally: conn.close()

@contextmanager
def get_connection():
    """Öffnet eine DB-Verbindung und schließt sie garantiert auch bei Exceptions."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL fehlt")
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with connection() as c:
        with c.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS profiles(
              id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, min_price NUMERIC NOT NULL DEFAULT 0,
              max_price NUMERIC NOT NULL, min_rooms NUMERIC NOT NULL DEFAULT 0, max_rooms NUMERIC,
              min_size NUMERIC NOT NULL DEFAULT 0, districts TEXT, keywords_exclude TEXT,
              active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS listings(
              id BIGSERIAL PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL, title TEXT NOT NULL,
              description TEXT, price NUMERIC, price_total NUMERIC, rooms NUMERIC, size NUMERIC,
              location TEXT, city TEXT, postal_code TEXT, region_code TEXT, url TEXT NOT NULL,
              contact_name TEXT, contact_phone TEXT, published_at TIMESTAMPTZ, first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(), last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(), raw JSONB NOT NULL DEFAULT '{}'::jsonb,
              CONSTRAINT listings_source_external_id_key UNIQUE(source, external_id)
            );
            CREATE TABLE IF NOT EXISTS matches(
              listing_id BIGINT REFERENCES listings(id) ON DELETE CASCADE, profile_id INT REFERENCES profiles(id) ON DELETE CASCADE,
              score INT NOT NULL CHECK(score BETWEEN 0 AND 100), price_score INT DEFAULT 0, rooms_score INT DEFAULT 0, size_score INT DEFAULT 0, location_score INT DEFAULT 0,
              reasons JSONB NOT NULL DEFAULT '[]'::jsonb, notified BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              PRIMARY KEY(listing_id, profile_id)
            );
            CREATE TABLE IF NOT EXISTS profile_sources(profile_id INT REFERENCES profiles(id) ON DELETE CASCADE, source TEXT NOT NULL, PRIMARY KEY(profile_id,source));
            CREATE TABLE IF NOT EXISTS profile_regions(profile_id INT REFERENCES profiles(id) ON DELETE CASCADE, region_code TEXT NOT NULL, PRIMARY KEY(profile_id,region_code));
            CREATE TABLE IF NOT EXISTS scan_runs(
              id BIGSERIAL PRIMARY KEY, started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), duration_seconds NUMERIC, summary JSONB NOT NULL DEFAULT '{}'::jsonb
            );
            CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings(last_seen DESC);
            CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source);
            CREATE INDEX IF NOT EXISTS idx_matches_score ON matches(score DESC);
            CREATE INDEX IF NOT EXISTS idx_matches_profile_created ON matches(profile_id,created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_matches_notified ON matches(notified);
            CREATE INDEX IF NOT EXISTS idx_profile_sources_source ON profile_sources(source);
            CREATE INDEX IF NOT EXISTS idx_profile_regions_region ON profile_regions(region_code);
            CREATE INDEX IF NOT EXISTS idx_scan_runs_started ON scan_runs(started_at DESC);
            """)
            cur.execute("ALTER TABLE listings ADD COLUMN IF NOT EXISTS raw JSONB NOT NULL DEFAULT '{}'::jsonb")
            # Alte Scan-Läufe werden nicht mehr benötigt und würden die Tabelle
            # sonst unbegrenzt wachsen lassen.
            cur.execute(
                "DELETE FROM scan_runs WHERE started_at < NOW() - INTERVAL '30 days'"
            )
        c.commit()

def try_scan_lock():
    # Der Advisory-Lock muss auf genau dieser Verbindung gehalten werden,
    # deshalb darf diese Verbindung erst in release_scan_lock() geschlossen werden.
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL fehlt")
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
            ok = cur.fetchone()[0]
        if ok:
            return conn
    except Exception:
        conn.close()
        raise
    conn.close()
    return None

def release_scan_lock(conn):
    if not conn: return
    try:
        with conn.cursor() as cur: cur.execute("SELECT pg_advisory_unlock(%s)",(LOCK_KEY,)); conn.commit()
    finally: conn.close()

def get_active_profiles():
    with get_connection() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM profiles WHERE active ORDER BY id")
            return cur.fetchall()

def get_active_profiles_with_sources():
    with get_connection() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
              SELECT p.*, COALESCE(array_agg(DISTINCT ps.source) FILTER(WHERE ps.source IS NOT NULL),'{}') sources,
                     COALESCE(array_agg(DISTINCT pr.region_code) FILTER(WHERE pr.region_code IS NOT NULL),'{}') regions
              FROM profiles p LEFT JOIN profile_sources ps ON ps.profile_id=p.id LEFT JOIN profile_regions pr ON pr.profile_id=p.id
              WHERE p.active GROUP BY p.id ORDER BY p.id
            """)
            return cur.fetchall()

def get_profile(profile_id):
    with get_connection() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM profiles WHERE id=%s",(profile_id,)); p=cur.fetchone()
            if not p:return None
            cur.execute("SELECT source FROM profile_sources WHERE profile_id=%s ORDER BY source",(profile_id,)); p['sources']=[r['source'] for r in cur.fetchall()]
            cur.execute("SELECT region_code FROM profile_regions WHERE profile_id=%s ORDER BY region_code",(profile_id,)); p['regions']=[r['region_code'] for r in cur.fetchall()]
            return p

def add_profile(data):
    with get_connection() as c:
        with c.cursor() as cur:
            cur.execute("INSERT INTO profiles(name,min_price,max_price,min_rooms,max_rooms,min_size,districts,keywords_exclude) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",tuple(data.get(k) for k in ('name','min_price','max_price','min_rooms','max_rooms','min_size','districts','keywords_exclude'))); pid=cur.fetchone()[0]
        c.commit(); return pid

def update_profile(pid,data):
    with get_connection() as c:
        with c.cursor() as cur:
            cur.execute("UPDATE profiles SET name=%s,min_price=%s,max_price=%s,min_rooms=%s,max_rooms=%s,min_size=%s,districts=%s,keywords_exclude=%s,active=%s,updated_at=NOW() WHERE id=%s",tuple(data.get(k) for k in ('name','min_price','max_price','min_rooms','max_rooms','min_size','districts','keywords_exclude','active'))+(pid,)); c.commit()

def set_profile_sources(pid,sources):
    with get_connection() as c:
        with c.cursor() as cur:
            cur.execute("DELETE FROM profile_sources WHERE profile_id=%s",(pid,))
            for s in set(sources or []): cur.execute("INSERT INTO profile_sources(profile_id,source) VALUES(%s,%s) ON CONFLICT DO NOTHING",(pid,s))
        c.commit()

def set_profile_regions(pid,regions):
    with get_connection() as c:
        with c.cursor() as cur:
            cur.execute("DELETE FROM profile_regions WHERE profile_id=%s",(pid,))
            vals=set(regions or ['DE'])
            for r in vals: cur.execute("INSERT INTO profile_regions(profile_id,region_code) VALUES(%s,%s) ON CONFLICT DO NOTHING",(pid,r))
        c.commit()

def delete_profile(pid):
    with get_connection() as c:
        with c.cursor() as cur: cur.execute("DELETE FROM profiles WHERE id=%s",(pid,))
        c.commit()

def upsert_listing(item):
    with get_connection() as c:
        with c.cursor() as cur:
            cur.execute("""INSERT INTO listings(source,external_id,title,description,price,price_total,rooms,size,location,city,postal_code,region_code,url,contact_name,contact_phone,published_at,raw)
              VALUES(%(source)s,%(external_id)s,%(title)s,%(description)s,%(price)s,%(price_total)s,%(rooms)s,%(size)s,%(address)s,%(city)s,%(postal_code)s,%(region_code)s,%(url)s,%(contact_name)s,%(contact_phone)s,%(published_at)s,%(raw)s)
              ON CONFLICT(source,external_id) DO UPDATE SET title=EXCLUDED.title,description=EXCLUDED.description,price=EXCLUDED.price,price_total=EXCLUDED.price_total,rooms=EXCLUDED.rooms,size=EXCLUDED.size,location=EXCLUDED.location,url=EXCLUDED.url,last_seen=NOW(),raw=EXCLUDED.raw
              RETURNING id,(xmax=0) AS is_new""",{**item.__dict__,'raw': psycopg2.extras.Json(item.raw or {})}); row=cur.fetchone(); c.commit(); return row[0],row[1]

def save_match(listing_id,profile_id,score,components,reasons):
    with get_connection() as c:
        with c.cursor() as cur:
            cur.execute("""INSERT INTO matches(listing_id,profile_id,score,price_score,rooms_score,size_score,location_score,reasons)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(listing_id,profile_id) DO UPDATE SET score=EXCLUDED.score,price_score=EXCLUDED.price_score,rooms_score=EXCLUDED.rooms_score,size_score=EXCLUDED.size_score,location_score=EXCLUDED.location_score,reasons=EXCLUDED.reasons,updated_at=NOW() RETURNING notified""",(listing_id,profile_id,score,*components,psycopg2.extras.Json(reasons))); notified=cur.fetchone()[0]; c.commit(); return not notified

def mark_notified(listing_id,profile_id):
    with get_connection() as c:
        with c.cursor() as cur: cur.execute("UPDATE matches SET notified=TRUE,updated_at=NOW() WHERE listing_id=%s AND profile_id=%s",(listing_id,profile_id)); c.commit()

def save_scan_run(summary, duration_seconds=None):
    with get_connection() as c:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO scan_runs(duration_seconds,summary) VALUES(%s,%s)",
                (duration_seconds, psycopg2.extras.Json(summary)),
            )
        c.commit()

def get_last_scan_run():
    with get_connection() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM scan_runs ORDER BY started_at DESC LIMIT 1")
            return cur.fetchone()

DASHBOARD_LIMIT = max(1, int(os.getenv("DASHBOARD_LIMIT", "300")))

def get_dashboard_rows(min_score=0,profile_id=None,limit=None):
    limit = DASHBOARD_LIMIT if limit is None else max(1, int(limit))
    with get_connection() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            q="""SELECT m.*,l.title,l.price,l.price_total,l.rooms,l.size,l.location,l.url,l.source,l.first_seen,l.last_seen,p.name profile_name FROM matches m JOIN listings l ON l.id=m.listing_id JOIN profiles p ON p.id=m.profile_id WHERE m.score >= %s"""; args=[min_score]
            if profile_id:q+=" AND p.id=%s"; args.append(profile_id)
            q+=" ORDER BY m.score DESC,m.created_at DESC LIMIT %s"; args.append(limit); cur.execute(q,args); return cur.fetchall()

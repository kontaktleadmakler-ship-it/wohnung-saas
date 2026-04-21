import os
import psycopg2
from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

# -----------------------------
# DATABASE CONFIG (FIXED)
# -----------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    print("❌ DATABASE_URL fehlt! Bitte in Render Environment Variables setzen.")


def db():
    """
    Safe DB connection for Render PostgreSQL
    """
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        return conn
    except Exception as e:
        print("❌ DB CONNECTION ERROR:", e)
        return None


# -----------------------------
# INIT DB TABLES
# -----------------------------
def init_db():
    conn = db()
    if not conn:
        return

    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id SERIAL PRIMARY KEY,
            title TEXT,
            price TEXT,
            location TEXT,
            url TEXT UNIQUE
        );
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("✅ DB initialized")


# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    conn = db()
    if not conn:
        return "DB not connected"

    cur = conn.cursor()
    cur.execute("SELECT * FROM listings ORDER BY id DESC LIMIT 50;")
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return render_template("dashboard.html", listings=rows)


@app.route("/scraper/run")
def run_scraper():
    """
    Placeholder scraper trigger
    """
    print("🚀 Scraper started")

    conn = db()
    if not conn:
        return "DB not connected"

    cur = conn.cursor()

    # TEST INSERT (damit du sofort Daten siehst)
    cur.execute("""
        INSERT INTO listings (title, price, location, url)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (url) DO NOTHING;
    """, ("Test Wohnung", "1200€", "Berlin", "https://example.com/test"))

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("home"))


@app.route("/login")
def login():
    return "Login Page (placeholder)"


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# -----------------------------
# START APP
# -----------------------------
if __name__ == "__main__":
    init_db()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

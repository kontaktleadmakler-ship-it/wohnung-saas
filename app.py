from flask import Flask, render_template, request, redirect, session
import sqlite3
import os

app = Flask(__name__)
app.secret_key = "v5saas"

DB = "leads.db"


# =========================
# 💾 DB INIT (WICHTIG!)
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
# 🔐 LOGIN
# =========================
@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        if request.form["username"] == "admin" and request.form["password"] == "1234":
            session["user"] = "admin"
            return redirect("/dashboard")

    return """
    <h2>Login</h2>
    <form method="post">
        <input name="username" placeholder="user">
        <input name="password" placeholder="pass" type="password">
        <button type="submit">Login</button>
    </form>
    """


# =========================
# 📊 DASHBOARD
# =========================
@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect("/")

    init_db()

    score_filter = request.args.get("score", "0")

    try:
        score_filter = int(score_filter)
    except:
        score_filter = 0

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM leads
        WHERE score >= ?
        ORDER BY score DESC
    """, (score_filter,))

    leads = cur.fetchall()
    conn.close()

    html = "<h1>Dashboard</h1>"
    html += "<a href='/logout'>Logout</a><br><br>"

    html += "<form><input name='score' placeholder='min score'><button>Filter</button></form><br>"

    if not leads:
        html += "<h3>⚠️ Keine Daten in DB – Scraper starten!</h3>"
    else:
        for l in leads:
            html += f"""
            <div style='border:1px solid #ccc;padding:10px;margin:10px'>
                <b>{l[1]}</b><br>
                💶 {l[2]}€ | 🏠 {l[3]} Zi | 📏 {l[4]} m²<br>
                ⭐ Score: {l[8]} | 👤 {l[7]}<br>
                <a href="{l[5]}" target="_blank">Link</a>
            </div>
            """

    return html


# =========================
# 🚪 LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# =========================
# 🚀 START (RENDER FIX)
# =========================
if __name__ == "__main__":
    init_db()

    print("🔥 CRM RUNNING")

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

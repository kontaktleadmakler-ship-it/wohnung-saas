from flask import Flask, request, redirect, session
import os
import psycopg2

app = Flask(__name__)
app.secret_key = "v5saas"

DATABASE_URL = os.environ.get("DATABASE_URL")


# =========================
# DB CONNECT
# =========================
def db():
    return psycopg2.connect(DATABASE_URL, sslmode='require')


# =========================
# INIT DB
# =========================
def init_db():
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

    conn.commit()
    conn.close()


# =========================
# LOGIN
# =========================
@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        if request.form["username"] == "admin":
            session["user"] = "admin"
            return redirect("/dashboard")

    return """
    <form method="post">
        <input name="username">
        <button>Login</button>
    </form>
    """


# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect("/")

    init_db()

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM leads ORDER BY score DESC")
    leads = cur.fetchall()
    conn.close()

    html = "<h1>CRM DASHBOARD</h1><a href='/logout'>Logout</a><br><br>"

    if not leads:
        return html + "<h3>Keine Daten – Worker läuft noch nicht</h3>"

    for l in leads:
        html += f"""
        <div style='border:1px solid #ccc;padding:10px;margin:10px'>
            <b>{l[1]}</b><br>
            💶 {l[2]}€ | 🏠 {l[3]} Zi | 📏 {l[4]} m²<br>
            ⭐ {l[8]} | 👤 {l[7]}<br>
            <a href="{l[5]}" target="_blank">Link</a>
        </div>
        """

    return html


# =========================
# LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# =========================
# START
# =========================
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

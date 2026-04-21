from flask import Flask, render_template, request, redirect, session
import sqlite3
import os

app = Flask(__name__)
app.secret_key = "v5saas"


# ---------------- DB ----------------
def get_db():
    conn = sqlite3.connect("leads.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            phone TEXT,
            score INTEGER
        )
    """)

    # Beispiel-Daten (nur wenn leer)
    cur.execute("SELECT COUNT(*) FROM leads")
    if cur.fetchone()[0] == 0:
        cur.executemany("""
            INSERT INTO leads (name, email, phone, score)
            VALUES (?, ?, ?, ?)
        """, [
            ("Max Mustermann", "max@mail.de", "0123456", 90),
            ("Anna Schmidt", "anna@mail.de", "0223456", 70),
            ("Tom Becker", "tom@mail.de", "0333456", 50),
        ])

    conn.commit()
    conn.close()


init_db()


# ---------------- ROUTES ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == "admin" and request.form["password"] == "1234":
            session["user"] = "admin"
            return redirect("/dashboard")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")

    score_filter = request.args.get("score", 0)

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM leads
        WHERE score >= ?
        ORDER BY score DESC
    """, (score_filter,))

    leads = cur.fetchall()
    conn.close()

    return render_template("dashboard.html", leads=leads)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ---------------- START ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

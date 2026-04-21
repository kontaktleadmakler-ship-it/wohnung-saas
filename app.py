from flask import Flask, render_template, request, redirect, session
import sqlite3
import os

app = Flask(__name__)
app.secret_key = "v5saas"


# ----------------------------
# DATABASE CONNECTION
# ----------------------------
def db():
    return sqlite3.connect("leads.db")


# ----------------------------
# INIT DATABASE (IMPORTANT FIX)
# ----------------------------
def init_db():
    conn = sqlite3.connect("leads.db")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            score INTEGER
        )
    """)

    conn.commit()
    conn.close()


init_db()


# ----------------------------
# LOGIN PAGE
# ----------------------------
@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == "admin" and password == "1234":
            session["user"] = "admin"
            return redirect("/dashboard")

    return render_template("login.html")


# ----------------------------
# DASHBOARD
# ----------------------------
@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect("/")

    score_filter = request.args.get("score", 0)

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM leads
        WHERE score >= ?
        ORDER BY score DESC
    """, (score_filter,))

    leads = cur.fetchall()
    conn.close()

    return render_template("dashboard.html", leads=leads)


# ----------------------------
# LOGOUT
# ----------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ----------------------------
# RUN SERVER (RENDER FIXED)
# ----------------------------
if __name__ == "__main__":
    print("🔥 V6 SAAS CRM RUNNING")

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)

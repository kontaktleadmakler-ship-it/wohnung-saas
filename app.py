from flask import Flask, render_template, request, redirect, session
import sqlite3
from scraper import run_scraper

app = Flask(__name__)
app.secret_key = "v5saas"


def db():
    return sqlite3.connect("leads.db")


# =========================
# LOGIN
# =========================
@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        if request.form["username"] == "admin" and request.form["password"] == "1234":
            session["user"] = "admin"
            return redirect("/dashboard")

    return render_template("login.html")


# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
def dashboard():

    if "user" not in session:
        return redirect("/")

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM leads ORDER BY score DESC
    """)

    leads = cur.fetchall()
    conn.close()

    return render_template("dashboard.html", leads=leads)


# =========================
# SCRAPER TRIGGER
# =========================
@app.route("/scrape")
def scrape():

    if "user" not in session:
        return redirect("/")

    run_scraper()
    return redirect("/dashboard")


# =========================
# LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# =========================
# START SERVER (WICHTIG FÜR RENDER)
# =========================
if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

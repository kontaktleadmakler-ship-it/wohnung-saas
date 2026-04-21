from flask import Flask, render_template, request, redirect, session
import sqlite3
import os

app = Flask(__name__)
app.secret_key = "v6saas"

# =========================
# DATABASE
# =========================
def db():
    conn = sqlite3.connect("leads.db")
    conn.row_factory = sqlite3.Row
    return conn

# =========================
# LOGIN
# =========================
@app.route("/", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == "admin" and password == "1234":
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

    # safe conversion
    try:
        score_filter = int(request.args.get("score", 0))
    except:
        score_filter = 0

    conn = db()
    cur = conn.cursor()

    # FIX: avoids crash if score column missing
    try:
        cur.execute("""
            SELECT * FROM leads
            WHERE score >= ?
            ORDER BY score DESC
        """, (score_filter,))
    except:
        cur.execute("""
            SELECT * FROM leads
            ORDER BY id DESC
        """)

    leads = cur.fetchall()
    conn.close()

    return render_template("dashboard.html", leads=leads)

# =========================
# LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# =========================
# START SERVER (RENDER SAFE)
# =========================
if __name__ == "__main__":
    print("🔥 V6 SAAS CRM RUNNING")

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

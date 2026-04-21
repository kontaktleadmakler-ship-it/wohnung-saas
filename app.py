from flask import Flask, render_template, request, redirect, session
import sqlite3

app = Flask(__name__)
app.secret_key = "v5saas"

def db():
    return sqlite3.connect("leads.db")

@app.route("/", methods=["GET","POST"])
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

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM leads
        WHERE score >= ?
        ORDER BY score DESC
    """, (score_filter,))

    leads = cur.fetchall()

    return render_template("dashboard.html", leads=leads)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    print("🔥 V5 CRM FILTER SYSTEM RUNNING")
    app.run(debug=True)
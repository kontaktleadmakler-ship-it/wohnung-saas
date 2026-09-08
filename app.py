import os
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session

import db
from scrapers.registry import list_sources
from scrapers.regions import BUNDESLAENDER

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

APP_PASSWORD = os.environ.get("APP_PASSWORD")  # Login-Passwort für das Dashboard


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if APP_PASSWORD and not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not APP_PASSWORD or request.form.get("password") == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("home"))
        return render_template("login.html", error="Falsches Passwort")
    return render_template("login.html", error=None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def home():
    min_score = int(request.args.get("min_score", 0))
    profile_id = request.args.get("profile_id") or None
    rows = db.get_dashboard_rows(min_score=min_score, profile_id=profile_id)
    profiles = db.get_active_profiles()
    return render_template(
        "dashboard.html", rows=rows, profiles=profiles,
        min_score=min_score, selected_profile=profile_id,
    )


@app.route("/profiles", methods=["GET", "POST"])
@login_required
def profiles():
    if request.method == "POST":
        profile_id = db.add_profile({
            "name": request.form["name"],
            "min_price": request.form.get("min_price") or 0,
            "max_price": request.form["max_price"],
            "min_rooms": request.form.get("min_rooms") or 0,
            "max_rooms": request.form.get("max_rooms") or None,
            "min_size": request.form.get("min_size") or 0,
            "districts": request.form.get("districts", ""),
            "keywords_exclude": request.form.get("keywords_exclude", ""),
        })
        db.set_profile_sources(profile_id, request.form.getlist("sources"))
        db.set_profile_regions(profile_id, request.form.getlist("regions"))
        return redirect(url_for("profiles"))

    return render_template(
        "profiles.html",
        profiles=db.get_active_profiles_with_sources(),
        available_sources=list_sources(),
        available_regions=BUNDESLAENDER,
    )


@app.route("/profiles/<int:profile_id>/sources", methods=["POST"])
@login_required
def update_profile_sources(profile_id):
    """Nachträgliche Änderung der Quellen/Regionen, ohne das ganze Profil neu anzulegen."""
    db.set_profile_sources(profile_id, request.form.getlist("sources"))
    db.set_profile_regions(profile_id, request.form.getlist("regions"))
    return redirect(url_for("profiles"))


@app.route("/profiles/<int:profile_id>/delete", methods=["POST"])
@login_required
def delete_profile(profile_id):
    db.delete_profile(profile_id)
    return redirect(url_for("profiles"))


if __name__ == "__main__":
    db.init_db()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

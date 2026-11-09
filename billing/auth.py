import hmac
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, current_app, g, jsonify, redirect, request, session

from .db import connect, fetch_one

bp = Blueprint("auth", __name__, url_prefix="/auth")


def require_user():
    user_id = session.get("user_id")
    if user_id is None:
        abort(401)
    user = fetch_one(
        "SELECT u.id, u.account_id, u.email, u.name, u.role, u.status, a.status AS account_status "
        "FROM users u JOIN accounts a ON a.id = u.account_id WHERE u.id = ?",
        (user_id,),
    )
    if user is None or user["status"] != "active":
        session.clear()
        abort(401)
    if user["account_status"] == "suspended" and user["role"] != "admin":
        abort(403)
    g.user = user
    return user


def require_admin():
    user = require_user()
    if user["role"] != "admin":
        abort(403)
    return user


@bp.post("/login")
def login():
    from .api.users import hash_password

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    db = connect()
    user = fetch_one(
        "SELECT id, password_hash, status, failed_logins, locked_until FROM users WHERE email = ?",
        (email,),
    )
    now = datetime.now(timezone.utc)
    if user and user["locked_until"] and datetime.fromisoformat(user["locked_until"]) > now:
        return jsonify(error="too many failed attempts, try again later"), 429
    if not user or user["status"] != "active" or not hmac.compare_digest(user["password_hash"], hash_password(password)):
        if user:
            _count_failure(db, user, now)
        return jsonify(error="wrong email or password"), 401

    db.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", (user["id"],))
    db.commit()
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True
    return redirect(request.args.get("next", "/"))


@bp.post("/logout")
def logout():
    session.clear()
    return "", 204


def _count_failure(db, user, now):
    failures = user["failed_logins"] + 1
    locked_until = None
    if failures >= current_app.config["LOGIN_MAX_FAILURES"]:
        failures = 0
        locked_until = (now + timedelta(seconds=current_app.config["LOGIN_LOCKOUT_SECONDS"])).isoformat()
    db.execute(
        "UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
        (failures, locked_until, user["id"]),
    )
    db.commit()

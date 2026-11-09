import hashlib
import hmac

from flask import Blueprint, jsonify, request, session

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all, fetch_one
from .audit import record

bp = Blueprint("users", __name__, url_prefix="/users")

PROFILE_FIELDS = ("name", "email", "timezone", "role")


def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()


def _profile(user_id):
    return fetch_one(
        "SELECT id, account_id, email, name, role, timezone, created_at FROM users WHERE id = ?",
        (user_id,),
    )


def _password_matches(user_id, password):
    if not isinstance(password, str):
        return False
    row = fetch_one("SELECT password_hash FROM users WHERE id = ?", (user_id,))
    return row is not None and hmac.compare_digest(row["password_hash"], hash_password(password))


@bp.post("")
def sign_up():
    body = validators.json_body(request)
    email = validators.email(body.get("email"))
    password = validators.password(body.get("password"))
    company = validators.text(body, "company", max_length=120, required=True)
    name = validators.text(body, "name", max_length=100)

    db = connect()
    if fetch_one("SELECT 1 FROM users WHERE email = ?", (email,)):
        return jsonify(error="an account with that email already exists"), 409
    account_id = db.execute("INSERT INTO accounts (name) VALUES (?)", (company,)).lastrowid
    user_id = db.execute(
        "INSERT INTO users (account_id, email, name, password_hash, role) VALUES (?, ?, ?, ?, 'owner')",
        (account_id, email, name, hash_password(password)),
    ).lastrowid
    db.commit()

    session.clear()
    session["user_id"] = user_id
    return jsonify(_profile(user_id)), 201


@bp.get("/me")
def me():
    user = require_user()
    return jsonify(_profile(user["id"]))


@bp.patch("/me")
def update_me():
    user = require_user()
    body = validators.json_body(request)
    changes = {field: body[field] for field in PROFILE_FIELDS if field in body}

    if "name" in changes:
        changes["name"] = validators.text(changes, "name", max_length=100)
    if "timezone" in changes:
        changes["timezone"] = validators.timezone_name(changes["timezone"])
    if "email" in changes:
        changes["email"] = validators.email(changes["email"])
        if not _password_matches(user["id"], body.get("current_password")):
            return jsonify(error="enter your current password to change your email"), 403
        if fetch_one("SELECT 1 FROM users WHERE email = ? AND id != ?", (changes["email"], user["id"])):
            return jsonify(error="that email is already in use"), 409
    if not changes:
        return jsonify(_profile(user["id"]))

    db = connect()
    assignments = ", ".join(f"{field} = ?" for field in changes)
    db.execute(f"UPDATE users SET {assignments} WHERE id = ?", (*changes.values(), user["id"]))
    record(db, user, "user.updated", {"fields": sorted(changes)})
    db.commit()
    return jsonify(_profile(user["id"]))


@bp.post("/me/password")
def change_password():
    user = require_user()
    body = validators.json_body(request)
    if not _password_matches(user["id"], body.get("current_password")):
        return jsonify(error="your current password is not right"), 403
    new_password = validators.password(body.get("new_password"), "new_password")

    db = connect()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user["id"]))
    record(db, user, "user.password_changed")
    db.commit()
    return "", 204


@bp.get("")
def list_team():
    user = require_user()
    team = fetch_all(
        "SELECT id, email, name, role, status, created_at FROM users WHERE account_id = ? ORDER BY created_at",
        (user["account_id"],),
    )
    return jsonify(data=team)

import hashlib
import hmac
import random
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, jsonify, request

from .. import validators
from ..db import connect, fetch_one
from .notifications import send_email
from .users import hash_password

bp = Blueprint("password_reset", __name__, url_prefix="/password-reset")

MAX_ATTEMPTS = 5


def _digest(code):
    return hmac.new(current_app.config["SECRET_KEY"].encode(), code.encode(), hashlib.sha256).hexdigest()


def _rejected():
    return jsonify(error="that code is wrong or has expired"), 400


@bp.post("")
def start_reset():
    body = validators.json_body(request)
    email = validators.email(body.get("email"))
    user = fetch_one("SELECT id, email FROM users WHERE email = ? AND status = 'active'", (email,))
    if user is not None:
        ttl = current_app.config["PASSWORD_RESET_TTL"]
        code = str(random.randint(100000, 999999))
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        db = connect()
        db.execute(
            "UPDATE password_resets SET used_at = CURRENT_TIMESTAMP WHERE user_id = ? AND used_at IS NULL",
            (user["id"],),
        )
        db.execute(
            "INSERT INTO password_resets (user_id, code_hash, expires_at) VALUES (?, ?, ?)",
            (user["id"], _digest(code), expires_at.isoformat()),
        )
        db.commit()
        send_email(
            user["email"],
            "Your password reset code",
            f"Your code is {code}. It expires in {ttl // 60} minutes.\n\n"
            "If you did not ask to reset your password, you can ignore this email.",
        )
    return jsonify(message="If that email has an account, a reset code is on its way."), 202


@bp.post("/confirm")
def confirm_reset():
    body = validators.json_body(request)
    email = validators.email(body.get("email"))
    code = str(body.get("code", "")).strip()
    new_password = validators.password(body.get("new_password"), "new_password")
    reset = fetch_one(
        "SELECT r.id, r.user_id, r.code_hash, r.expires_at, r.attempts FROM password_resets r "
        "JOIN users u ON u.id = r.user_id WHERE u.email = ? AND r.used_at IS NULL ORDER BY r.id DESC LIMIT 1",
        (email,),
    )
    if reset is None or reset["attempts"] >= MAX_ATTEMPTS:
        return _rejected()
    if datetime.fromisoformat(reset["expires_at"]) < datetime.now(timezone.utc):
        return _rejected()

    db = connect()
    if not hmac.compare_digest(reset["code_hash"], _digest(code)):
        db.execute("UPDATE password_resets SET attempts = attempts + 1 WHERE id = ?", (reset["id"],))
        db.commit()
        return _rejected()
    db.execute(
        "UPDATE users SET password_hash = ?, failed_logins = 0, locked_until = NULL WHERE id = ?",
        (hash_password(new_password), reset["user_id"]),
    )
    db.execute("UPDATE password_resets SET used_at = CURRENT_TIMESTAMP WHERE id = ?", (reset["id"],))
    db.commit()
    return "", 204

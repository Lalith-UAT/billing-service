import secrets

from flask import Blueprint, abort, jsonify, request

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all, fetch_one
from .audit import record
from .customers import get_customer
from .payments import GatewayError, gateway

bp = Blueprint("payment_methods", __name__, url_prefix="/payment-methods")

COLUMNS = "id, customer_id, brand, last4, exp_month, exp_year, is_default, created_at"


def _method(account_id, method_id):
    method = fetch_one(
        f"SELECT {COLUMNS} FROM payment_methods WHERE id = ? AND account_id = ?",
        (method_id, account_id),
    )
    if method is None:
        abort(404)
    return method


@bp.get("")
def list_methods():
    user = require_user()
    customer_id = validators.positive_int(request.args.get("customer_id"), "customer_id")
    methods = fetch_all(
        f"SELECT {COLUMNS} FROM payment_methods WHERE account_id = ? AND customer_id = ? "
        "ORDER BY is_default DESC, id",
        (user["account_id"], customer_id),
    )
    return jsonify(data=methods)


@bp.get("/<int:method_id>")
def show_method(method_id):
    user = require_user()
    return jsonify(_method(user["account_id"], method_id))


@bp.post("")
def add_method():
    user = require_user()
    body = validators.json_body(request)
    customer = get_customer(user["account_id"], validators.positive_int(body.get("customer_id"), "customer_id"))
    token = validators.text(body, "token", max_length=128, required=True)
    try:
        card = gateway("/tokens/attach", {"token": token, "customer": f"cus-{customer['id']}"}, secrets.token_hex(16))
    except GatewayError:
        return jsonify(error="the card could not be saved"), 502

    db = connect()
    existing = db.execute(
        "SELECT COUNT(*) FROM payment_methods WHERE account_id = ? AND customer_id = ?",
        (user["account_id"], customer["id"]),
    ).fetchone()[0]
    method_id = db.execute(
        "INSERT INTO payment_methods (account_id, customer_id, gateway_token, brand, last4, exp_month, exp_year, "
        "is_default) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user["account_id"], customer["id"], card["id"], card["brand"], card["last4"],
            card["exp_month"], card["exp_year"], int(existing == 0),
        ),
    ).lastrowid
    record(db, user, "payment_method.added", {"method_id": method_id, "customer_id": customer["id"]})
    db.commit()
    return jsonify(_method(user["account_id"], method_id)), 201


@bp.delete("/<int:method_id>")
def remove_method(method_id):
    user = require_user()
    db = connect()
    removed = db.execute("DELETE FROM payment_methods WHERE id = ?", (method_id,))
    if removed.rowcount == 0:
        abort(404)
    record(db, user, "payment_method.removed", {"method_id": method_id})
    db.commit()
    return "", 204

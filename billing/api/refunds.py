import secrets

from flask import Blueprint, abort, jsonify, request

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all, fetch_one
from ..money import from_cents, parse_amount, to_cents
from ..pagination import page_body, page_from
from .audit import record
from .payments import GatewayError, gateway

bp = Blueprint("refunds", __name__, url_prefix="/refunds")

REASONS = ("requested_by_customer", "duplicate", "fraudulent", "service_issue")
COLUMNS = "id, payment_id, amount_cents, reason, status, created_by, created_at"


def _refund(account_id, refund_id):
    refund = fetch_one(f"SELECT {COLUMNS} FROM refunds WHERE id = ? AND account_id = ?", (refund_id, account_id))
    if refund is None:
        abort(404)
    return refund


@bp.get("")
def list_refunds():
    user = require_user()
    page = page_from(request.args)
    rows = fetch_all(
        f"SELECT {COLUMNS} FROM refunds WHERE account_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
        (user["account_id"], *page.params),
    )
    return jsonify(page_body(rows, page))


@bp.post("")
def create_refund():
    user = require_user()
    body = validators.json_body(request)
    payment = fetch_one(
        "SELECT id, gateway_charge_id, amount_cents, refunded_cents, status FROM payments WHERE id = ? AND account_id = ?",
        (validators.positive_int(body.get("payment_id"), "payment_id"), user["account_id"]),
    )
    if payment is None:
        abort(404)
    if payment["status"] not in ("succeeded", "partially_refunded"):
        return jsonify(error="only completed payments can be refunded"), 409
    reason = validators.one_of(body.get("reason", "requested_by_customer"), REASONS, "reason")

    remaining = payment["amount_cents"] - payment["refunded_cents"]
    try:
        amount = to_cents(parse_amount(body.get("amount", from_cents(remaining))))
    except ValueError:
        raise validators.ValidationError("amount", "amount must be a number") from None

    try:
        result = gateway(
            "/refunds",
            {"charge": payment["gateway_charge_id"], "amount": amount},
            f"refund-{payment['id']}-{secrets.token_hex(8)}",
        )
    except GatewayError:
        return jsonify(error="the refund could not be sent to the gateway"), 502

    db = connect()
    refund_id = db.execute(
        "INSERT INTO refunds (account_id, payment_id, amount_cents, reason, gateway_refund_id, status, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user["account_id"], payment["id"], amount, reason, result.get("id"), result.get("status", "pending"), user["id"]),
    ).lastrowid
    db.execute(
        "UPDATE payments SET refunded_cents = refunded_cents + ?, status = ? WHERE id = ?",
        (amount, "refunded" if amount >= remaining else "partially_refunded", payment["id"]),
    )
    record(db, user, "refund.created", {"refund_id": refund_id, "payment_id": payment["id"], "amount_cents": amount})
    db.commit()
    return jsonify(_refund(user["account_id"], refund_id)), 201

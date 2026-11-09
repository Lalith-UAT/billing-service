from flask import Blueprint, abort, jsonify, request

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all, fetch_one
from ..money import from_cents, to_cents
from .audit import record
from .customers import get_customer

bp = Blueprint("credits", __name__, url_prefix="/customers/<int:customer_id>/credits")


@bp.get("")
def list_credits(customer_id):
    user = require_user()
    customer = get_customer(user["account_id"], customer_id)
    entries = fetch_all(
        "SELECT id, invoice_id, amount_cents, note, created_by, created_at FROM credits "
        "WHERE customer_id = ? AND account_id = ? ORDER BY id DESC",
        (customer["id"], user["account_id"]),
    )
    return jsonify(balance_cents=customer["balance_cents"], data=entries)


@bp.post("")
def grant_credit(customer_id):
    user = require_user()
    customer = get_customer(user["account_id"], customer_id)
    body = validators.json_body(request)
    amount = to_cents(validators.positive_amount(body.get("amount")))
    note = validators.text(body, "note", max_length=500)

    db = connect()
    db.execute(
        "INSERT INTO credits (account_id, customer_id, amount_cents, note, created_by) VALUES (?, ?, ?, ?, ?)",
        (user["account_id"], customer["id"], amount, note, user["id"]),
    )
    db.execute(
        "UPDATE customers SET balance_cents = balance_cents + ? WHERE id = ? AND account_id = ?",
        (amount, customer["id"], user["account_id"]),
    )
    record(db, user, "credit.granted", {"customer_id": customer["id"], "amount_cents": amount})
    db.commit()
    return jsonify(get_customer(user["account_id"], customer_id)), 201


@bp.post("/apply")
def apply_credit(customer_id):
    user = require_user()
    customer = get_customer(user["account_id"], customer_id)
    body = validators.json_body(request)
    invoice = fetch_one(
        "SELECT id, amount_due_cents, status FROM invoices WHERE id = ? AND account_id = ? AND customer_id = ?",
        (validators.positive_int(body.get("invoice_id"), "invoice_id"), user["account_id"], customer["id"]),
    )
    if invoice is None:
        abort(404)
    if invoice["status"] != "open":
        return jsonify(error="credit can only be applied to open invoices"), 409

    largest = min(customer["balance_cents"], invoice["amount_due_cents"])
    amount = to_cents(validators.positive_amount(body.get("amount", from_cents(largest))))
    if amount > invoice["amount_due_cents"]:
        raise validators.ValidationError("amount", "that is more than the invoice's amount due")

    db = connect()
    taken = db.execute(
        "UPDATE customers SET balance_cents = balance_cents - ? WHERE id = ? AND account_id = ? AND balance_cents >= ?",
        (amount, customer["id"], user["account_id"], amount),
    )
    applied = db.execute(
        "UPDATE invoices SET amount_due_cents = amount_due_cents - ?, "
        "status = CASE WHEN amount_due_cents = ? THEN 'paid' ELSE status END "
        "WHERE id = ? AND status = 'open' AND amount_due_cents >= ?",
        (amount, amount, invoice["id"], amount),
    )
    if taken.rowcount == 0 or applied.rowcount == 0:
        db.rollback()
        return jsonify(error="not enough credit, or the invoice changed; try again"), 409
    db.execute(
        "INSERT INTO credits (account_id, customer_id, invoice_id, amount_cents, note, created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (user["account_id"], customer["id"], invoice["id"], -amount, "applied to invoice", user["id"]),
    )
    record(db, user, "credit.applied", {"invoice_id": invoice["id"], "amount_cents": amount})
    db.commit()
    return jsonify(get_customer(user["account_id"], customer_id))

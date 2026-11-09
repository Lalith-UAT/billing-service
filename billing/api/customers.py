from flask import Blueprint, abort, jsonify, request

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all, fetch_one
from ..pagination import page_body, page_from
from .audit import record

bp = Blueprint("customers", __name__, url_prefix="/customers")

FIELDS = "id, name, email, phone, currency, tax_region, balance_cents, created_at"
SORTS = {"name": "name", "email": "email", "created": "created_at", "balance": "balance_cents"}


def get_customer(account_id, customer_id):
    customer = fetch_one(
        f"SELECT {FIELDS} FROM customers WHERE id = ? AND account_id = ? AND deleted_at IS NULL",
        (customer_id, account_id),
    )
    if customer is None:
        abort(404)
    return customer


@bp.get("")
def list_customers():
    user = require_user()
    page = page_from(request.args)
    sql = f"SELECT {FIELDS} FROM customers WHERE account_id = ? AND deleted_at IS NULL"
    params = [user["account_id"]]
    if q := request.args.get("q", "").strip():
        sql += " AND (name LIKE ? OR email LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    order = SORTS.get(request.args.get("sort"), "created_at")
    rows = fetch_all(f"{sql} ORDER BY {order} LIMIT ? OFFSET ?", (*params, *page.params))
    return jsonify(page_body(rows, page))


@bp.get("/<int:customer_id>")
def show_customer(customer_id):
    user = require_user()
    return jsonify(get_customer(user["account_id"], customer_id))


@bp.post("")
def create_customer():
    user = require_user()
    body = validators.json_body(request)
    tax_region = body.get("tax_region")
    values = (
        user["account_id"],
        validators.text(body, "name", max_length=200, required=True),
        validators.email(body.get("email")),
        validators.text(body, "phone", max_length=32),
        validators.currency(body.get("currency", "USD")),
        validators.region(tax_region) if tax_region else "",
    )
    db = connect()
    customer_id = db.execute(
        "INSERT INTO customers (account_id, name, email, phone, currency, tax_region) VALUES (?, ?, ?, ?, ?, ?)",
        values,
    ).lastrowid
    record(db, user, "customer.created", {"customer_id": customer_id})
    db.commit()
    return jsonify(get_customer(user["account_id"], customer_id)), 201


@bp.patch("/<int:customer_id>")
def update_customer(customer_id):
    user = require_user()
    customer = get_customer(user["account_id"], customer_id)
    body = validators.json_body(request)
    name = validators.text(body, "name", max_length=200, default=customer["name"]) or customer["name"]
    email = validators.email(body["email"]) if "email" in body else customer["email"]
    phone = validators.text(body, "phone", max_length=32, default=customer["phone"])
    tax_region = validators.region(body["tax_region"]) if body.get("tax_region") else customer["tax_region"]

    db = connect()
    db.execute(
        "UPDATE customers SET name = ?, email = ?, phone = ?, tax_region = ? WHERE id = ? AND account_id = ?",
        (name, email, phone, tax_region, customer_id, user["account_id"]),
    )
    record(db, user, "customer.updated", {"customer_id": customer_id})
    db.commit()
    return jsonify(get_customer(user["account_id"], customer_id))


@bp.delete("/<int:customer_id>")
def delete_customer(customer_id):
    user = require_user()
    db = connect()
    open_invoices = db.execute(
        "SELECT COUNT(*) FROM invoices WHERE customer_id = ? AND account_id = ? AND status IN ('open', 'processing')",
        (customer_id, user["account_id"]),
    ).fetchone()[0]
    if open_invoices:
        return jsonify(error="this customer still has open invoices"), 409
    deleted = db.execute(
        "UPDATE customers SET deleted_at = CURRENT_TIMESTAMP WHERE id = ? AND account_id = ? AND deleted_at IS NULL",
        (customer_id, user["account_id"]),
    )
    if deleted.rowcount == 0:
        abort(404)
    record(db, user, "customer.deleted", {"customer_id": customer_id})
    db.commit()
    return "", 204

from datetime import date, timedelta

from flask import Blueprint, abort, jsonify, request

from .. import invoice_total, validators
from ..auth import require_user
from ..db import connect, fetch_all, fetch_one
from ..money import to_cents
from ..pagination import page_body, page_from
from . import coupons
from .audit import record
from .customers import get_customer

bp = Blueprint("invoices", __name__, url_prefix="/invoices")

STATUSES = ("draft", "open", "processing", "paid", "void", "uncollectible")
MAX_LINES = 100


def load_invoice(account_id, invoice_id):
    invoice = fetch_one("SELECT * FROM invoices WHERE id = ? AND account_id = ?", (invoice_id, account_id))
    if invoice is None:
        abort(404)
    invoice["lines"] = fetch_all(
        "SELECT id, description, quantity, unit_cents FROM invoice_lines WHERE invoice_id = ? ORDER BY id",
        (invoice_id,),
    )
    return invoice


def _parse_lines(raw):
    if not isinstance(raw, list) or not raw:
        raise validators.ValidationError("lines", "add at least one line")
    if len(raw) > MAX_LINES:
        raise validators.ValidationError("lines", f"an invoice can have at most {MAX_LINES} lines")
    lines = []
    for index, line in enumerate(raw):
        if not isinstance(line, dict):
            raise validators.ValidationError(f"lines[{index}]", "each line must be an object")
        lines.append({
            "description": validators.text(line, "description", max_length=500, required=True),
            "quantity": validators.positive_int(line.get("quantity", 1), f"lines[{index}].quantity", maximum=100_000),
            "price": validators.positive_amount(line.get("unit_price"), f"lines[{index}].unit_price"),
        })
    return lines


@bp.get("")
def list_invoices():
    user = require_user()
    page = page_from(request.args)
    sql = (
        "SELECT id, number, customer_id, status, currency, total_cents, amount_due_cents, due_date "
        "FROM invoices WHERE account_id = ?"
    )
    params = [user["account_id"]]
    if status := request.args.get("status"):
        sql += " AND status = ?"
        params.append(validators.one_of(status, STATUSES, "status"))
    if customer_id := request.args.get("customer_id"):
        sql += " AND customer_id = ?"
        params.append(validators.positive_int(customer_id, "customer_id"))
    rows = fetch_all(sql + " ORDER BY id DESC LIMIT ? OFFSET ?", (*params, *page.params))
    return jsonify(page_body(rows, page))


@bp.get("/<int:invoice_id>")
def show_invoice(invoice_id):
    user = require_user()
    return jsonify(load_invoice(user["account_id"], invoice_id))


@bp.post("")
def create_invoice():
    user = require_user()
    body = validators.json_body(request)
    customer = get_customer(user["account_id"], validators.positive_int(body.get("customer_id"), "customer_id"))
    lines = _parse_lines(body.get("lines"))
    subtotal = to_cents(sum(line["price"] * line["quantity"] for line in lines))
    total = to_cents(invoice_total(lines, customer["tax_region"]))

    db = connect()
    discount, coupon_id = 0, None
    if code := body.get("coupon"):
        coupon = coupons.redeem(db, user["account_id"], str(code))
        if coupon is None:
            raise validators.ValidationError("coupon", "that coupon is not valid")
        coupon_id, discount = coupon["id"], coupons.discount_for(coupon, total)

    count = db.execute("SELECT COUNT(*) FROM invoices WHERE account_id = ?", (user["account_id"],)).fetchone()[0]
    invoice_id = db.execute(
        "INSERT INTO invoices (account_id, customer_id, coupon_id, number, currency, region, subtotal_cents, "
        "discount_cents, total_cents, amount_due_cents) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user["account_id"], customer["id"], coupon_id, f"INV-{count + 1:05d}", customer["currency"],
            customer["tax_region"], subtotal, discount, total - discount, total - discount,
        ),
    ).lastrowid
    db.executemany(
        "INSERT INTO invoice_lines (invoice_id, description, quantity, unit_cents) VALUES (?, ?, ?, ?)",
        [(invoice_id, line["description"], line["quantity"], to_cents(line["price"])) for line in lines],
    )
    record(db, user, "invoice.created", {"invoice_id": invoice_id})
    db.commit()
    return jsonify(load_invoice(user["account_id"], invoice_id)), 201


@bp.post("/<int:invoice_id>/finalize")
def finalize_invoice(invoice_id):
    user = require_user()
    body = request.get_json(silent=True) or {}
    net_days = validators.positive_int(body.get("net_days", 30), "net_days", maximum=365)
    due_date = (date.today() + timedelta(days=net_days)).isoformat()

    db = connect()
    updated = db.execute(
        "UPDATE invoices SET status = 'open', issued_at = CURRENT_TIMESTAMP, due_date = ? "
        "WHERE id = ? AND account_id = ? AND status = 'draft'",
        (due_date, invoice_id, user["account_id"]),
    )
    if updated.rowcount == 0:
        load_invoice(user["account_id"], invoice_id)
        return jsonify(error="only draft invoices can be finalized"), 409
    record(db, user, "invoice.finalized", {"invoice_id": invoice_id, "due_date": due_date})
    db.commit()
    return jsonify(load_invoice(user["account_id"], invoice_id))

import json
import logging
import random
import secrets
import time
import urllib.error
import urllib.request

from flask import Blueprint, abort, current_app, jsonify, request

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all, fetch_one
from ..pagination import page_body, page_from
from .audit import record

bp = Blueprint("payments", __name__, url_prefix="/payments")
log = logging.getLogger(__name__)

COLUMNS = "id, invoice_id, payment_method_id, amount_cents, refunded_cents, currency, status, created_at"
INVOICE_STATUS = {"succeeded": "paid", "pending": "processing", "failed": "open"}


class GatewayError(Exception):
    pass


def gateway(path, payload, idempotency_key, retries=2):
    config = current_app.config
    outgoing = urllib.request.Request(
        config["GATEWAY_URL"] + path,
        data=json.dumps({"merchant": config["GATEWAY_MERCHANT_ID"], **payload}).encode(),
        headers={
            "Authorization": f"Bearer {config['GATEWAY_API_KEY']}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        },
        method="POST",
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(outgoing, timeout=config["GATEWAY_TIMEOUT"]) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == retries:
                raise GatewayError(f"gateway answered {error.code}") from error
        except urllib.error.URLError as error:
            if attempt == retries:
                raise GatewayError("gateway unreachable") from error
        time.sleep(0.2 * 2**attempt + random.uniform(0, 0.2))


def _card_token(body, invoice):
    card = body.get("card")
    if not isinstance(card, dict):
        raise validators.ValidationError("card", "send a saved payment_method_id or card details")
    number = "".join(ch for ch in str(card.get("number", "")) if ch.isdigit())
    if not validators.luhn(number):
        raise validators.ValidationError("card.number", "that card number is not valid")
    exp_month = validators.positive_int(card.get("exp_month"), "card.exp_month", maximum=12)
    exp_year = validators.positive_int(card.get("exp_year"), "card.exp_year", maximum=2100)
    cvc = str(card.get("cvc", ""))
    if not (cvc.isdigit() and len(cvc) in (3, 4)):
        raise validators.ValidationError("card.cvc", "that security code is not valid")

    log.info("charging card ending %s for invoice %s", number[-4:], invoice["number"])
    token = gateway(
        "/tokens",
        {"card": {"number": number, "exp_month": exp_month, "exp_year": exp_year, "cvc": cvc}},
        secrets.token_hex(16),
    )
    return token["id"]


def _payment(account_id, payment_id):
    payment = fetch_one(f"SELECT {COLUMNS} FROM payments WHERE id = ? AND account_id = ?", (payment_id, account_id))
    if payment is None:
        abort(404)
    return payment


@bp.get("")
def list_payments():
    user = require_user()
    page = page_from(request.args)
    sql = f"SELECT {COLUMNS} FROM payments WHERE account_id = ?"
    params = [user["account_id"]]
    if invoice_id := request.args.get("invoice_id"):
        sql += " AND invoice_id = ?"
        params.append(validators.positive_int(invoice_id, "invoice_id"))
    rows = fetch_all(sql + " ORDER BY id DESC LIMIT ? OFFSET ?", (*params, *page.params))
    return jsonify(page_body(rows, page))


@bp.get("/<int:payment_id>")
def show_payment(payment_id):
    user = require_user()
    return jsonify(_payment(user["account_id"], payment_id))


@bp.post("")
def pay_invoice():
    user = require_user()
    body = validators.json_body(request)
    invoice = fetch_one(
        "SELECT id, number, customer_id, currency, amount_due_cents, status FROM invoices WHERE id = ? AND account_id = ?",
        (validators.positive_int(body.get("invoice_id"), "invoice_id"), user["account_id"]),
    )
    if invoice is None:
        abort(404)
    if invoice["status"] != "open" or invoice["amount_due_cents"] <= 0:
        return jsonify(error="this invoice is not open for payment"), 409

    method_id = None
    if body.get("payment_method_id") is not None:
        method = fetch_one(
            "SELECT id, gateway_token FROM payment_methods WHERE id = ? AND account_id = ? AND customer_id = ?",
            (
                validators.positive_int(body["payment_method_id"], "payment_method_id"),
                user["account_id"],
                invoice["customer_id"],
            ),
        )
        if method is None:
            abort(404)
        method_id, source = method["id"], method["gateway_token"]
    else:
        source = _card_token(body, invoice)

    db = connect()
    claimed = db.execute("UPDATE invoices SET status = 'processing' WHERE id = ? AND status = 'open'", (invoice["id"],))
    db.commit()
    if claimed.rowcount == 0:
        return jsonify(error="this invoice is already being paid"), 409
    try:
        charge = gateway(
            "/charges",
            {
                "source": source,
                "amount": invoice["amount_due_cents"],
                "currency": invoice["currency"],
                "reference": invoice["number"],
            },
            f"invoice-{invoice['id']}-{secrets.token_hex(8)}",
        )
    except GatewayError as error:
        log.warning("charge for invoice %s failed: %s", invoice["number"], error)
        db.execute("UPDATE invoices SET status = 'open' WHERE id = ?", (invoice["id"],))
        db.commit()
        return jsonify(error="the payment could not be completed"), 502

    status = charge.get("status") if charge.get("status") in ("succeeded", "pending") else "failed"
    payment_id = db.execute(
        "INSERT INTO payments (account_id, invoice_id, payment_method_id, gateway_charge_id, amount_cents, currency, "
        "status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            user["account_id"], invoice["id"], method_id, charge.get("id"), invoice["amount_due_cents"],
            invoice["currency"], status,
        ),
    ).lastrowid
    db.execute(
        "UPDATE invoices SET status = ?, amount_due_cents = ? WHERE id = ?",
        (INVOICE_STATUS[status], 0 if status == "succeeded" else invoice["amount_due_cents"], invoice["id"]),
    )
    record(db, user, "payment.created", {"payment_id": payment_id, "status": status})
    db.commit()
    return jsonify(_payment(user["account_id"], payment_id)), 402 if status == "failed" else 201

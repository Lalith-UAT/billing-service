from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request

from .. import validators
from ..auth import require_admin, require_user
from ..db import connect, fetch_all, fetch_one
from ..money import CENT, format_money, to_cents
from .audit import record

bp = Blueprint("currencies", __name__, url_prefix="/currencies")

MAX_RATE = Decimal("100000")


def _usd_rate(code, field):
    row = fetch_one("SELECT usd_rate FROM currencies WHERE code = ?", (validators.currency(code, field),))
    if row is None:
        raise validators.ValidationError(field, f"{code} is not a supported currency")
    return Decimal(row["usd_rate"])


@bp.get("")
def list_currencies():
    return jsonify(data=fetch_all("SELECT code, name, usd_rate, updated_at FROM currencies ORDER BY code"))


@bp.get("/convert")
def convert():
    require_user()
    amount = validators.positive_amount(request.args.get("amount"))
    source = request.args.get("from", "USD")
    target = request.args.get("to", "USD")
    converted = (amount * _usd_rate(source, "from") / _usd_rate(target, "to")).quantize(CENT)
    return jsonify(
        amount=str(amount),
        source=source,
        target=target,
        converted=str(converted),
        formatted=format_money(to_cents(converted), target),
    )


@bp.put("/<code>")
def set_rate(code):
    admin = require_admin()
    code = validators.currency(code.upper(), "code")
    body = validators.json_body(request)
    try:
        rate = Decimal(str(body.get("usd_rate")))
    except InvalidOperation:
        raise validators.ValidationError("usd_rate", "usd_rate must be a number") from None
    if not rate.is_finite() or not 0 < rate <= MAX_RATE:
        raise validators.ValidationError("usd_rate", "usd_rate must be a positive number")
    name = validators.text(body, "name", max_length=60) or code

    db = connect()
    db.execute(
        "INSERT INTO currencies (code, name, usd_rate) VALUES (?, ?, ?) ON CONFLICT (code) DO UPDATE SET "
        "name = excluded.name, usd_rate = excluded.usd_rate, updated_at = CURRENT_TIMESTAMP",
        (code, name, str(rate)),
    )
    record(db, admin, "admin.currency_rate_set", {"code": code, "usd_rate": str(rate)})
    db.commit()
    return jsonify(fetch_one("SELECT code, name, usd_rate, updated_at FROM currencies WHERE code = ?", (code,)))

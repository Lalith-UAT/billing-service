import re
from datetime import date

from flask import Blueprint, jsonify, request

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all, fetch_one
from ..money import percent_of, to_cents
from .audit import record

bp = Blueprint("coupons", __name__, url_prefix="/coupons")

CODE = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,31}$")
COLUMNS = "id, code, percent_off, amount_off_cents, max_redemptions, redeemed, expires_on, created_at"


def _usable(coupon):
    if coupon["expires_on"] and date.fromisoformat(coupon["expires_on"]) < date.today():
        return False
    return coupon["max_redemptions"] is None or coupon["redeemed"] < coupon["max_redemptions"]


def redeem(db, account_id, code):
    coupon = fetch_one(f"SELECT {COLUMNS} FROM coupons WHERE account_id = ? AND code = ?", (account_id, code.upper()))
    if coupon is None or not _usable(coupon):
        return None
    claimed = db.execute(
        "UPDATE coupons SET redeemed = redeemed + 1 "
        "WHERE id = ? AND (max_redemptions IS NULL OR redeemed < max_redemptions)",
        (coupon["id"],),
    )
    return coupon if claimed.rowcount else None


def discount_for(coupon, total_cents):
    if coupon["percent_off"]:
        return min(percent_of(total_cents, coupon["percent_off"]), total_cents)
    return min(coupon["amount_off_cents"] or 0, total_cents)


@bp.get("")
def list_coupons():
    user = require_user()
    coupons = fetch_all(
        f"SELECT {COLUMNS} FROM coupons WHERE account_id = ? ORDER BY created_at DESC",
        (user["account_id"],),
    )
    return jsonify(data=coupons)


@bp.post("")
def create_coupon():
    user = require_user()
    body = validators.json_body(request)
    code = str(body.get("code", "")).strip().upper()
    if not CODE.match(code):
        raise validators.ValidationError("code", "use 3 to 32 letters, digits or dashes")

    percent_off = amount_off = None
    if "percent_off" in body:
        percent_off = validators.positive_int(body["percent_off"], "percent_off", maximum=100)
    if "amount_off" in body:
        amount_off = to_cents(validators.positive_amount(body["amount_off"], "amount_off"))
    if (percent_off is None) == (amount_off is None):
        raise validators.ValidationError("percent_off", "set either percent_off or amount_off")
    max_redemptions = None
    if body.get("max_redemptions") is not None:
        max_redemptions = validators.positive_int(body["max_redemptions"], "max_redemptions")
    expires_on = validators.iso_date(body["expires_on"], "expires_on") if body.get("expires_on") else None

    db = connect()
    if fetch_one("SELECT 1 FROM coupons WHERE account_id = ? AND code = ?", (user["account_id"], code)):
        return jsonify(error="a coupon with that code already exists"), 409
    coupon_id = db.execute(
        "INSERT INTO coupons (account_id, code, percent_off, amount_off_cents, max_redemptions, expires_on) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user["account_id"], code, percent_off, amount_off, max_redemptions, expires_on),
    ).lastrowid
    record(db, user, "coupon.created", {"coupon_id": coupon_id, "code": code})
    db.commit()
    return jsonify(fetch_one(f"SELECT {COLUMNS} FROM coupons WHERE id = ?", (coupon_id,))), 201

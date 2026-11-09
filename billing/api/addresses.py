import re

from flask import Blueprint, abort, jsonify, request

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all, fetch_one
from .customers import get_customer

bp = Blueprint("addresses", __name__, url_prefix="/customers/<int:customer_id>/addresses")

KINDS = ("billing", "shipping")
POSTAL_CODE = re.compile(r"^[A-Za-z0-9 -]{0,12}$")
COLUMNS = "id, customer_id, kind, line1, line2, city, region, postal_code, country, created_at"


def _read(body):
    postal_code = validators.text(body, "postal_code", max_length=12)
    if not POSTAL_CODE.match(postal_code):
        raise validators.ValidationError("postal_code", "postal code has characters we don't expect")
    return {
        "kind": validators.one_of(body.get("kind", "billing"), KINDS, "kind"),
        "line1": validators.text(body, "line1", required=True),
        "line2": validators.text(body, "line2"),
        "city": validators.text(body, "city", max_length=100, required=True),
        "region": validators.text(body, "region", max_length=100),
        "postal_code": postal_code,
        "country": validators.country(body.get("country")),
    }


def _address(account_id, customer_id, address_id):
    address = fetch_one(
        f"SELECT {COLUMNS} FROM addresses WHERE id = ? AND customer_id = ? AND account_id = ?",
        (address_id, customer_id, account_id),
    )
    if address is None:
        abort(404)
    return address


@bp.get("")
def list_addresses(customer_id):
    user = require_user()
    get_customer(user["account_id"], customer_id)
    addresses = fetch_all(
        f"SELECT {COLUMNS} FROM addresses WHERE customer_id = ? AND account_id = ? ORDER BY id",
        (customer_id, user["account_id"]),
    )
    return jsonify(data=addresses)


@bp.post("")
def add_address(customer_id):
    user = require_user()
    get_customer(user["account_id"], customer_id)
    address = _read(validators.json_body(request))
    db = connect()
    address_id = db.execute(
        "INSERT INTO addresses (account_id, customer_id, kind, line1, line2, city, region, postal_code, country) "
        "VALUES (:account_id, :customer_id, :kind, :line1, :line2, :city, :region, :postal_code, :country)",
        {"account_id": user["account_id"], "customer_id": customer_id, **address},
    ).lastrowid
    db.commit()
    return jsonify(_address(user["account_id"], customer_id, address_id)), 201


@bp.delete("/<int:address_id>")
def delete_address(customer_id, address_id):
    user = require_user()
    db = connect()
    deleted = db.execute(
        "DELETE FROM addresses WHERE id = ? AND customer_id = ? AND account_id = ?",
        (address_id, customer_id, user["account_id"]),
    )
    if deleted.rowcount == 0:
        abort(404)
    db.commit()
    return "", 204

import re

from flask import Blueprint, abort, jsonify, request

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all, fetch_one
from ..money import format_money, to_cents
from .audit import record

bp = Blueprint("plans", __name__, url_prefix="/plans")

CODE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,40}$")
INTERVALS = ("month", "year")


def _with_price(plan):
    plan["price"] = format_money(plan["amount_cents"], plan["currency"])
    return plan


def _plan(account_id, plan_id):
    plan = fetch_one(
        "SELECT id, code, name, amount_cents, currency, interval, active FROM plans WHERE id = ? AND account_id = ?",
        (plan_id, account_id),
    )
    if plan is None:
        abort(404)
    return _with_price(plan)


@bp.get("")
def list_plans():
    user = require_user()
    include_archived = request.args.get("include_archived") == "true"
    plans = fetch_all(
        "SELECT id, code, name, amount_cents, currency, interval, active FROM plans "
        "WHERE account_id = ? AND (active = 1 OR ?) ORDER BY amount_cents",
        (user["account_id"], int(include_archived)),
    )
    return jsonify(data=[_with_price(plan) for plan in plans])


@bp.post("")
def create_plan():
    user = require_user()
    body = validators.json_body(request)
    code = str(body.get("code", "")).strip().lower()
    if not CODE.match(code):
        raise validators.ValidationError("code", "use lowercase letters, digits, dashes or underscores")
    name = validators.text(body, "name", max_length=80, required=True)
    amount = to_cents(validators.positive_amount(body.get("amount")))
    currency = validators.currency(body.get("currency", "USD"))
    interval = validators.one_of(body.get("interval", "month"), INTERVALS, "interval")

    db = connect()
    if fetch_one("SELECT 1 FROM plans WHERE account_id = ? AND code = ?", (user["account_id"], code)):
        return jsonify(error="a plan with that code already exists"), 409
    plan_id = db.execute(
        "INSERT INTO plans (account_id, code, name, amount_cents, currency, interval) VALUES (?, ?, ?, ?, ?, ?)",
        (user["account_id"], code, name, amount, currency, interval),
    ).lastrowid
    record(db, user, "plan.created", {"plan_id": plan_id, "code": code})
    db.commit()
    return jsonify(_plan(user["account_id"], plan_id)), 201

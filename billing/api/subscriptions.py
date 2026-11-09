from datetime import date, timedelta

from flask import Blueprint, abort, jsonify, request

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all, fetch_one
from ..pagination import page_body, page_from
from .audit import record
from .customers import get_customer

bp = Blueprint("subscriptions", __name__, url_prefix="/subscriptions")

PERIOD_DAYS = {"month": 30, "year": 365}
SELECT = (
    "SELECT s.id, s.customer_id, s.plan_id, p.code AS plan, p.interval, s.quantity, s.status, "
    "s.current_period_end, s.cancel_at_period_end, s.created_at "
    "FROM subscriptions s JOIN plans p ON p.id = s.plan_id"
)


def _subscription(account_id, subscription_id):
    subscription = fetch_one(f"{SELECT} WHERE s.id = ? AND s.account_id = ?", (subscription_id, account_id))
    if subscription is None:
        abort(404)
    return subscription


def _active_plan(account_id, plan_id):
    plan = fetch_one("SELECT id, interval, active FROM plans WHERE id = ? AND account_id = ?", (plan_id, account_id))
    if plan is None or not plan["active"]:
        raise validators.ValidationError("plan_id", "choose an active plan")
    return plan


@bp.get("")
def list_subscriptions():
    user = require_user()
    page = page_from(request.args)
    sql, params = f"{SELECT} WHERE s.account_id = ?", [user["account_id"]]
    if status := request.args.get("status"):
        sql += " AND s.status = ?"
        params.append(validators.one_of(status, ("active", "canceled"), "status"))
    if customer_id := request.args.get("customer_id"):
        sql += " AND s.customer_id = ?"
        params.append(validators.positive_int(customer_id, "customer_id"))
    rows = fetch_all(sql + " ORDER BY s.id DESC LIMIT ? OFFSET ?", (*params, *page.params))
    return jsonify(page_body(rows, page))


@bp.get("/<int:subscription_id>")
def show_subscription(subscription_id):
    user = require_user()
    return jsonify(_subscription(user["account_id"], subscription_id))


@bp.post("")
def create_subscription():
    user = require_user()
    body = validators.json_body(request)
    customer = get_customer(user["account_id"], validators.positive_int(body.get("customer_id"), "customer_id"))
    plan = _active_plan(user["account_id"], validators.positive_int(body.get("plan_id"), "plan_id"))
    quantity = validators.positive_int(body.get("quantity", 1), "quantity", maximum=10_000)
    period_end = date.today() + timedelta(days=PERIOD_DAYS[plan["interval"]])

    db = connect()
    subscription_id = db.execute(
        "INSERT INTO subscriptions (account_id, customer_id, plan_id, quantity, current_period_end) VALUES (?, ?, ?, ?, ?)",
        (user["account_id"], customer["id"], plan["id"], quantity, period_end.isoformat()),
    ).lastrowid
    record(db, user, "subscription.created", {"subscription_id": subscription_id, "plan_id": plan["id"]})
    db.commit()
    return jsonify(_subscription(user["account_id"], subscription_id)), 201


@bp.post("/<int:subscription_id>/cancel")
def cancel_subscription(subscription_id):
    user = require_user()
    subscription = _subscription(user["account_id"], subscription_id)
    if subscription["status"] != "active":
        return jsonify(error="this subscription is already canceled"), 409
    at_period_end = bool((request.get_json(silent=True) or {}).get("at_period_end", True))

    db = connect()
    if at_period_end:
        db.execute(
            "UPDATE subscriptions SET cancel_at_period_end = 1 WHERE id = ? AND account_id = ?",
            (subscription_id, user["account_id"]),
        )
    else:
        db.execute(
            "UPDATE subscriptions SET status = 'canceled', current_period_end = ? WHERE id = ? AND account_id = ?",
            (date.today().isoformat(), subscription_id, user["account_id"]),
        )
    record(db, user, "subscription.canceled", {"subscription_id": subscription_id, "at_period_end": at_period_end})
    db.commit()
    return jsonify(_subscription(user["account_id"], subscription_id))

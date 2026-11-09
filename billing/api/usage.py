import re
import secrets
from datetime import date, timedelta

from flask import Blueprint, abort, jsonify, request

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all, fetch_one

bp = Blueprint("usage", __name__, url_prefix="/usage")

METRIC = re.compile(r"^[a-z][a-z0-9_.]{1,63}$")
EVENT_COLUMNS = "id, subscription_id, metric, quantity, idempotency_key, recorded_at"


@bp.post("")
def record_usage():
    user = require_user()
    body = validators.json_body(request)
    subscription = fetch_one(
        "SELECT id, status FROM subscriptions WHERE id = ? AND account_id = ?",
        (validators.positive_int(body.get("subscription_id"), "subscription_id"), user["account_id"]),
    )
    if subscription is None:
        abort(404)
    if subscription["status"] != "active":
        return jsonify(error="usage can only be recorded on active subscriptions"), 409

    metric = str(body.get("metric", ""))
    if not METRIC.match(metric):
        raise validators.ValidationError("metric", "use a lowercase metric name like api.calls")
    quantity = validators.positive_int(body.get("quantity"), "quantity", maximum=1_000_000)
    key = validators.text(body, "idempotency_key", max_length=64) or secrets.token_hex(16)

    db = connect()
    inserted = db.execute(
        "INSERT OR IGNORE INTO usage_events (account_id, subscription_id, metric, quantity, idempotency_key) "
        "VALUES (?, ?, ?, ?, ?)",
        (user["account_id"], subscription["id"], metric, quantity, key),
    )
    db.commit()
    event = fetch_one(
        f"SELECT {EVENT_COLUMNS} FROM usage_events WHERE account_id = ? AND idempotency_key = ?",
        (user["account_id"], key),
    )
    return jsonify(event), 201 if inserted.rowcount else 200


@bp.get("/summary")
def usage_summary():
    user = require_user()
    subscription_id = validators.positive_int(request.args.get("subscription_id"), "subscription_id")
    default_since = (date.today() - timedelta(days=30)).isoformat()
    since = validators.iso_date(request.args.get("since", default_since), "since")
    metrics = fetch_all(
        "SELECT metric, SUM(quantity) AS total, COUNT(*) AS events FROM usage_events "
        "WHERE account_id = ? AND subscription_id = ? AND recorded_at >= ? GROUP BY metric ORDER BY metric",
        (user["account_id"], subscription_id, since),
    )
    return jsonify(subscription_id=subscription_id, since=since, metrics=metrics)

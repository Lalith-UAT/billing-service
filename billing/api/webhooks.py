import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlparse

from flask import Blueprint, abort, current_app, jsonify, request

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all
from .audit import record

bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")

TOLERANCE_SECONDS = 300
EVENT_TYPES = (
    "invoice.created", "invoice.paid", "invoice.voided", "payment.failed", "refund.created", "subscription.canceled",
)


def _signature_ok(timestamp, body, signature):
    secret = current_app.config["WEBHOOK_SECRET"].encode()
    expected = hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.encode(), expected.encode())


def _payment_for(db, charge_id):
    return db.execute(
        "SELECT id, invoice_id, amount_cents, status FROM payments WHERE gateway_charge_id = ?",
        (charge_id,),
    ).fetchone()


def _charge_succeeded(db, data):
    payment = _payment_for(db, data["charge"])
    if payment is None or payment["status"] != "pending":
        return
    db.execute("UPDATE payments SET status = 'succeeded' WHERE id = ?", (payment["id"],))
    db.execute("UPDATE invoices SET status = 'paid', amount_due_cents = 0 WHERE id = ?", (payment["invoice_id"],))


def _charge_failed(db, data):
    payment = _payment_for(db, data["charge"])
    if payment is None or payment["status"] == "failed":
        return
    owed_again = payment["amount_cents"] if payment["status"] == "succeeded" else 0
    db.execute("UPDATE payments SET status = 'failed' WHERE id = ?", (payment["id"],))
    db.execute(
        "UPDATE invoices SET status = 'open', amount_due_cents = amount_due_cents + ? WHERE id = ?",
        (owed_again, payment["invoice_id"]),
    )


def _refund_updated(db, data):
    db.execute("UPDATE refunds SET status = ? WHERE gateway_refund_id = ?", (data["status"], data["refund"]))


HANDLERS = {
    "charge.succeeded": _charge_succeeded,
    "charge.failed": _charge_failed,
    "refund.updated": _refund_updated,
}


@bp.post("/gateway")
def gateway_event():
    body = request.get_data()
    timestamp = request.headers.get("X-Paygate-Timestamp", "")
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > TOLERANCE_SECONDS:
        abort(400)
    if not _signature_ok(timestamp, body, request.headers.get("X-Paygate-Signature", "")):
        abort(401)
    try:
        event = json.loads(body)
        event_id, event_type = str(event["id"]), str(event["type"])
    except (ValueError, KeyError, TypeError):
        abort(400)

    db = connect()
    fresh = db.execute("INSERT OR IGNORE INTO webhook_events (id, type) VALUES (?, ?)", (event_id, event_type))
    if fresh.rowcount and event_type in HANDLERS:
        HANDLERS[event_type](db, event.get("data", {}))
    db.commit()
    return "", 204


@bp.get("/endpoints")
def list_endpoints():
    user = require_user()
    endpoints = fetch_all(
        "SELECT id, url, events, active, created_at FROM webhook_endpoints WHERE account_id = ? ORDER BY id",
        (user["account_id"],),
    )
    for endpoint in endpoints:
        endpoint["events"] = json.loads(endpoint["events"])
    return jsonify(data=endpoints)


@bp.post("/endpoints")
def add_endpoint():
    user = require_user()
    body = validators.json_body(request)
    url = validators.text(body, "url", max_length=2048, required=True)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise validators.ValidationError("url", "use an https:// URL")
    events = body.get("events") or list(EVENT_TYPES)
    if not isinstance(events, list) or any(event not in EVENT_TYPES for event in events):
        raise validators.ValidationError("events", f"pick events from: {', '.join(EVENT_TYPES)}")
    events = sorted(set(events))
    secret = secrets.token_urlsafe(32)

    db = connect()
    endpoint_id = db.execute(
        "INSERT INTO webhook_endpoints (account_id, url, secret, events) VALUES (?, ?, ?, ?)",
        (user["account_id"], url, secret, json.dumps(events)),
    ).lastrowid
    record(db, user, "webhook_endpoint.added", {"endpoint_id": endpoint_id})
    db.commit()
    return jsonify(id=endpoint_id, url=url, events=events, secret=secret), 201


@bp.delete("/endpoints/<int:endpoint_id>")
def remove_endpoint(endpoint_id):
    user = require_user()
    db = connect()
    removed = db.execute(
        "DELETE FROM webhook_endpoints WHERE id = ? AND account_id = ?",
        (endpoint_id, user["account_id"]),
    )
    if removed.rowcount == 0:
        abort(404)
    record(db, user, "webhook_endpoint.removed", {"endpoint_id": endpoint_id})
    db.commit()
    return "", 204

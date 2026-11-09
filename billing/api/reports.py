from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from .. import validators
from ..auth import require_user
from ..db import fetch_all
from ..money import format_money
from ..pagination import page_body, page_from

bp = Blueprint("reports", __name__, url_prefix="/reports")

AGING_BUCKETS = ((0, 30, "current"), (31, 60, "31-60"), (61, 90, "61-90"), (91, None, "90+"))
SORTS = {
    "issued": "i.issued_at",
    "number": "i.number",
    "customer": "c.name",
    "status": "i.status",
    "currency": "i.currency",
    "total": "i.total_cents",
    "due": "i.due_date",
    "i.issued_at": "i.issued_at",
    "i.number": "i.number",
    "c.name": "c.name",
    "i.status": "i.status",
    "i.currency": "i.currency",
    "i.total_cents": "i.total_cents",
    "i.due_date": "i.due_date",
}


@bp.get("/revenue")
def revenue():
    user = require_user()
    today = date.today()
    start = validators.iso_date(request.args.get("from", today.replace(day=1).isoformat()), "from")
    end = validators.iso_date(request.args.get("to", (today + timedelta(days=1)).isoformat()), "to")
    days = fetch_all(
        "SELECT substr(created_at, 1, 10) AS day, currency, COUNT(*) AS payments, "
        "SUM(amount_cents) AS gross_cents, SUM(refunded_cents) AS refunded_cents "
        "FROM payments WHERE account_id = ? AND status != 'failed' AND created_at >= ? AND created_at < ? "
        "GROUP BY day, currency ORDER BY day",
        (user["account_id"], start, end),
    )
    for day in days:
        day["net"] = format_money(day["gross_cents"] - day["refunded_cents"], day["currency"])
    return jsonify(start=start, end=end, days=days)


@bp.get("/invoices")
def invoice_report():
    user = require_user()
    page = page_from(request.args)
    sort = SORTS.get(request.args.get("sort", ""), "i.issued_at")
    direction = "ASC" if request.args.get("direction") == "asc" else "DESC"
    rows = fetch_all(
        "SELECT i.id, i.number, c.name AS customer, i.status, i.currency, i.total_cents, i.amount_due_cents, "
        "i.issued_at, i.due_date FROM invoices i JOIN customers c ON c.id = i.customer_id "
        f"WHERE i.account_id = ? ORDER BY {sort} {direction} LIMIT ? OFFSET ?",
        (user["account_id"], *page.params),
    )
    return jsonify(page_body(rows, page))


@bp.get("/aging")
def aging():
    user = require_user()
    rows = fetch_all(
        "SELECT currency, CAST(julianday('now') - julianday(due_date) AS INTEGER) AS days_late, amount_due_cents "
        "FROM invoices WHERE account_id = ? AND status = 'open' AND due_date IS NOT NULL",
        (user["account_id"],),
    )
    totals = {}
    for row in rows:
        late = max(row["days_late"], 0)
        bucket = next(name for low, high, name in AGING_BUCKETS if late >= low and (high is None or late <= high))
        key = (row["currency"], bucket)
        totals[key] = totals.get(key, 0) + row["amount_due_cents"]
    return jsonify(data=[
        {"currency": currency, "bucket": bucket, "amount_cents": cents, "amount": format_money(cents, currency)}
        for (currency, bucket), cents in sorted(totals.items())
    ])

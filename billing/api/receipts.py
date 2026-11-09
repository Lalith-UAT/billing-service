import os
import subprocess
import tempfile

from flask import Blueprint, abort, current_app, render_template_string, request, send_from_directory

from ..auth import require_user
from ..db import fetch_all, fetch_one
from ..money import format_money
from ..validators import one_of

bp = Blueprint("receipts", __name__, url_prefix="/receipts")

PAGE_SIZES = ("A3", "A4", "A5", "Legal", "Letter", "Tabloid")

RECEIPT_HTML = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>Receipt for {{ invoice.number }}</title></head>
<body style="font-family: sans-serif">
  <h1>{{ account.name }}</h1>
  <p>Receipt for invoice {{ invoice.number }}, paid {{ payment.created_at[:10] }}</p>
  <table>
    {% for line in lines %}
    <tr><td>{{ line.description }}</td><td>{{ line.quantity }}</td><td>{{ line.amount }}</td></tr>
    {% endfor %}
  </table>
  <p>Total paid: {{ paid }}</p>
  {% if refunded %}<p>Refunded: {{ refunded }}</p>{% endif %}
</body>
</html>
"""


def _context(account_id, payment_id):
    payment = fetch_one(
        "SELECT id, invoice_id, amount_cents, refunded_cents, currency, status, created_at FROM payments "
        "WHERE id = ? AND account_id = ? AND status != 'failed'",
        (payment_id, account_id),
    )
    if payment is None:
        abort(404)
    invoice = fetch_one("SELECT id, number FROM invoices WHERE id = ? AND account_id = ?", (payment["invoice_id"], account_id))
    lines = fetch_all(
        "SELECT description, quantity, unit_cents FROM invoice_lines WHERE invoice_id = ? ORDER BY id",
        (invoice["id"],),
    )
    for line in lines:
        line["amount"] = format_money(line["quantity"] * line["unit_cents"], payment["currency"])
    return {
        "account": fetch_one("SELECT name FROM accounts WHERE id = ?", (account_id,)),
        "payment": payment,
        "invoice": invoice,
        "lines": lines,
        "paid": format_money(payment["amount_cents"], payment["currency"]),
        "refunded": format_money(payment["refunded_cents"], payment["currency"]) if payment["refunded_cents"] else None,
    }


@bp.get("/<int:payment_id>/html")
def receipt_html(payment_id):
    user = require_user()
    return render_template_string(RECEIPT_HTML, **_context(user["account_id"], payment_id))


@bp.get("/<int:payment_id>/pdf")
def receipt_pdf(payment_id):
    user = require_user()
    context = _context(user["account_id"], payment_id)
    folder = os.path.join(current_app.config["RECEIPT_DIR"], str(user["account_id"]))
    name = f"receipt-{payment_id}.pdf"
    if not os.path.exists(os.path.join(folder, name)):
        os.makedirs(folder, exist_ok=True)
        page_size = one_of(request.args.get("size", "Letter"), PAGE_SIZES, "size")
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as html:
            html.write(render_template_string(RECEIPT_HTML, **context))
        try:
            subprocess.run(
                ["wkhtmltopdf", "--quiet", "--page-size", page_size, html.name, os.path.join(folder, name)],
                check=True,
                timeout=60,
            )
        finally:
            os.unlink(html.name)
    return send_from_directory(folder, name, as_attachment=True)

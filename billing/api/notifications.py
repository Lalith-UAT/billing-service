import logging
import random
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from flask import Blueprint, abort, current_app, jsonify, render_template_string, request

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_one
from ..money import format_money

bp = Blueprint("notifications", __name__, url_prefix="/notifications")
log = logging.getLogger(__name__)

SUBJECTS = {
    "invoice_reminder": "Invoice {number} is due soon",
    "payment_receipt": "Thanks for your payment on invoice {number}",
}
TEMPLATES = {
    "invoice_reminder": (
        "<p>Hi {{ customer.name }},</p>\n"
        "<p>Invoice {{ invoice.number }} for {{ amount }} is due on {{ invoice.due_date }}.</p>\n"
    ),
    "payment_receipt": (
        "<p>Hi {{ customer.name }},</p>\n"
        "<p>We received your payment of {{ amount }} for invoice {{ invoice.number }}. Thank you.</p>\n"
    ),
}
FOOTER = '<p style="color: #666">{{ footer }}</p>\n'
DEFAULTS = {"invoice_reminders": 1, "payment_receipts": 1, "reminder_days": 3, "footer": ""}


def send_email(to, subject, text, html=None, attempts=3):
    config = current_app.config
    message = EmailMessage()
    message["From"] = config["MAIL_FROM"]
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    for attempt in range(1, attempts + 1):
        try:
            with smtplib.SMTP(config["SMTP_HOST"], config["SMTP_PORT"], timeout=10) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if config["SMTP_USER"]:
                    smtp.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
                smtp.send_message(message)
            return True
        except (smtplib.SMTPException, OSError) as error:
            log.warning("sending %r failed on attempt %d of %d: %s", subject, attempt, attempts, error)
            if attempt < attempts:
                time.sleep(attempt + random.random())
    return False


def _settings(account_id):
    settings = fetch_one(
        "SELECT invoice_reminders, payment_receipts, reminder_days, footer FROM notification_settings WHERE account_id = ?",
        (account_id,),
    )
    return settings or dict(DEFAULTS)


def _invoice_context(account_id, invoice_id):
    invoice = fetch_one(
        "SELECT id, number, customer_id, currency, total_cents, amount_due_cents, due_date FROM invoices "
        "WHERE id = ? AND account_id = ?",
        (invoice_id, account_id),
    )
    if invoice is None:
        abort(404)
    customer = fetch_one(
        "SELECT id, name, email FROM customers WHERE id = ? AND account_id = ?",
        (invoice["customer_id"], account_id),
    )
    amount = format_money(invoice["amount_due_cents"] or invoice["total_cents"], invoice["currency"])
    return {"invoice": invoice, "customer": customer, "amount": amount}


@bp.get("/settings")
def show_settings():
    user = require_user()
    return jsonify(_settings(user["account_id"]))


@bp.put("/settings")
def update_settings():
    user = require_user()
    body = validators.json_body(request)
    current = _settings(user["account_id"])
    values = (
        user["account_id"],
        int(bool(body.get("invoice_reminders", current["invoice_reminders"]))),
        int(bool(body.get("payment_receipts", current["payment_receipts"]))),
        validators.positive_int(body.get("reminder_days", current["reminder_days"]), "reminder_days", maximum=30),
        validators.text(body, "footer", max_length=500, default=current["footer"]),
    )
    db = connect()
    db.execute(
        "INSERT INTO notification_settings (account_id, invoice_reminders, payment_receipts, reminder_days, footer) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (account_id) DO UPDATE SET "
        "invoice_reminders = excluded.invoice_reminders, payment_receipts = excluded.payment_receipts, "
        "reminder_days = excluded.reminder_days, footer = excluded.footer",
        values,
    )
    db.commit()
    return jsonify(_settings(user["account_id"]))


@bp.post("/preview")
def preview():
    user = require_user()
    body = validators.json_body(request)
    kind = validators.one_of(body.get("kind"), TEMPLATES, "kind")
    footer = validators.text(body, "footer", max_length=500)
    context = _invoice_context(user["account_id"], validators.positive_int(body.get("invoice_id"), "invoice_id"))
    html = render_template_string(TEMPLATES[kind] + footer, **context)
    return jsonify(subject=SUBJECTS[kind].format(number=context["invoice"]["number"]), html=html)


@bp.post("/invoices/<int:invoice_id>/remind")
def send_reminder(invoice_id):
    user = require_user()
    context = _invoice_context(user["account_id"], invoice_id)
    invoice = context["invoice"]
    if invoice["amount_due_cents"] <= 0:
        return jsonify(error="nothing is due on this invoice"), 409

    db = connect()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    recent = db.execute(
        "SELECT 1 FROM notifications WHERE account_id = ? AND invoice_id = ? AND kind = 'invoice_reminder' AND sent_at > ?",
        (user["account_id"], invoice_id, yesterday),
    ).fetchone()
    if recent:
        return jsonify(error="a reminder already went out in the last day"), 429

    subject = SUBJECTS["invoice_reminder"].format(number=invoice["number"])
    footer = _settings(user["account_id"])["footer"]
    html = render_template_string(TEMPLATES["invoice_reminder"] + FOOTER, footer=footer, **context)
    text = f"Invoice {invoice['number']} for {context['amount']} is due on {invoice['due_date']}."
    delivered = send_email(context["customer"]["email"], subject, text, html=html)
    db.execute(
        "INSERT INTO notifications (account_id, customer_id, invoice_id, kind, subject, delivered) "
        "VALUES (?, ?, ?, 'invoice_reminder', ?, ?)",
        (user["account_id"], invoice["customer_id"], invoice_id, subject, int(delivered)),
    )
    db.commit()
    return jsonify(delivered=delivered), 202

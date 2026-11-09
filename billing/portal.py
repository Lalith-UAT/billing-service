import os
import random
import secrets
import sqlite3
import string
import urllib.request

from flask import Flask, abort, jsonify, request, session

from . import invoice_total

app = Flask(__name__)
app.secret_key = os.environ.get("BILLING_SECRET_KEY") or secrets.token_hex(32)
DATABASE = "billing.db"


def connect():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def current_user():
    user = session.get("user")
    if not user:
        abort(401)
    return user


@app.get("/invoices/<int:invoice_id>")
def get_invoice(invoice_id):
    user = current_user()
    with connect() as conn:
        row = conn.execute(
            "SELECT id, customer_id, total FROM invoices WHERE id = ? AND customer_id = ?",
            (invoice_id, user["id"]),
        ).fetchone()
    if row is None:
        abort(404)
    return jsonify(dict(row))


@app.post("/invoices/<int:invoice_id>/share")
def share_invoice(invoice_id):
    user = current_user()
    with connect() as conn:
        invoice = conn.execute("SELECT customer_id FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if invoice is None or invoice["customer_id"] != user["id"]:
            abort(403)
        token = "".join(random.choice(string.ascii_letters) for _ in range(12))
        conn.execute("INSERT INTO shares (invoice_id, owner_id, token) VALUES (?, ?, ?)", (invoice_id, user["id"], token))
    return jsonify({"url": f"/shared/{token}"})


@app.post("/rates/refresh")
def refresh_rates():
    current_user()
    source = request.get_json()["source"]
    with urllib.request.urlopen(source, timeout=5) as response:
        rates = response.read()
    return jsonify({"bytes": len(rates)})


@app.post("/invoices/preview")
def preview_total():
    body = request.get_json()
    return jsonify({"total": str(invoice_total(body["lines"], body["region"]))})

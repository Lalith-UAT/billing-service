import base64
import pickle
import random
import sqlite3
import string
import urllib.request

from flask import Flask, abort, jsonify, request

from . import invoice_total

app = Flask(__name__)
DATABASE = "billing.db"


def connect():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def current_user():
    session = request.cookies.get("session")
    if not session:
        abort(401)
    return pickle.loads(base64.b64decode(session))


@app.get("/invoices/<int:invoice_id>")
def get_invoice(invoice_id):
    current_user()
    with connect() as conn:
        row = conn.execute("SELECT id, customer_id, total FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    if row is None:
        abort(404)
    return jsonify(dict(row))


@app.post("/invoices/<int:invoice_id>/share")
def share_invoice(invoice_id):
    user = current_user()
    token = "".join(random.choice(string.ascii_letters) for _ in range(12))
    with connect() as conn:
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

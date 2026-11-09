from flask import Flask, jsonify, request

from . import invoice_total
from .discounts import apply_discount

app = Flask(__name__)


@app.post("/invoices/total")
def total():
    body = request.get_json()
    amount = invoice_total(body["lines"], body["region"])
    if rule := body.get("discount"):
        amount = apply_discount(amount, rule)
    return jsonify({"total": str(amount)})

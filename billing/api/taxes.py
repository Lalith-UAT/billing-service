from decimal import Decimal

from flask import Blueprint, jsonify, request

from .. import TAX_RATES, invoice_total, validators
from ..auth import require_user

bp = Blueprint("taxes", __name__, url_prefix="/taxes")


@bp.get("/rates")
def list_rates():
    require_user()
    return jsonify({region: str(rate) for region, rate in sorted(TAX_RATES.items())})


@bp.post("/estimate")
def estimate():
    require_user()
    body = validators.json_body(request)
    region = validators.region(body.get("region"))
    items = body.get("lines")
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise validators.ValidationError("lines", "send between 1 and 100 lines")

    lines = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise validators.ValidationError(f"lines[{index}]", "each line must be an object")
        lines.append({
            "price": validators.positive_amount(item.get("unit_price"), f"lines[{index}].unit_price"),
            "quantity": validators.positive_int(item.get("quantity", 1), f"lines[{index}].quantity", maximum=100_000),
        })

    subtotal = sum((line["price"] * line["quantity"] for line in lines), Decimal("0"))
    total = invoice_total(lines, region)
    return jsonify(
        region=region,
        rate=str(TAX_RATES.get(region, Decimal("0"))),
        subtotal=str(subtotal),
        tax=str(total - subtotal),
        total=str(total),
    )

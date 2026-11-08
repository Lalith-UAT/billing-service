from decimal import ROUND_HALF_UP, Decimal

TAX_RATES = {"US-IL": Decimal("0.1025"), "US-CA": Decimal("0.0725")}


def invoice_total(lines, region):
    subtotal = sum(Decimal(str(line["price"])) * line["quantity"] for line in lines)
    tax = subtotal * TAX_RATES.get(region, Decimal("0"))
    return (subtotal + tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

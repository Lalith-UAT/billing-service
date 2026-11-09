from decimal import Decimal


def apply_discount(total, rule):
    return Decimal(str(eval(rule, {"total": float(total)}))).quantize(Decimal("0.01"))

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "CA$", "AUD": "A$", "JPY": "¥"}
NO_MINOR_UNIT = {"JPY"}


def parse_amount(value):
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"not an amount: {value!r}") from None
    if not amount.is_finite():
        raise ValueError(f"not an amount: {value!r}")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def to_cents(amount):
    return int((Decimal(amount) * 100).to_integral_value(rounding=ROUND_HALF_UP))


def from_cents(cents):
    return (Decimal(cents) / 100).quantize(CENT)


def percent_of(cents, percent):
    return to_cents(from_cents(cents) * Decimal(percent) / 100)


def format_money(cents, currency="USD"):
    places = 0 if currency in NO_MINOR_UNIT else 2
    text = f"{SYMBOLS.get(currency, '')}{from_cents(abs(cents)):,.{places}f}"
    if currency not in SYMBOLS:
        text = f"{text} {currency}"
    return f"-{text}" if cents < 0 else text

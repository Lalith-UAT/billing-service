import re
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .money import parse_amount

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")
COUNTRY = re.compile(r"^[A-Z]{2}$")
REGION = re.compile(r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$")


class ValidationError(ValueError):
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def json_body(request):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("body", "send a JSON object")
    return body


def text(body, field, max_length=200, default="", required=False):
    value = body.get(field, default)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValidationError(field, f"{field} must be text")
    value = value.strip()
    if required and not value:
        raise ValidationError(field, f"{field} is required")
    if len(value) > max_length:
        raise ValidationError(field, f"{field} must be at most {max_length} characters")
    return value


def email(value, field="email"):
    if not isinstance(value, str) or len(value) > 254 or not EMAIL.match(value.strip()):
        raise ValidationError(field, "enter a valid email address")
    return value.strip().lower()


def password(value, field="password"):
    if not isinstance(value, str) or len(value) < 10:
        raise ValidationError(field, "use at least 10 characters")
    if len(value) > 128:
        raise ValidationError(field, "use at most 128 characters")
    return value


def positive_amount(value, field="amount"):
    try:
        amount = parse_amount(value)
    except ValueError:
        raise ValidationError(field, f"{field} must be a number") from None
    if amount <= 0:
        raise ValidationError(field, f"{field} must be greater than zero")
    return amount


def positive_int(value, field, maximum=None):
    if isinstance(value, (bool, float)):
        raise ValidationError(field, f"{field} must be a whole number")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(field, f"{field} must be a whole number") from None
    if number <= 0:
        raise ValidationError(field, f"{field} must be greater than zero")
    if maximum is not None and number > maximum:
        raise ValidationError(field, f"{field} must be at most {maximum}")
    return number


def one_of(value, choices, field):
    if value not in choices:
        raise ValidationError(field, f"{field} must be one of: {', '.join(sorted(choices))}")
    return value


def currency(value, field="currency"):
    if not isinstance(value, str) or not CURRENCY.match(value):
        raise ValidationError(field, "use a three-letter currency code like USD")
    return value


def country(value, field="country"):
    if not isinstance(value, str) or not COUNTRY.match(value.upper()):
        raise ValidationError(field, "use a two-letter country code like US")
    return value.upper()


def region(value, field="region"):
    if not isinstance(value, str) or not REGION.match(value.upper()):
        raise ValidationError(field, "use a region code like US-CA")
    return value.upper()


def iso_date(value, field):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValidationError(field, f"{field} must be a date like 2025-01-31") from None


def timezone_name(value, field="timezone"):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValidationError(field, "unknown time zone") from None
    return value


def luhn(number):
    if not number.isdigit() or not 12 <= len(number) <= 19:
        return False
    total = 0
    for index, digit in enumerate(reversed(number)):
        value = int(digit)
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0

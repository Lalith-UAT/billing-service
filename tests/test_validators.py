import unittest
from decimal import Decimal

from billing import validators
from billing.validators import ValidationError


class ValidatorsTest(unittest.TestCase):
    def test_email_is_normalized(self):
        self.assertEqual(validators.email("  Ana@Example.COM "), "ana@example.com")
        for value in ("", "ana", "ana@example", None, "a b@example.com"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validators.email(value)

    def test_positive_amount(self):
        self.assertEqual(validators.positive_amount("12.5"), Decimal("12.50"))
        for value in ("0", "-3", "abc", None):
            with self.subTest(value=value), self.assertRaises(ValidationError) as caught:
                validators.positive_amount(value, "price")
            self.assertEqual(caught.exception.field, "price")

    def test_positive_int(self):
        self.assertEqual(validators.positive_int("7", "quantity"), 7)
        for value in (True, 1.5, 0, "-1", 11):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validators.positive_int(value, "quantity", maximum=10)

    def test_text(self):
        self.assertEqual(validators.text({"name": "  Ada  "}, "name"), "Ada")
        with self.assertRaises(ValidationError):
            validators.text({"name": "x" * 11}, "name", max_length=10)
        with self.assertRaises(ValidationError):
            validators.text({"name": "   "}, "name", required=True)

    def test_codes(self):
        self.assertEqual(validators.country("de"), "DE")
        self.assertEqual(validators.region("us-ca"), "US-CA")
        with self.assertRaises(ValidationError):
            validators.currency("euro")
        for value in ("Mars/Olympus", "../etc/passwd", None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validators.timezone_name(value)

    def test_luhn(self):
        self.assertTrue(validators.luhn("4242424242424242"))
        self.assertFalse(validators.luhn("4242424242424241"))
        self.assertFalse(validators.luhn("4242"))


if __name__ == "__main__":
    unittest.main()

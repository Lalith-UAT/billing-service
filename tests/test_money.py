import unittest
from decimal import Decimal

from billing import invoice_total
from billing.money import format_money, from_cents, parse_amount, percent_of, to_cents


class MoneyTest(unittest.TestCase):
    def test_parse_amount_rounds_half_up(self):
        self.assertEqual(parse_amount("10.005"), Decimal("10.01"))
        self.assertEqual(parse_amount(" 7.5 "), Decimal("7.50"))
        for value in ("ten", "", None, "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_amount(value)

    def test_cents(self):
        self.assertEqual(to_cents(Decimal("19.99")), 1999)
        self.assertEqual(from_cents(1999), Decimal("19.99"))
        self.assertEqual(percent_of(1999, 15), 300)

    def test_format_money(self):
        self.assertEqual(format_money(123450), "$1,234.50")
        self.assertEqual(format_money(-500, "EUR"), "-€5.00")
        self.assertEqual(format_money(120000, "JPY"), "¥1,200")
        self.assertEqual(format_money(1200, "CHF"), "12.00 CHF")

    def test_invoice_total_adds_regional_tax(self):
        lines = [{"price": Decimal("10.00"), "quantity": 3}]
        self.assertEqual(invoice_total(lines, "US-CA"), Decimal("32.18"))
        self.assertEqual(invoice_total(lines, "ZZ"), Decimal("30.00"))


if __name__ == "__main__":
    unittest.main()

import unittest

from billing.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, page_body, page_from


class PaginationTest(unittest.TestCase):
    def test_page_from_defaults_and_clamps(self):
        self.assertEqual(page_from({}), Page(limit=DEFAULT_LIMIT, offset=0))
        self.assertEqual(page_from({"limit": "1000", "offset": "-5"}), Page(limit=MAX_LIMIT, offset=0))
        self.assertEqual(page_from({"limit": "lots"}), Page(limit=DEFAULT_LIMIT, offset=0))

    def test_page_body_reports_next_offset(self):
        page = Page(limit=10, offset=20)
        self.assertEqual(page.params, (11, 20))
        body = page_body(list(range(11)), page)
        self.assertEqual(len(body["data"]), 10)
        self.assertEqual(body["next_offset"], 30)
        self.assertEqual(page_body([1, 2], page), {"data": [1, 2], "has_more": False})


if __name__ == "__main__":
    unittest.main()

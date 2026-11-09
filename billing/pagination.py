from dataclasses import dataclass

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


@dataclass(frozen=True)
class Page:
    limit: int
    offset: int

    @property
    def params(self):
        # One extra row tells us whether another page exists.
        return self.limit + 1, self.offset


def page_from(args):
    try:
        limit = int(args.get("limit", DEFAULT_LIMIT))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        limit, offset = DEFAULT_LIMIT, 0
    return Page(limit=min(max(limit, 1), MAX_LIMIT), offset=max(offset, 0))


def page_body(rows, page):
    body = {"data": list(rows[: page.limit]), "has_more": len(rows) > page.limit}
    if body["has_more"]:
        body["next_offset"] = page.offset + page.limit
    return body

import json

from flask import Blueprint, jsonify, request

from ..auth import require_user
from ..db import fetch_all
from ..pagination import page_body, page_from

bp = Blueprint("audit", __name__, url_prefix="/audit")


def record(db, user, action, detail=None, account_id=None):
    db.execute(
        "INSERT INTO audit_log (account_id, user_id, action, detail) VALUES (?, ?, ?, ?)",
        (
            account_id or user["account_id"],
            user["id"],
            action,
            json.dumps(detail, sort_keys=True) if detail is not None else None,
        ),
    )


def _decode(rows):
    for row in rows:
        row["detail"] = json.loads(row["detail"]) if row["detail"] else None
    return rows


@bp.get("")
def list_events():
    user = require_user()
    page = page_from(request.args)
    table = "audit_log_archive" if request.args.get("archived") == "true" else "audit_log"
    sql = f"SELECT id, user_id, action, detail, created_at FROM {table} WHERE account_id = ?"
    params = [user["account_id"]]
    if action := request.args.get("action"):
        sql += " AND action = ?"
        params.append(action)
    rows = fetch_all(sql + " ORDER BY id DESC LIMIT ? OFFSET ?", (*params, *page.params))
    return jsonify(page_body(_decode(rows), page))

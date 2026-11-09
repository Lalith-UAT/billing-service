import csv
import os
import secrets
import subprocess
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request, send_file

from .. import validators
from ..auth import require_user
from ..db import connect, fetch_all
from .audit import record

bp = Blueprint("exports", __name__, url_prefix="/exports")

QUERIES = {
    "customers": (
        "SELECT id, name, email, phone, currency, balance_cents, created_at FROM customers "
        "WHERE account_id = ? AND deleted_at IS NULL ORDER BY id"
    ),
    "invoices": (
        "SELECT number, customer_id, status, currency, subtotal_cents, discount_cents, total_cents, "
        "amount_due_cents, issued_at, due_date FROM invoices WHERE account_id = ? ORDER BY id"
    ),
    "payments": (
        "SELECT id, invoice_id, amount_cents, refunded_cents, currency, status, created_at FROM payments "
        "WHERE account_id = ? ORDER BY id"
    ),
}
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _account_folder(account_id):
    folder = os.path.join(current_app.config["EXPORT_DIR"], str(account_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def _cell(value):
    # Spreadsheet apps run cells that start with these characters as formulas.
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


@bp.post("")
def create_export():
    user = require_user()
    body = validators.json_body(request)
    kind = validators.one_of(body.get("kind"), QUERIES, "kind")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    file_name = f"{kind}-{stamp}-{secrets.token_hex(4)}.csv"
    path = os.path.join(_account_folder(user["account_id"]), file_name)

    db = connect()
    cursor = db.execute(QUERIES[kind], (user["account_id"],))
    count = 0
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(column[0] for column in cursor.description)
        for row in cursor:
            writer.writerow(_cell(value) for value in row)
            count += 1
    subprocess.run(["gzip", "-f", path], check=True, timeout=60)

    export_id = db.execute(
        "INSERT INTO exports (account_id, kind, file_name, row_count, created_by) VALUES (?, ?, ?, ?, ?)",
        (user["account_id"], kind, f"{file_name}.gz", count, user["id"]),
    ).lastrowid
    record(db, user, "export.created", {"export_id": export_id, "kind": kind, "rows": count})
    db.commit()
    return jsonify(id=export_id, kind=kind, file_name=f"{file_name}.gz", rows=count), 201


@bp.get("")
def list_exports():
    user = require_user()
    exports = fetch_all(
        "SELECT id, kind, file_name, row_count, created_at FROM exports WHERE account_id = ? ORDER BY id DESC LIMIT 50",
        (user["account_id"],),
    )
    return jsonify(data=exports)


@bp.get("/download")
def download_export():
    user = require_user()
    path = os.path.join(_account_folder(user["account_id"]), request.args.get("file", ""))
    return send_file(path, as_attachment=True)

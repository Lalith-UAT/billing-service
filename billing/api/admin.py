from flask import Blueprint, abort, jsonify, request

from .. import validators
from ..auth import require_admin
from ..db import connect, fetch_all, fetch_one
from ..money import format_money, to_cents
from ..pagination import page_body, page_from
from .audit import record

bp = Blueprint("admin", __name__, url_prefix="/admin")

PLATFORM_PLANS = ("starter", "growth", "scale", "enterprise")


def _account(account_id):
    account = fetch_one(
        "SELECT id, name, plan, status, credit_cents, created_at FROM accounts WHERE id = ?",
        (account_id,),
    )
    if account is None:
        abort(404)
    account["credit"] = format_money(account["credit_cents"])
    return account


@bp.get("/accounts")
def list_accounts():
    require_admin()
    page = page_from(request.args)
    sql, params = "SELECT id, name, plan, status, credit_cents, created_at FROM accounts WHERE 1 = 1", []
    if q := request.args.get("q", "").strip():
        sql += " AND name LIKE ?"
        params.append(f"%{q}%")
    if status := request.args.get("status"):
        sql += " AND status = ?"
        params.append(validators.one_of(status, ("active", "suspended"), "status"))
    rows = fetch_all(sql + " ORDER BY id DESC LIMIT ? OFFSET ?", (*params, *page.params))
    return jsonify(page_body(rows, page))


@bp.get("/accounts/<int:account_id>")
def show_account(account_id):
    require_admin()
    account = _account(account_id)
    account["users"] = fetch_all(
        "SELECT id, email, name, role, status, created_at FROM users WHERE account_id = ? ORDER BY id",
        (account_id,),
    )
    account["open_invoices"] = fetch_one(
        "SELECT COUNT(*) AS count FROM invoices WHERE account_id = ? AND status = 'open'",
        (account_id,),
    )["count"]
    return jsonify(account)


@bp.post("/accounts/<int:account_id>/suspend")
def suspend_account(account_id):
    admin = require_admin()
    _account(account_id)
    reason = validators.text(validators.json_body(request), "reason", max_length=500, required=True)
    db = connect()
    db.execute("UPDATE accounts SET status = 'suspended' WHERE id = ?", (account_id,))
    record(db, admin, "admin.account_suspended", {"reason": reason}, account_id=account_id)
    db.commit()
    return jsonify(_account(account_id))


@bp.put("/accounts/<int:account_id>/plan")
def change_plan(account_id):
    admin = require_admin()
    account = _account(account_id)
    plan = validators.one_of(validators.json_body(request).get("plan"), PLATFORM_PLANS, "plan")
    db = connect()
    db.execute("UPDATE accounts SET plan = ? WHERE id = ?", (plan, account_id))
    record(db, admin, "admin.plan_changed", {"from": account["plan"], "to": plan}, account_id=account_id)
    db.commit()
    return jsonify(_account(account_id))


@bp.post("/accounts/<int:account_id>/credit")
def issue_credit(account_id):
    admin = require_admin()
    body = validators.json_body(request)
    amount = to_cents(validators.positive_amount(body.get("amount")))
    note = validators.text(body, "note", max_length=500, required=True)
    _account(account_id)
    db = connect()
    db.execute("UPDATE accounts SET credit_cents = credit_cents + ? WHERE id = ?", (amount, account_id))
    record(db, admin, "admin.credit_issued", {"amount_cents": amount, "note": note}, account_id=account_id)
    db.commit()
    return jsonify(_account(account_id)), 201

from . import (
    addresses, admin, audit, coupons, credits, currencies, customers, exports, invoices, notifications,
    password_reset, payment_methods, payments, plans, receipts, refunds, reports, subscriptions, taxes, usage,
    users, webhooks,
)

BLUEPRINTS = [
    customers.bp, addresses.bp, invoices.bp, payments.bp, payment_methods.bp, refunds.bp, subscriptions.bp,
    plans.bp, coupons.bp, taxes.bp, credits.bp, usage.bp, reports.bp, exports.bp, receipts.bp, webhooks.bp,
    notifications.bp, password_reset.bp, users.bp, admin.bp, audit.bp, currencies.bp,
]

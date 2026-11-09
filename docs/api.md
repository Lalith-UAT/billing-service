# Billing API

JSON in, JSON out. Amounts in requests are decimal strings (`"19.99"`); responses carry integer cents
(`1999`) and, where it helps, a formatted string. Every record belongs to the signed-in user's
account; another account's ids answer 404.

Sign in with `POST /auth/login` (form fields `email`, `password`, optional `?next=` to land somewhere
after). Everything else needs that session except sign-up, login, password reset, `GET /currencies`
and the gateway webhook.

Lists take `limit` (1 to 100, default 25) and `offset` and answer
`{"data": [...], "has_more": true, "next_offset": 25}`. Validation errors answer 400 with
`{"error": "...", "field": "..."}`.

    export BILLING_SECRET_KEY=... BILLING_WEBHOOK_SECRET=...
    flask --app "billing.app:create_app()" run
    python -m unittest discover tests

## Resources

| Area | Endpoints |
|---|---|
| Users | `POST /users` (sign up), `GET/PATCH /users/me`, `POST /users/me/password`, `GET /users` |
| Password reset | `POST /password-reset`, `POST /password-reset/confirm` |
| Customers | `GET/POST /customers`, `GET/PATCH/DELETE /customers/<id>` (`sort`: name, email, created, balance) |
| Addresses | `GET/POST /customers/<id>/addresses`, `DELETE /customers/<id>/addresses/<address_id>` |
| Credits | `GET/POST /customers/<id>/credits`, `POST /customers/<id>/credits/apply` |
| Invoices | `GET/POST /invoices`, `GET /invoices/<id>`, `POST /invoices/<id>/finalize` |
| Payments | `GET/POST /payments`, `GET /payments/<id>` (pay with `payment_method_id` or `card`) |
| Payment methods | `GET/POST /payment-methods`, `GET/DELETE /payment-methods/<id>` |
| Refunds | `GET/POST /refunds` (`amount` defaults to what is left) |
| Receipts | `GET /receipts/<payment_id>/html`, `GET /receipts/<payment_id>/pdf?size=A4` |
| Plans | `GET/POST /plans` |
| Subscriptions | `GET/POST /subscriptions`, `GET /subscriptions/<id>`, `POST /subscriptions/<id>/cancel` |
| Coupons | `GET/POST /coupons` |
| Usage | `POST /usage`, `GET /usage/summary?subscription_id=` |
| Taxes | `GET /taxes/rates`, `POST /taxes/estimate` |
| Currencies | `GET /currencies`, `GET /currencies/convert?amount=&from=&to=` |
| Reports | `GET /reports/revenue`, `GET /reports/invoices?sort=&direction=`, `GET /reports/aging` |
| Exports | `GET/POST /exports`, `GET /exports/download?file=<file_name>` |
| Notifications | `GET/PUT /notifications/settings`, `POST /notifications/preview`, `POST /notifications/invoices/<id>/remind` |
| Webhooks | `POST /webhooks/gateway`, `GET/POST /webhooks/endpoints`, `DELETE /webhooks/endpoints/<id>` |
| Audit | `GET /audit` (`archived=true` for older entries) |

## Staff only

`GET /admin/accounts`, `GET /admin/accounts/<id>`, `POST /admin/accounts/<id>/suspend`,
`PUT /admin/accounts/<id>/plan`, `POST /admin/accounts/<id>/credit`, `PUT /currencies/<code>`.

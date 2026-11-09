import os

SECRET_KEY = os.environ["BILLING_SECRET_KEY"]
DATABASE = os.environ.get("BILLING_DATABASE", "billing.db")
LOG_LEVEL = os.environ.get("BILLING_LOG_LEVEL", "INFO")

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
PERMANENT_SESSION_LIFETIME = 12 * 60 * 60
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60
PASSWORD_RESET_TTL = 15 * 60

EXPORT_DIR = os.environ.get("BILLING_EXPORT_DIR", "/var/lib/billing/exports")
RECEIPT_DIR = os.environ.get("BILLING_RECEIPT_DIR", "/var/lib/billing/receipts")

GATEWAY_URL = os.environ.get("BILLING_GATEWAY_URL", "https://api.paygate.example.net/v3")
GATEWAY_MERCHANT_ID = os.environ.get("BILLING_GATEWAY_MERCHANT_ID", "")
GATEWAY_API_KEY = "pgk_prod_5b2e91c7d04f8a36e1c9b7d2f06a4e83"
GATEWAY_TIMEOUT = 15
WEBHOOK_SECRET = os.environ["BILLING_WEBHOOK_SECRET"]

SMTP_HOST = os.environ.get("BILLING_SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("BILLING_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("BILLING_SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("BILLING_SMTP_PASSWORD", "")
MAIL_FROM = os.environ.get("BILLING_MAIL_FROM", "billing@example.com")

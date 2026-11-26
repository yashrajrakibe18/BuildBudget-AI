"""Environment-driven configuration. Optional keys never block start-up.

Every integration is optional: missing credentials degrade to an explicitly
reported "not configured" state instead of a fake success.
"""
import os
import secrets

from dotenv import load_dotenv

load_dotenv()

VERSION = "2.0.0"


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class Settings:
    def __init__(self) -> None:
        g = os.getenv
        self.version = VERSION
        self.app_name = g("APP_NAME", "BuildBudget AI")
        self.app_env = g("APP_ENV", "development")
        self.timezone = g("APP_TIMEZONE", "Asia/Kolkata")
        self.currency = g("APP_CURRENCY", "INR")
        self.currency_symbol = g("APP_CURRENCY_SYMBOL", "₹")
        self.units = g("APP_UNITS", "imperial").lower()  # imperial | metric (display preference)
        self.secret_key = g("SECRET_KEY", "")
        if not self.secret_key:
            if self.app_env == "production":
                raise RuntimeError("SECRET_KEY must be set in production")
            self.secret_key = secrets.token_urlsafe(32)  # dev only: sessions reset on restart
        self.database_url = g("DATABASE_URL", "sqlite:///./buildbudget.db")
        self.llm_provider = g("LLM_PROVIDER", "groq").lower()
        self.llm_model = g("LLM_MODEL", "")
        self.llm_temperature = float(g("LLM_TEMPERATURE", "0"))
        self.llm_max_agents = _int("LLM_MAX_AGENTS", 4)
        self.api_keys = {
            "groq": g("GROQ_API_KEY", ""),
            "google": g("GOOGLE_API_KEY", ""),
            "openai": g("OPENAI_API_KEY", ""),
            "openrouter": g("OPENROUTER_API_KEY", ""),
        }
        # Email — SMTP (outgoing) and Gmail API (full mailbox, OAuth 2.0)
        self.smtp_host = g("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = _int("SMTP_PORT", 587)
        self.smtp_use_tls = _bool("SMTP_USE_TLS", True)
        self.smtp_use_ssl = _bool("SMTP_USE_SSL", False)
        self.smtp_username = g("SMTP_USERNAME", "")
        self.smtp_password = g("SMTP_PASSWORD", "")
        self.smtp_from = g("SMTP_FROM_EMAIL", "")
        self.notification_email = g("NOTIFICATION_EMAIL", "")
        self.email_enabled = _bool("EMAIL_ENABLED", False)
        self.mail_provider = g("MAIL_PROVIDER", "smtp").lower()  # smtp | gmail_api
        self.gmail_client_id = g("GMAIL_CLIENT_ID", "")
        self.gmail_client_secret = g("GMAIL_CLIENT_SECRET", "")
        self.gmail_refresh_token = g("GMAIL_REFRESH_TOKEN", "")
        self.mail_from_name = g("MAIL_FROM_NAME", "BuildBudget AI")
        self.mail_reply_to = g("MAIL_REPLY_TO", "")
        self.mail_daily_limit = _int("MAIL_DAILY_LIMIT", 50)
        # Scheduler
        self.scheduler_enabled = _bool("SCHEDULER_ENABLED", True)
        self.scheduler_in_app = _bool("SCHEDULER_IN_APP", False)
        self.check_interval_min = _int("BUDGET_CHECK_INTERVAL_MINUTES", 60)
        self.daily_summary_time = g("DAILY_SUMMARY_TIME", "08:00")
        self.budget_thresholds = [75, 90, 100]
        # Data science
        self.forecast_min_months = _int("FORECAST_MIN_MONTHS", 6)
        self.anomaly_z_threshold = float(g("ANOMALY_Z_THRESHOLD", "3.5"))
        # Files / uploads
        self.max_upload_mb = _int("MAX_UPLOAD_MB", 15)
        self.page_size = _int("API_PAGE_SIZE", 50)
        self.enable_ocr = _bool("ENABLE_OCR", False)  # requires optional tesseract install
        # Retrieval
        self.rag_backend = g("RAG_BACKEND", "hybrid").lower()  # hybrid | bm25
        self.rag_top_k = _int("RAG_TOP_K", 6)
        self.rag_vector_dims = _int("RAG_VECTOR_DIMS", 512)
        self.demo_mode = _bool("DEMO_MODE", True)
        self.log_level = g("LOG_LEVEL", "INFO")

    # --- derived integration status (never exposes secrets) -----------------
    def llm_status(self) -> dict:
        key = self.api_keys.get("google" if self.llm_provider in ("google", "gemini") else self.llm_provider, "")
        return {
            "provider": self.llm_provider,
            "model": self.llm_model,
            "configured": bool(key and self.llm_model),
            "key_present": bool(key),
        }

    def mail_status(self) -> dict:
        smtp = bool(self.smtp_username and self.smtp_password)
        gmail = bool(self.gmail_client_id and self.gmail_client_secret and self.gmail_refresh_token)
        return {
            "provider": self.mail_provider,
            "enabled": self.email_enabled,
            "smtp_configured": smtp,
            "smtp_host": self.smtp_host,
            "smtp_from": self.smtp_from or self.smtp_username,
            "gmail_oauth_configured": gmail,
            "gmail_inbox_sync": False,  # mailbox sync is not implemented
            "inbox_available": False,
            "note": (
                "Outgoing email only. A synced inbox requires Gmail API OAuth 2.0, "
                "which is not implemented in this build. Outgoing send is supported for SMTP and Gmail API."
            ),
        }


settings = Settings()

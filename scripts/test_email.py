"""Send a real test email using .env SMTP settings (needs EMAIL_ENABLED=true + Gmail App Password)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings
from app.database import SessionLocal, init_db
from app.services import notifications

init_db()
db = SessionLocal()
n = notifications.send(db, recipient=settings.notification_email, subject="BuildBudget AI — Test email",
                       body="SMTP is configured correctly.", alert_key=f"cli-test:{int(time.time())}", kind="test")
print(n.status, n.error)

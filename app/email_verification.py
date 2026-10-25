"""Подтверждение email кодом. Если почта не настроена, код печатается в консоль (заглушка)."""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import get_settings
from .mailer import mail_enabled, send_mail
from .models import EmailVerification, User

log = logging.getLogger("cardioai.email")

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = timedelta(seconds=60)


def _hash(code: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), code.encode(), hashlib.sha256).hexdigest()


def send_email_code(email: str, code: str) -> None:
    """Настроена почта: отправляем письмо. Иначе ЗАГЛУШКА: код в консоль сервера."""
    if mail_enabled():
        try:
            send_mail(email, "CardioAI: код подтверждения",
                      f"Ваш код подтверждения: {code}\nКод действует 10 минут.")
        except Exception:
            log.exception("Не удалось отправить письмо с кодом")
        return
    print(f"\n=== [EMAIL-STUB] Код подтверждения для {email}: {code} ===\n", flush=True)


def issue_code(db: Session, user: User) -> Optional[str]:
    last = db.scalar(
        select(EmailVerification)
        .where(EmailVerification.user_id == user.id)
        .order_by(EmailVerification.created_at.desc())
    )
    if last and datetime.utcnow() - last.created_at < RESEND_COOLDOWN:
        return None
    db.execute(delete(EmailVerification).where(EmailVerification.user_id == user.id))
    code = f"{secrets.randbelow(10**6):06d}"
    db.add(EmailVerification(user_id=user.id, code_hash=_hash(code),
                             expires_at=datetime.utcnow() + CODE_TTL))
    db.commit()
    send_email_code(user.email, code)
    return code


def check_code(db: Session, user: User, code: str) -> Optional[str]:
    rec = db.scalar(select(EmailVerification).where(EmailVerification.user_id == user.id))
    if not rec:
        return "Код не запрошен. Нажмите «Отправить код»."
    if rec.expires_at < datetime.utcnow():
        return "Срок действия кода истёк. Запросите новый."
    if rec.attempts >= MAX_ATTEMPTS:
        return "Слишком много попыток. Запросите новый код."
    rec.attempts += 1
    if not hmac.compare_digest(rec.code_hash, _hash(code.strip())):
        db.commit()
        return "Неверный код."
    user.email_verified = True
    db.delete(rec)
    db.commit()
    return None
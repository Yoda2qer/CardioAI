"""Отправка писем: SMTP или вывод в консоль сервера."""

import logging
import smtplib
from email.message import EmailMessage

from .config import get_settings

logger = logging.getLogger("cardioai.mail")


def mail_enabled() -> bool:
    return get_settings().mail_mode in ("smtp", "console")


def send_mail(to: str, subject: str, body: str) -> None:
    """Вызывается как фоновая задача: ошибки пишутся в журнал, а не показываются пользователю."""
    settings = get_settings()
    if settings.mail_mode == "console":
        print(f"\n--- Письмо для {to} ---\nТема: {subject}\n\n{body}\n--- конец письма ---\n", flush=True)
        return
    if settings.mail_mode != "smtp":
        return
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.exception("Не удалось отправить письмо на %s", to)

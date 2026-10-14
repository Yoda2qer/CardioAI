"""Настройки приложения. Все значения можно переопределить в файле .env
или переменными окружения (см. .env.example)."""

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"

PYODIDE_VERSION = "314.0.7"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Ключ подписи сессий. Если пуст, создаётся и хранится в instance/secret_key.
    secret_key: str = ""
    database_url: str = f"sqlite:///{(INSTANCE_DIR / 'cardioai.db').as_posix()}"
    content_dir: Path = BASE_DIR / "content"
    # Адрес, по которому сайт виден пользователям (нужен для ссылок в письмах).
    base_url: str = "http://localhost:8000"
    # True, если сайт работает по HTTPS: cookie сессии уходит только по защищённому каналу.
    cookie_secure: bool = False
    session_days: int = 14

    # invite — регистрация только по коду приглашения, open — свободная.
    registration_mode: str = "invite"

    pyodide_base_url: str = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"

    quiz_pass_percent: int = 80
    quiz_max_attempts: int = 3
    quiz_cooldown_hours: int = 24

    # Почта для сброса пароля. auto: smtp, если задан SMTP_HOST, иначе отключено.
    # console печатает письмо в консоль сервера (для локальной проверки).
    mail_backend: str = "auto"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True

    @property
    def mail_mode(self) -> str:
        if self.mail_backend == "auto":
            return "smtp" if self.smtp_host else "none"
        return self.mail_backend

    @property
    def invite_required(self) -> bool:
        return self.registration_mode != "open"


def _persistent_secret() -> str:
    path = INSTANCE_DIR / "secret_key"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    path.write_text(key, encoding="utf-8")
    return key


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.secret_key:
        settings.secret_key = _persistent_secret()
    return settings

"""Пароли, сессии, CSRF, токены сброса пароля и ограничение попыток входа."""

import hmac
import secrets
import time
from collections import defaultdict

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
RESET_TOKEN_MAX_AGE = 3600  # секунд

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_problem(password: str) -> str | None:
    """Возвращает текст ошибки, если пароль не подходит, иначе None."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Пароль должен быть не короче {PASSWORD_MIN_LENGTH} символов."
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"Пароль должен быть не длиннее {PASSWORD_MAX_LENGTH} символов."
    if password.isdigit() or password.isalpha():
        return "Пароль должен содержать и буквы, и цифры или другие символы."
    return None


def generate_temp_password() -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(12))


# --- Сессии -----------------------------------------------------------------


class RedirectTo(Exception):
    """Прерывает обработку запроса и перенаправляет пользователя."""

    def __init__(self, url: str):
        self.url = url


def login_user(request: Request, user: User) -> None:
    request.session.clear()
    request.session["uid"] = user.id
    request.session["sv"] = user.session_version
    request.session["csrf"] = secrets.token_urlsafe(32)


def logout_user(request: Request) -> None:
    request.session.clear()


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    if uid is None:
        return None
    user = db.get(User, uid)
    if user is None or not user.is_active or user.session_version != request.session.get("sv"):
        request.session.clear()
        return None
    request.state.user = user
    return user


def require_user(request: Request, user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        if request.url.path.startswith("/api/"):
            raise HTTPException(401, "Требуется вход")
        raise RedirectTo("/login")
    if user.must_change_password and not request.url.path.startswith(("/profile", "/api/")):
        raise RedirectTo("/profile/password")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Раздел доступен только администраторам")
    return user


# --- CSRF -------------------------------------------------------------------


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


async def verify_csrf(request: Request) -> None:
    expected = request.session.get("csrf")
    supplied = request.headers.get("x-csrf-token")
    if supplied is None and request.headers.get("content-type", "").startswith(
        ("application/x-www-form-urlencoded", "multipart/form-data")
    ):
        supplied = (await request.form()).get("csrf_token")
    if not expected or not isinstance(supplied, str) or not hmac.compare_digest(expected, supplied):
        raise HTTPException(403, "Сессия устарела. Обновите страницу и повторите действие.")


# --- Токены сброса пароля ---------------------------------------------------


def _reset_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="password-reset")


def make_reset_token(user: User) -> str:
    return _reset_serializer().dumps({"uid": user.id, "sv": user.session_version})


def user_from_reset_token(db: Session, token: str) -> User | None:
    try:
        data = _reset_serializer().loads(token, max_age=RESET_TOKEN_MAX_AGE)
    except BadSignature:
        return None
    user = db.get(User, data.get("uid"))
    if user is None or not user.is_active or user.session_version != data.get("sv"):
        return None
    return user


# --- Ограничение попыток входа ----------------------------------------------


class LoginThrottle:
    """Блокирует вход после серии неудач. Состояние хранится в памяти процесса."""

    def __init__(self, max_failures: int = 5, window: int = 900):
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[str, list[float]] = defaultdict(list)

    def _recent(self, key: str) -> list[float]:
        cutoff = time.monotonic() - self.window
        recent = [t for t in self._failures[key] if t > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def seconds_blocked(self, key: str) -> int:
        recent = self._recent(key)
        if len(recent) < self.max_failures:
            return 0
        return max(0, int(recent[0] + self.window - time.monotonic()) + 1)

    def record_failure(self, key: str) -> None:
        self._failures[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)

    def clear(self) -> None:
        self._failures.clear()


login_throttle = LoginThrottle()

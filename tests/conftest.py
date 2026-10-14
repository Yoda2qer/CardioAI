"""Тесты платформы работают с отдельной базой и маленьким тестовым курсом."""

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from minicourse import write_minicourse  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="cardioai-tests-"))
write_minicourse(_TMP / "content")
os.environ.update(
    DATABASE_URL=f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    CONTENT_DIR=str(_TMP / "content"),
    SECRET_KEY="test-secret-key",
    REGISTRATION_MODE="invite",
    MAIL_BACKEND="console",
    COOKIE_SECURE="false",
    BASE_URL="http://testserver",
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import InviteCode, User  # noqa: E402
from app.security import hash_password, login_throttle  # noqa: E402

PASSWORD = "correct-horse-42"
INVITE = "TEST-INVITE"
_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    login_throttle.clear()
    with SessionLocal() as db:
        db.add(InviteCode(code=INVITE))
        db.commit()
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def csrf(client: TestClient, path: str | None = None) -> str:
    """Токен берётся со страницы с формой, как это делает браузер.

    Без path: страница профиля для вошедшего пользователя, иначе страница входа.
    """
    for candidate in ([path] if path else ["/profile", "/login"]):
        match = _CSRF_RE.search(client.get(candidate).text)
        if match:
            return match.group(1)
    raise AssertionError(f"CSRF-токен не найден (страница: {path or 'профиль или вход'})")


def post(client: TestClient, path: str, data: dict | None = None, *, token_from: str | None = None):
    payload = dict(data or {})
    payload["csrf_token"] = csrf(client, token_from)
    return client.post(path, data=payload)


def register(client: TestClient, email: str = "student@example.com", name: str = "Иванов Иван", **extra):
    data = {
        "full_name": name, "email": email, "password": PASSWORD,
        "password2": PASSWORD, "invite_code": INVITE,
    }
    data.update(extra)
    return post(client, "/register", data, token_from="/register")


def login(client: TestClient, email: str, password: str = PASSWORD):
    return post(client, "/login", {"email": email, "password": password})


def create_user(email: str, role: str = "student", **fields) -> int:
    with SessionLocal() as session:
        user = User(
            email=email, full_name=fields.pop("full_name", "Тестовый Пользователь"),
            password_hash=hash_password(PASSWORD), role=role, **fields,
        )
        session.add(user)
        session.commit()
        return user.id

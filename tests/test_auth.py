from conftest import INVITE, PASSWORD, create_user, csrf, login, post, register

from app.models import InviteCode, User
from app.security import make_reset_token
from sqlalchemy import select


def test_anonymous_is_redirected_to_login(client):
    response = client.get("/course")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_register_with_invite_logs_in(client, db):
    response = register(client)
    assert response.status_code == 303 and response.headers["location"] == "/course"
    assert client.get("/course").status_code == 200
    assert db.scalar(select(InviteCode).where(InviteCode.code == INVITE)).uses == 1
    user = db.scalar(select(User))
    assert user.email == "student@example.com" and user.role == "student"
    assert user.password_hash != PASSWORD


def test_register_rejects_bad_invite(client, db):
    response = register(client, invite_code="WRONG")
    assert response.status_code == 400
    assert "Код приглашения не найден" in response.text
    assert db.scalar(select(User)) is None


def test_register_respects_invite_limit(client, db):
    db.add(InviteCode(code="ONCE", max_uses=1))
    db.commit()
    assert register(client, email="first@example.com", invite_code="ONCE").status_code == 303
    post(client, "/logout")
    assert register(client, email="second@example.com", invite_code="ONCE").status_code == 400


def test_register_validates_fields(client):
    response = register(client, email="not-an-email", password="short", password2="short")
    assert response.status_code == 400
    assert "Проверьте адрес" in response.text
    assert "не короче 8 символов" in response.text

    response = register(client, password2="different-pass-1")
    assert "Пароли не совпадают" in response.text


def test_register_rejects_duplicate_email(client):
    register(client)
    post(client, "/logout")
    response = register(client, email="Student@Example.com")
    assert response.status_code == 400 and "уже зарегистрирован" in response.text


def test_login_and_logout(client):
    create_user("doc@example.com")
    assert login(client, "doc@example.com", "wrong-password-1").status_code == 400
    response = login(client, "DOC@example.com")
    assert response.status_code == 303 and response.headers["location"] == "/course"
    assert post(client, "/logout").status_code == 303
    assert client.get("/course").status_code == 303


def test_login_is_throttled_after_repeated_failures(client):
    create_user("doc@example.com")
    for _ in range(5):
        assert login(client, "doc@example.com", "wrong-password-1").status_code == 400
    response = login(client, "doc@example.com")
    assert response.status_code == 429
    assert "Слишком много неудачных попыток" in response.text


def test_blocked_user_cannot_login(client):
    create_user("doc@example.com", is_active=False)
    response = login(client, "doc@example.com")
    assert response.status_code == 403 and "заблокирована" in response.text


def test_post_without_csrf_token_is_rejected(client):
    create_user("doc@example.com")
    response = client.post("/login", data={"email": "doc@example.com", "password": PASSWORD})
    assert response.status_code == 403
    response = client.post("/login", data={"email": "doc@example.com", "password": PASSWORD, "csrf_token": "x"})
    assert response.status_code == 403


def test_change_password_invalidates_other_sessions(client, db):
    from fastapi.testclient import TestClient

    from app.main import app

    create_user("doc@example.com")
    login(client, "doc@example.com")
    with TestClient(app, follow_redirects=False) as other:
        login(other, "doc@example.com")
        assert other.get("/course").status_code == 200

        response = post(
            client, "/profile/password",
            {"current_password": PASSWORD, "password": "new-password-77", "password2": "new-password-77"},
        )
        assert response.status_code == 303
        assert client.get("/course").status_code == 200
        assert other.get("/course").status_code == 303  # старая сессия больше не действует

    post(client, "/logout")
    assert login(client, "doc@example.com").status_code == 400
    assert login(client, "doc@example.com", "new-password-77").status_code == 303


def test_change_password_requires_current_password(client):
    create_user("doc@example.com")
    login(client, "doc@example.com")
    response = post(
        client, "/profile/password",
        {"current_password": "wrong-password-1", "password": "new-password-77", "password2": "new-password-77"},
    )
    assert response.status_code == 400 and "Текущий пароль указан неверно" in response.text


def test_password_reset_by_email_link(client, db, capsys):
    user_id = create_user("doc@example.com")
    response = post(client, "/forgot", {"email": "doc@example.com"}, token_from="/forgot")
    assert response.status_code == 200 and "отправили" in response.text
    assert "/reset/" in capsys.readouterr().out  # MAIL_BACKEND=console печатает письмо

    token = make_reset_token(db.get(User, user_id))
    assert client.get(f"/reset/{token}").status_code == 200
    response = post(
        client, f"/reset/{token}",
        {"password": "brand-new-pass-9", "password2": "brand-new-pass-9"}, token_from=f"/reset/{token}",
    )
    assert response.status_code == 303 and response.headers["location"] == "/login"
    assert login(client, "doc@example.com", "brand-new-pass-9").status_code == 303
    # Ссылка одноразовая: после смены пароля она перестаёт работать.
    assert client.get(f"/reset/{token}").status_code == 400


def test_forgot_does_not_reveal_unknown_email(client, capsys):
    response = post(client, "/forgot", {"email": "nobody@example.com"}, token_from="/forgot")
    assert response.status_code == 200 and "отправили" in response.text
    assert "/reset/" not in capsys.readouterr().out


def test_invalid_reset_token(client):
    assert client.get("/reset/garbage").status_code == 400


def test_profile_name_update(client, db):
    user_id = create_user("doc@example.com")
    login(client, "doc@example.com")
    assert post(client, "/profile", {"full_name": "  Петрова   Анна  Сергеевна "}).status_code == 303
    assert db.get(User, user_id).full_name == "Петрова Анна Сергеевна"


def test_landing_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/no-such-page").status_code == 404
    assert "csrf_token" in client.get("/login").text
    assert csrf(client, "/login")

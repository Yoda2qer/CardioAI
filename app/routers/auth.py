import re

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..mailer import mail_enabled, send_mail
from ..models import InviteCode, User, utcnow
from ..security import (
    RESET_TOKEN_MAX_AGE,
    get_optional_user,
    hash_password,
    login_throttle,
    login_user,
    logout_user,
    make_reset_token,
    password_problem,
    require_user,
    user_from_reset_token,
    verify_csrf,
    verify_password,
)
from ..web import flash, render

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Сравнение с заранее посчитанным хешем выравнивает время ответа, когда адрес не найден.
_DUMMY_HASH = hash_password("cardioai-dummy-password")


def normalize_email(value: str) -> str:
    return value.strip().lower()


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _client_key(request: Request, email: str) -> str:
    host = request.client.host if request.client else "?"
    return f"{email}|{host}"


@router.get("/")
def landing(request: Request, user: User | None = Depends(get_optional_user)):
    if user:
        return _redirect("/course")
    return render(request, "landing.html")


# --- Вход и выход -----------------------------------------------------------


@router.get("/login")
def login_form(request: Request, user: User | None = Depends(get_optional_user)):
    if user:
        return _redirect("/course")
    return render(request, "auth/login.html", email="", error=None)


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    email = normalize_email(email)
    key = _client_key(request, email)
    blocked = login_throttle.seconds_blocked(key)
    if blocked:
        minutes = (blocked + 59) // 60
        error = f"Слишком много неудачных попыток. Повторите через {minutes} мин."
        return render(request, "auth/login.html", status_code=429, email=email, error=error)

    user = db.scalar(select(User).where(User.email == email))
    password_ok = verify_password(user.password_hash if user else _DUMMY_HASH, password)
    if user is None or not password_ok:
        login_throttle.record_failure(key)
        error = "Неверный email или пароль."
        return render(request, "auth/login.html", status_code=400, email=email, error=error)
    if not user.is_active:
        error = "Учётная запись заблокирована. Обратитесь к администратору."
        return render(request, "auth/login.html", status_code=403, email=email, error=error)

    login_throttle.reset(key)
    user.last_login_at = utcnow()
    db.commit()
    login_user(request, user)
    return _redirect("/profile/password" if user.must_change_password else "/course")


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request):
    logout_user(request)
    return _redirect("/")


# --- Регистрация ------------------------------------------------------------


@router.get("/register")
def register_form(request: Request, user: User | None = Depends(get_optional_user)):
    if user:
        return _redirect("/course")
    return render(request, "auth/register.html", form={}, errors={})


@router.post("/register", dependencies=[Depends(verify_csrf)])
def register(
    request: Request,
    full_name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    password2: str = Form(""),
    invite_code: str = Form(""),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    full_name = " ".join(full_name.split())
    email = normalize_email(email)
    invite_code = invite_code.strip()
    form = {"full_name": full_name, "email": email, "invite_code": invite_code}
    errors: dict[str, str] = {}

    if not 2 <= len(full_name) <= 150:
        errors["full_name"] = "Укажите фамилию, имя и отчество — они будут в сертификате."
    if not EMAIL_RE.match(email) or len(email) > 254:
        errors["email"] = "Проверьте адрес электронной почты."
    elif db.scalar(select(User.id).where(User.email == email)):
        errors["email"] = "Этот адрес уже зарегистрирован. Попробуйте войти."
    problem = password_problem(password)
    if problem:
        errors["password"] = problem
    elif password != password2:
        errors["password2"] = "Пароли не совпадают."

    invite = None
    if settings.invite_required:
        invite = db.scalar(select(InviteCode).where(InviteCode.code == invite_code))
        if invite is None or not invite.is_usable:
            errors["invite_code"] = "Код приглашения не найден или больше не действует."

    if errors:
        return render(request, "auth/register.html", status_code=400, form=form, errors=errors)

    user = User(email=email, full_name=full_name, password_hash=hash_password(password))
    if invite:
        invite.uses += 1
        user.invite_code = invite
    user.last_login_at = utcnow()
    db.add(user)
    db.commit()
    login_user(request, user)
    flash(request, "Добро пожаловать! Курс открыт — начните с первого урока.", "success")
    return _redirect("/course")


# --- Сброс пароля -----------------------------------------------------------


@router.get("/forgot")
def forgot_form(request: Request):
    return render(request, "auth/forgot.html", mail_enabled=mail_enabled(), sent=False)


@router.post("/forgot", dependencies=[Depends(verify_csrf)])
def forgot(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(""),
    db: Session = Depends(get_db),
):
    if mail_enabled():
        user = db.scalar(select(User).where(User.email == normalize_email(email)))
        if user and user.is_active:
            link = f"{get_settings().base_url.rstrip('/')}/reset/{make_reset_token(user)}"
            body = (
                f"Здравствуйте, {user.full_name}!\n\n"
                "Чтобы задать новый пароль на платформе CardioAI, откройте ссылку:\n"
                f"{link}\n\n"
                f"Ссылка действует {RESET_TOKEN_MAX_AGE // 60} минут. "
                "Если вы не запрашивали сброс пароля, просто проигнорируйте это письмо."
            )
            background.add_task(send_mail, user.email, "CardioAI: сброс пароля", body)
    # Ответ одинаков для любого адреса, чтобы по нему нельзя было узнать, кто зарегистрирован.
    return render(request, "auth/forgot.html", mail_enabled=mail_enabled(), sent=True)


@router.get("/reset/{token}")
def reset_form(request: Request, token: str, db: Session = Depends(get_db)):
    valid = user_from_reset_token(db, token) is not None
    return render(request, "auth/reset.html", status_code=200 if valid else 400, valid=valid, error=None)


@router.post("/reset/{token}", dependencies=[Depends(verify_csrf)])
def reset(
    request: Request,
    token: str,
    password: str = Form(""),
    password2: str = Form(""),
    db: Session = Depends(get_db),
):
    user = user_from_reset_token(db, token)
    if user is None:
        return render(request, "auth/reset.html", status_code=400, valid=False, error=None)
    error = password_problem(password) or (None if password == password2 else "Пароли не совпадают.")
    if error:
        return render(request, "auth/reset.html", status_code=400, valid=True, error=error)
    user.password_hash = hash_password(password)
    user.session_version += 1
    user.must_change_password = False
    db.commit()
    logout_user(request)
    flash(request, "Пароль изменён. Войдите с новым паролем.", "success")
    return _redirect("/login")


# --- Профиль ----------------------------------------------------------------


@router.get("/profile")
def profile(request: Request, user: User = Depends(require_user)):
    return render(request, "auth/profile.html", error=None)


@router.post("/profile", dependencies=[Depends(verify_csrf)])
def update_profile(
    request: Request,
    full_name: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    full_name = " ".join(full_name.split())
    if not 2 <= len(full_name) <= 150:
        return render(request, "auth/profile.html", status_code=400, error="Укажите ФИО полностью.")
    user.full_name = full_name
    db.commit()
    flash(request, "Данные профиля сохранены.", "success")
    return _redirect("/profile")


@router.get("/profile/password")
def password_form(request: Request, user: User = Depends(require_user)):
    return render(request, "auth/password.html", error=None)


@router.post("/profile/password", dependencies=[Depends(verify_csrf)])
def change_password(
    request: Request,
    current_password: str = Form(""),
    password: str = Form(""),
    password2: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    # После входа по временному паролю текущий пароль повторно не спрашиваем.
    if not user.must_change_password and not verify_password(user.password_hash, current_password):
        error = "Текущий пароль указан неверно."
    else:
        error = password_problem(password) or (None if password == password2 else "Пароли не совпадают.")
    if error:
        return render(request, "auth/password.html", status_code=400, error=error)
    user.password_hash = hash_password(password)
    user.session_version += 1
    user.must_change_password = False
    db.commit()
    login_user(request, user)
    flash(request, "Пароль изменён.", "success")
    return _redirect("/course")

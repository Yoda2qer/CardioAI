import html
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..email_verification import check_code, issue_code
from ..models import User
from ..security import csrf_token, require_user, verify_csrf
from ..web import flash

router = APIRouter(prefix="/verify-email", tags=["verify-email"])

PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Подтверждение почты — CardioAI</title>
<style>
body{font-family:system-ui,sans-serif;background:#f4f6f8;margin:0;padding:40px 16px;color:#1e2327}
.card{max-width:420px;margin:0 auto;background:#fff;padding:28px;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08)}
input,button{font-size:16px;padding:10px 14px;border-radius:8px;border:1px solid #ccd3d9}
button{background:#1976d2;color:#fff;border:none;cursor:pointer}
.ok{color:#2e7d32}.err{color:#c62828}form{margin-top:16px}.skip{display:block;margin-top:20px;font-size:14px}
</style></head><body><div class="card">
<h2>Подтверждение почты</h2>
<p>Мы отправим 6-значный код на <b>__EMAIL__</b>.</p>
__MSG__
<form method="post" action="/verify-email/send">
<input type="hidden" name="csrf_token" value="__CSRF__">
<button type="submit">Отправить код</button></form>
<form method="post" action="/verify-email/confirm">
<input type="hidden" name="csrf_token" value="__CSRF__">
<input name="code" inputmode="numeric" maxlength="6" pattern="[0-9]{6}" placeholder="Код из письма" required>
<button type="submit">Подтвердить</button></form>
<a class="skip" href="/course">Пропустить пока</a>
</div></body></html>"""


def _go(msg: str = "", error: str = "") -> RedirectResponse:
    q = ("?msg=" + quote(msg)) if msg else (("?error=" + quote(error)) if error else "")
    return RedirectResponse("/verify-email" + q, status_code=303)


@router.get("", response_class=HTMLResponse)
def page(request: Request, user: User = Depends(require_user), msg: str = "", error: str = ""):
    if user.email_verified:
        return RedirectResponse("/course", status_code=303)
    block = ""
    if msg:
        block = f'<p class="ok">{html.escape(msg)}</p>'
    elif error:
        block = f'<p class="err">{html.escape(error)}</p>'
    out = (PAGE.replace("__EMAIL__", html.escape(user.email))
               .replace("__MSG__", block)
               .replace("__CSRF__", html.escape(csrf_token(request))))
    return HTMLResponse(out)


@router.post("/send", dependencies=[Depends(verify_csrf)])
def send(user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.email_verified:
        return RedirectResponse("/course", status_code=303)
    if issue_code(db, user) is None:
        return _go(error="Подождите минуту перед повторной отправкой.")
    return _go(msg="Код отправлен. Пока почта не настроена, код смотрите в консоли сервера.")


@router.post("/confirm", dependencies=[Depends(verify_csrf)])
def confirm(request: Request, code: str = Form(""), user: User = Depends(require_user),
            db: Session = Depends(get_db)):
    err = check_code(db, user, code)
    if err:
        return _go(error=err)
    flash(request, "Почта подтверждена.", "success")
    return RedirectResponse("/course", status_code=303)
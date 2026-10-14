import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..content import get_course
from ..db import get_db
from ..models import InviteCode, LessonProgress, PracticeSubmission, QuizAttempt, User
from ..progress import build_progress
from ..security import generate_temp_password, hash_password, require_admin, verify_csrf
from ..web import flash, render

router = APIRouter(prefix="/admin")


def _get_user(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "Пользователь не найден")
    return target


def _back(user_id: int) -> RedirectResponse:
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@router.get("")
def users_list(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    course = get_course()
    rows = []
    for person in db.scalars(select(User).order_by(User.created_at.desc())):
        progress = build_progress(db, person, course)
        rows.append(
            {
                "user": person,
                "percent": progress.percent,
                "quizzes": sum(q.passed for q in progress.quiz.values()),
                "completed": progress.completed,
            }
        )
    students = [r for r in rows if not r["user"].is_admin]
    stats = {
        "students": len(students),
        "started": sum(r["percent"] > 0 for r in students),
        "completed": sum(r["completed"] for r in students),
        "average": round(sum(r["percent"] for r in students) / len(students)) if students else 0,
    }
    return render(request, "admin/users.html", rows=rows, stats=stats)


def _user_detail(request: Request, db: Session, target: User, temp_password: str | None = None):
    course = get_course()
    done_at = {
        row.lesson_id: row.completed_at
        for row in db.scalars(select(LessonProgress).where(LessonProgress.user_id == target.id))
    }
    submissions = {
        row.lesson_id: row
        for row in db.scalars(select(PracticeSubmission).where(PracticeSubmission.user_id == target.id))
    }
    attempts: dict[str, list[QuizAttempt]] = {}
    for attempt in db.scalars(
        select(QuizAttempt).where(QuizAttempt.user_id == target.id).order_by(QuizAttempt.created_at)
    ):
        attempts.setdefault(attempt.section_id, []).append(attempt)
    return render(
        request,
        "admin/user_detail.html",
        target=target,
        progress=build_progress(db, target, course),
        done_at=done_at,
        submissions=submissions,
        attempts=attempts,
        temp_password=temp_password,
    )


@router.get("/users/{user_id}")
def user_detail(
    request: Request, user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    return _user_detail(request, db, _get_user(db, user_id))


@router.post("/users/{user_id}/reset-password", dependencies=[Depends(verify_csrf)])
def reset_password(
    request: Request, user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    target = _get_user(db, user_id)
    if target.id == admin.id:
        raise HTTPException(400, "Свой пароль меняйте в профиле")
    temp_password = generate_temp_password()
    target.password_hash = hash_password(temp_password)
    target.must_change_password = True
    target.session_version += 1
    db.commit()
    # Пароль показывается один раз, прямо в ответе: в базе остаётся только хеш.
    return _user_detail(request, db, target, temp_password=temp_password)


@router.post("/users/{user_id}/toggle-active", dependencies=[Depends(verify_csrf)])
def toggle_active(
    request: Request, user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    target = _get_user(db, user_id)
    if target.id == admin.id:
        raise HTTPException(400, "Нельзя заблокировать самого себя")
    target.is_active = not target.is_active
    db.commit()
    flash(request, "Доступ восстановлен." if target.is_active else "Пользователь заблокирован.", "success")
    return _back(target.id)


@router.post("/users/{user_id}/toggle-admin", dependencies=[Depends(verify_csrf)])
def toggle_admin(
    request: Request, user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    target = _get_user(db, user_id)
    if target.id == admin.id:
        raise HTTPException(400, "Нельзя изменить собственную роль")
    target.role = "student" if target.is_admin else "admin"
    db.commit()
    flash(request, "Роль изменена.", "success")
    return _back(target.id)


@router.post("/users/{user_id}/reset-quiz/{section_id}", dependencies=[Depends(verify_csrf)])
def reset_quiz(
    request: Request,
    user_id: int,
    section_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = _get_user(db, user_id)
    if get_course().section(section_id) is None:
        raise HTTPException(404, "Раздел не найден")
    # Аннулируются только неудачные попытки: сданный тест остаётся сданным.
    db.execute(
        update(QuizAttempt)
        .where(
            QuizAttempt.user_id == target.id,
            QuizAttempt.section_id == section_id,
            QuizAttempt.passed.is_(False),
        )
        .values(is_void=True)
    )
    db.commit()
    flash(request, "Попытки сброшены: слушатель может сдавать тест заново.", "success")
    return _back(target.id)


# --- Коды приглашения -------------------------------------------------------


def generate_invite_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "CARDIO-" + "".join(secrets.choice(alphabet) for _ in range(8))


@router.get("/invites")
def invites(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    codes = list(db.scalars(select(InviteCode).order_by(InviteCode.created_at.desc())))
    return render(request, "admin/invites.html", codes=codes, error=None)


@router.post("/invites", dependencies=[Depends(verify_csrf)])
def create_invite(
    request: Request,
    code: str = Form(""),
    note: str = Form(""),
    max_uses: str = Form(""),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    code = code.strip() or generate_invite_code()
    error = None
    limit = None
    if not 4 <= len(code) <= 64 or any(ch.isspace() for ch in code):
        error = "Код должен быть длиной от 4 до 64 символов и без пробелов."
    elif db.scalar(select(InviteCode.id).where(InviteCode.code == code)):
        error = "Такой код уже существует."
    elif max_uses.strip():
        if max_uses.strip().isdigit() and int(max_uses) > 0:
            limit = int(max_uses)
        else:
            error = "Лимит регистраций должен быть положительным числом."
    if error:
        codes = list(db.scalars(select(InviteCode).order_by(InviteCode.created_at.desc())))
        return render(request, "admin/invites.html", status_code=400, codes=codes, error=error)
    db.add(InviteCode(code=code, note=note.strip()[:200], max_uses=limit))
    db.commit()
    flash(request, f"Код {code} создан.", "success")
    return RedirectResponse("/admin/invites", status_code=303)


@router.post("/invites/{invite_id}/toggle", dependencies=[Depends(verify_csrf)])
def toggle_invite(
    request: Request, invite_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    invite = db.get(InviteCode, invite_id)
    if invite is None:
        raise HTTPException(404, "Код не найден")
    invite.is_active = not invite.is_active
    db.commit()
    return RedirectResponse("/admin/invites", status_code=303)

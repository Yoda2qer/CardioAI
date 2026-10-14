from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..content import Lesson, get_course
from ..db import get_db
from ..grading import evaluate_checks
from ..models import LessonProgress, PracticeSubmission, User, utcnow
from ..progress import DONE, LOCKED, build_progress
from ..security import require_user, verify_csrf
from ..web import render

router = APIRouter()


def _get_lesson(lesson_id: str) -> Lesson:
    lesson = get_course().lesson(lesson_id)
    if lesson is None:
        raise HTTPException(404, "Урок не найден")
    return lesson


def _neighbours(lesson: Lesson) -> tuple[str | None, str]:
    """Адреса предыдущего и следующего шага. После последнего урока раздела идёт тест."""
    lessons = lesson.section.lessons
    index = lesson.number - 1
    prev_url = f"/lesson/{lessons[index - 1].id}" if index > 0 else None
    if index + 1 < len(lessons):
        next_url = f"/lesson/{lessons[index + 1].id}"
    else:
        next_url = f"/quiz/{lesson.section.id}"
    return prev_url, next_url


def mark_lesson_done(db: Session, user: User, lesson_id: str) -> None:
    exists = db.scalar(
        select(LessonProgress.id).where(
            LessonProgress.user_id == user.id, LessonProgress.lesson_id == lesson_id
        )
    )
    if not exists:
        db.add(LessonProgress(user_id=user.id, lesson_id=lesson_id))


@router.get("/course")
def dashboard(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    progress = build_progress(db, user, get_course())
    return render(request, "course/dashboard.html", progress=progress)


@router.get("/lesson/{lesson_id}")
def lesson_page(
    request: Request,
    lesson_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    lesson = _get_lesson(lesson_id)
    progress = build_progress(db, user, get_course())
    state = progress.lesson_state[lesson.id]
    if state == LOCKED:
        return render(
            request,
            "course/locked.html",
            status_code=403,
            progress=progress,
            title=lesson.title,
            reason="Этот урок откроется, когда вы завершите предыдущие.",
        )
    prev_url, next_url = _neighbours(lesson)
    context = dict(
        lesson=lesson, section=lesson.section, progress=progress, state=state,
        prev_url=prev_url, next_url=next_url,
    )
    if not lesson.is_practice:
        return render(request, "course/lesson.html", **context)

    submission = db.scalar(
        select(PracticeSubmission).where(
            PracticeSubmission.user_id == user.id, PracticeSubmission.lesson_id == lesson.id
        )
    )
    practice = lesson.practice
    config = {
        "lessonId": lesson.id,
        "starter": practice.starter,
        "saved": submission.code if submission else None,
        "varNames": practice.var_names,
        "packages": practice.packages,
        "datasets": practice.datasets,
        "pyodideBaseUrl": get_settings().pyodide_base_url,
        "nextUrl": next_url,
    }
    return render(request, "course/practice.html", practice=practice, config=config, **context)


@router.post("/lesson/{lesson_id}/complete", dependencies=[Depends(verify_csrf)])
def complete_lesson(
    lesson_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    lesson = _get_lesson(lesson_id)
    if lesson.is_practice:
        raise HTTPException(400, "Практический урок засчитывается после проверки кода")
    progress = build_progress(db, user, get_course())
    if progress.lesson_state[lesson.id] == LOCKED:
        raise HTTPException(403, "Урок пока недоступен")
    mark_lesson_done(db, user, lesson.id)
    db.commit()
    return RedirectResponse(_neighbours(lesson)[1], status_code=303)


class PracticePayload(BaseModel):
    code: str = Field(max_length=50_000)
    values: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/practice/{lesson_id}/check", dependencies=[Depends(verify_csrf)])
def check_practice(
    lesson_id: str,
    payload: PracticePayload,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    lesson = _get_lesson(lesson_id)
    if not lesson.is_practice:
        raise HTTPException(400, "Это не практический урок")
    progress = build_progress(db, user, get_course())
    if progress.lesson_state[lesson.id] == LOCKED:
        raise HTTPException(403, "Урок пока недоступен")

    results = evaluate_checks(lesson.practice.checks, payload.values)
    passed = all(r.ok for r in results)

    submission = db.scalar(
        select(PracticeSubmission).where(
            PracticeSubmission.user_id == user.id, PracticeSubmission.lesson_id == lesson.id
        )
    )
    if submission is None:
        submission = PracticeSubmission(user_id=user.id, lesson_id=lesson.id, code="")
        db.add(submission)
    submission.code = payload.code
    submission.attempts = (submission.attempts or 0) + 1
    submission.passed = bool(submission.passed) or passed
    submission.updated_at = utcnow()
    if passed:
        mark_lesson_done(db, user, lesson.id)
    db.commit()

    return {
        "passed": passed,
        "already_done": progress.lesson_state[lesson.id] == DONE,
        "results": [{"label": r.label, "ok": r.ok, "message": r.message} for r in results],
    }

import json
import random
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..content import Section, get_course
from ..db import get_db
from ..grading import grade_quiz
from ..models import Certificate, QuizAttempt, User, utcnow
from ..progress import build_progress
from ..security import require_user, verify_csrf
from ..web import render

router = APIRouter()


def _get_section(section_id: str) -> Section:
    section = get_course().section(section_id)
    if section is None:
        raise HTTPException(404, "Раздел не найден")
    return section


def ensure_certificate(db: Session, user: User) -> Certificate:
    certificate = db.scalar(select(Certificate).where(Certificate.user_id == user.id))
    if certificate is None:
        number = f"CAI-{utcnow().year}-{secrets.token_hex(4).upper()}"
        certificate = Certificate(user_id=user.id, number=number)
        db.add(certificate)
        db.commit()
    return certificate


@router.get("/quiz/{section_id}")
def quiz_page(
    request: Request,
    section_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    section = _get_section(section_id)
    progress = build_progress(db, user, get_course())
    status = progress.quiz[section.id]
    if not status.available:
        return render(
            request,
            "course/locked.html",
            status_code=403,
            progress=progress,
            title=f"Тест по разделу {section.number}",
            reason="Тест откроется, когда вы завершите все уроки раздела.",
        )
    if status.passed:
        return RedirectResponse(f"/quiz/{section.id}/result", status_code=303)
    if not status.can_attempt:
        return render(request, "course/quiz_wait.html", section=section, status=status, progress=progress)

    # Порядок вопросов и вариантов меняется при каждом открытии; на оценку он не влияет,
    # потому что в форме передаются исходные индексы вариантов.
    questions = []
    for question in random.sample(section.quiz, len(section.quiz)):
        options = list(enumerate(question.options_html))
        random.shuffle(options)
        questions.append((question, options))
    return render(
        request, "course/quiz.html", section=section, questions=questions, status=status, progress=progress
    )


@router.post("/quiz/{section_id}", dependencies=[Depends(verify_csrf)])
async def submit_quiz(
    request: Request,
    section_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    section = _get_section(section_id)
    progress = build_progress(db, user, get_course())
    status = progress.quiz[section.id]
    if not status.can_attempt:
        return RedirectResponse(f"/quiz/{section.id}", status_code=303)

    form = await request.form()
    answers: dict[str, list[int]] = {}
    for question in section.quiz:
        chosen = set()
        for raw in form.getlist(f"q-{question.id}"):
            if isinstance(raw, str) and raw.isdigit() and int(raw) < len(question.options_html):
                chosen.add(int(raw))
        answers[question.id] = sorted(chosen)

    score, _ = grade_quiz(section.quiz, answers)
    total = len(section.quiz)
    passed = score * 100 >= total * get_settings().quiz_pass_percent
    db.add(
        QuizAttempt(
            user_id=user.id, section_id=section.id, score=score, total=total,
            passed=passed, answers_json=json.dumps(answers),
        )
    )
    db.commit()
    if passed and build_progress(db, user, get_course()).completed:
        ensure_certificate(db, user)
    return RedirectResponse(f"/quiz/{section.id}/result", status_code=303)


@router.get("/quiz/{section_id}/result")
def quiz_result(
    request: Request,
    section_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    section = _get_section(section_id)
    course = get_course()
    progress = build_progress(db, user, course)
    status = progress.quiz[section.id]
    attempt = status.passing_attempt or status.last_attempt
    if attempt is None:
        return RedirectResponse(f"/quiz/{section.id}", status_code=303)

    answers = json.loads(attempt.answers_json)
    _, marks = grade_quiz(section.quiz, answers)
    review = [
        {
            "question": question,
            "ok": ok,
            "chosen": set(answers.get(question.id, [])),
            "lesson": course.lesson(question.lesson_id),
        }
        for question, ok in zip(section.quiz, marks)
    ]
    next_section = next((s for s in course.sections if s.number == section.number + 1), None)
    return render(
        request,
        "course/quiz_result.html",
        section=section,
        attempt=attempt,
        status=status,
        review=review,
        progress=progress,
        next_section=next_section,
        percent=round(100 * attempt.score / attempt.total),
    )


@router.get("/certificate")
def certificate_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    course = get_course()
    progress = build_progress(db, user, course)
    if not progress.completed:
        return render(
            request,
            "course/locked.html",
            status_code=403,
            progress=progress,
            title="Сертификат",
            reason="Сертификат выдаётся после сдачи тестов по всем пяти разделам.",
        )
    certificate = ensure_certificate(db, user)
    return render(
        request, "course/certificate.html", certificate=certificate, progress=progress, holder=user
    )


@router.get("/verify/{number}")
def verify_certificate(request: Request, number: str, db: Session = Depends(get_db)):
    certificate = db.scalar(select(Certificate).where(Certificate.number == number.strip().upper()))
    return render(
        request, "course/verify.html", status_code=200 if certificate else 404,
        certificate=certificate, number=number,
    )

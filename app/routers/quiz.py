import json
import random
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..content import Section, get_course
from ..db import get_db
from ..grading import grade_quiz
from ..models import Certificate, QuizAttempt, Reflection, User, utcnow
from ..progress import build_progress
from ..security import require_user, verify_csrf
from ..web import flash, render

router = APIRouter()

# Вопросы рефлексии после каждого блока курса (раздела и итогового теста).
REFLECTION_QUESTIONS = [
    ("useful", "Что в этом блоке оказалось самым полезным для вашей учёбы или работы?"),
    ("difficult", "Что осталось непонятным или вызвало затруднения?"),
    ("apply", "Где и как вы сможете применить полученные знания?"),
]
REFLECTION_MAX_LENGTH = 2000


def _get_section(section_id: str) -> Section:
    """Раздел курса или итоговый тест."""
    section = get_course().quiz_unit(section_id)
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
    return render(
        request,
        "course/quiz_result.html",
        section=section,
        attempt=attempt,
        status=status,
        review=review,
        progress=progress,
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


@router.get("/reflection/{section_id}")
def reflection_form(
    request: Request,
    section_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    section = _get_section(section_id)
    progress = build_progress(db, user, get_course())
    if not progress.quiz[section.id].passed:
        return render(
            request, "course/locked.html", status_code=403, progress=progress,
            title="Рефлексия", reason="Рефлексия по блоку открывается после сдачи его теста.",
        )
    existing = db.scalar(
        select(Reflection).where(Reflection.user_id == user.id, Reflection.section_id == section.id)
    )
    return render(
        request, "course/reflection.html", section=section, progress=progress,
        questions=REFLECTION_QUESTIONS, existing=existing,
        answers=json.loads(existing.answers_json) if existing else {}, error=None,
    )


@router.post("/reflection/{section_id}", dependencies=[Depends(verify_csrf)])
async def submit_reflection(
    request: Request,
    section_id: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    section = _get_section(section_id)
    course = get_course()
    progress = build_progress(db, user, course)
    if not progress.quiz[section.id].passed:
        raise HTTPException(403, "Рефлексия по блоку открывается после сдачи его теста")
    form = await request.form()
    rating = str(form.get("rating", ""))
    answers = {key: str(form.get(key, "")).strip()[:REFLECTION_MAX_LENGTH] for key, _ in REFLECTION_QUESTIONS}
    if rating not in {"1", "2", "3", "4", "5"} or not any(answers.values()):
        return render(
            request, "course/reflection.html", status_code=400, section=section, progress=progress,
            questions=REFLECTION_QUESTIONS, existing=None, answers=answers,
            error="Оцените блок и ответьте хотя бы на один вопрос.",
        )
    reflection = db.scalar(
        select(Reflection).where(Reflection.user_id == user.id, Reflection.section_id == section.id)
    )
    if reflection is None:
        reflection = Reflection(user_id=user.id, section_id=section.id, rating=0, answers_json="{}")
        db.add(reflection)
    reflection.rating = int(rating)
    reflection.answers_json = json.dumps(answers, ensure_ascii=False)
    db.commit()

    progress = build_progress(db, user, course)
    if progress.completed:
        ensure_certificate(db, user)
    flash(request, "Спасибо за отзыв! Он поможет сделать курс лучше.", "success")
    return RedirectResponse(progress.next_url, status_code=303)

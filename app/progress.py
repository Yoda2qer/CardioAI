"""Правила доступа к урокам и тестам. Единственное место, где решается,
что слушателю открыто, а что ещё нет.

Порядок строгий: урок открыт, когда завершены все предыдущие уроки раздела;
тест — когда завершены все уроки раздела; следующий раздел — когда сдан тест.
Администратору открыто всё.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .content import Course, Section
from .models import LessonProgress, QuizAttempt, User, utcnow

DONE, OPEN, LOCKED = "done", "open", "locked"


@dataclass
class QuizStatus:
    available: bool = False
    passed: bool = False
    passing_attempt: QuizAttempt | None = None
    last_attempt: QuizAttempt | None = None
    attempts_left: int = 0
    locked_until: datetime | None = None

    @property
    def can_attempt(self) -> bool:
        return self.available and not self.passed and self.attempts_left > 0

    @property
    def state(self) -> str:
        if self.passed:
            return DONE
        return OPEN if self.available else LOCKED


@dataclass
class CourseProgress:
    lesson_state: dict[str, str] = field(default_factory=dict)
    section_open: dict[str, bool] = field(default_factory=dict)
    quiz: dict[str, QuizStatus] = field(default_factory=dict)
    total_steps: int = 0
    done_steps: int = 0
    next_url: str = "/course"

    @property
    def percent(self) -> int:
        return round(100 * self.done_steps / self.total_steps) if self.total_steps else 0

    @property
    def completed(self) -> bool:
        return bool(self.quiz) and all(q.passed for q in self.quiz.values())

    def section_done(self, section: Section) -> int:
        done = sum(self.lesson_state[l.id] == DONE for l in section.lessons)
        return done + int(self.quiz[section.id].passed)


def quiz_status(attempts: list[QuizAttempt], available: bool, now: datetime | None = None) -> QuizStatus:
    """attempts — неаннулированные попытки одного слушателя по одному разделу, по времени."""
    settings = get_settings()
    now = now or utcnow()
    status = QuizStatus(available=available, last_attempt=attempts[-1] if attempts else None)
    status.passing_attempt = next((a for a in attempts if a.passed), None)
    status.passed = status.passing_attempt is not None
    if status.passed:
        return status
    failed = len(attempts)
    used = failed % settings.quiz_max_attempts
    if failed and used == 0:
        # Серия попыток исчерпана: новая серия откроется после паузы.
        unlock_at = attempts[-1].created_at + timedelta(hours=settings.quiz_cooldown_hours)
        if now < unlock_at:
            status.locked_until = unlock_at
            return status
    status.attempts_left = settings.quiz_max_attempts - used
    return status


def build_progress(db: Session, user: User, course: Course) -> CourseProgress:
    done_ids = set(
        db.scalars(select(LessonProgress.lesson_id).where(LessonProgress.user_id == user.id))
    )
    attempts_by_section: dict[str, list[QuizAttempt]] = {}
    for attempt in db.scalars(
        select(QuizAttempt)
        .where(QuizAttempt.user_id == user.id, QuizAttempt.is_void.is_(False))
        .order_by(QuizAttempt.created_at, QuizAttempt.id)
    ):
        attempts_by_section.setdefault(attempt.section_id, []).append(attempt)

    progress = CourseProgress()
    next_url = None
    section_open = True
    for section in course.sections:
        opened = section_open or user.is_admin
        progress.section_open[section.id] = opened
        previous_done = True
        for lesson in section.lessons:
            if lesson.id in done_ids:
                state = DONE
            elif opened and (previous_done or user.is_admin):
                state = OPEN
            else:
                state = LOCKED
            progress.lesson_state[lesson.id] = state
            if state == OPEN and next_url is None:
                next_url = f"/lesson/{lesson.id}"
            previous_done = previous_done and state == DONE

        available = opened and (previous_done or user.is_admin)
        status = quiz_status(attempts_by_section.get(section.id, []), available)
        progress.quiz[section.id] = status
        if available and not status.passed and next_url is None:
            next_url = f"/quiz/{section.id}"
        section_open = section_open and status.passed

        progress.total_steps += len(section.lessons) + 1
        progress.done_steps += progress.section_done(section)

    progress.next_url = next_url or ("/certificate" if progress.completed else "/course")
    return progress

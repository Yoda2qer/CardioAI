from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Текущее время UTC без tzinfo: так его одинаково хранят SQLite и PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    email_verified: Mapped[bool] = mapped_column(default=False, server_default="0")

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="student")
    is_active: Mapped[bool] = mapped_column(default=True)
    must_change_password: Mapped[bool] = mapped_column(default=False)
    # Увеличивается при смене пароля: все прежние сессии и ссылки сброса перестают работать.
    session_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(default=None)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class LessonProgress(Base):
    __tablename__ = "lesson_progress"
    __table_args__ = (UniqueConstraint("user_id", "lesson_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[str] = mapped_column(String(32))
    completed_at: Mapped[datetime] = mapped_column(default=utcnow)


class PracticeSubmission(Base):
    """Последняя отправка кода по практическому уроку (одна строка на слушателя и урок)."""

    __tablename__ = "practice_submissions"
    __table_args__ = (UniqueConstraint("user_id", "lesson_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[str] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(Text)
    passed: Mapped[bool] = mapped_column(default=False)
    attempts: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str] = mapped_column(String(32))
    score: Mapped[int]
    total: Mapped[int]
    passed: Mapped[bool]
    # JSON: {"<id вопроса>": [индексы выбранных вариантов]}
    answers_json: Mapped[str] = mapped_column(Text)
    # Аннулированные попытки не учитываются в лимите (сброс администратором).
    is_void: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    issued_at: Mapped[datetime] = mapped_column(default=utcnow)

    user: Mapped[User] = relationship()


class HomeworkSubmission(Base):
    """Домашнее задание раздела: ответ слушателя и отзыв преподавателя."""

    __tablename__ = "homework_submissions"
    __table_args__ = (UniqueConstraint("user_id", "lesson_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[str] = mapped_column(String(32))
    answer: Mapped[str] = mapped_column(Text)
    # submitted — ждёт проверки, accepted — принято, returned — возвращено на доработку
    status: Mapped[str] = mapped_column(String(16), default="submitted")
    teacher_comment: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime] = mapped_column(default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(default=None)

    user: Mapped[User] = relationship()


class Reflection(Base):
    """Рефлексия слушателя после завершения раздела или курса."""

    __tablename__ = "reflections"
    __table_args__ = (UniqueConstraint("user_id", "section_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[str] = mapped_column(String(32))
    rating: Mapped[int]
    # JSON: {"<ключ вопроса>": "ответ"}
    answers_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


# --- Подтверждение email (заглушка) ---
from datetime import datetime as _dt
from sqlalchemy import Column as _Col, DateTime as _DateTime, ForeignKey as _FK, Integer as _Int, String as _Str


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id = _Col(_Int, primary_key=True)
    user_id = _Col(_Int, _FK("users.id"), index=True, nullable=False)
    code_hash = _Col(_Str(128), nullable=False)
    expires_at = _Col(_DateTime, nullable=False)
    attempts = _Col(_Int, default=0, nullable=False)
    created_at = _Col(_DateTime, default=_dt.utcnow, nullable=False)
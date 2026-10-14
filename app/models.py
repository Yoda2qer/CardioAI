from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Текущее время UTC без tzinfo: так его одинаково хранят SQLite и PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InviteCode(Base):
    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    note: Mapped[str] = mapped_column(String(200), default="")
    max_uses: Mapped[int | None] = mapped_column(default=None)
    uses: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    @property
    def is_usable(self) -> bool:
        return self.is_active and (self.max_uses is None or self.uses < self.max_uses)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="student")
    is_active: Mapped[bool] = mapped_column(default=True)
    must_change_password: Mapped[bool] = mapped_column(default=False)
    # Увеличивается при смене пароля: все прежние сессии и ссылки сброса перестают работать.
    session_version: Mapped[int] = mapped_column(default=1)
    invite_code_id: Mapped[int | None] = mapped_column(ForeignKey("invite_codes.id"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(default=None)

    invite_code: Mapped[InviteCode | None] = relationship()

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

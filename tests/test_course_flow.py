from datetime import timedelta

from conftest import create_user, csrf, login, post
from sqlalchemy import select

from app.content import get_course
from app.models import (
    Certificate, HomeworkSubmission, LessonProgress, PracticeSubmission, QuizAttempt, Reflection, User,
)

GOOD_VALUES = {"total": 55, "ratio": 13.75}


def enter(client, email="student@example.com", role="student") -> int:
    user_id = create_user(email, role=role)
    login(client, email)
    return user_id


def check(client, lesson_id, values, code="total = 55"):
    return client.post(
        f"/api/practice/{lesson_id}/check",
        json={"code": code, "values": values},
        headers={"X-CSRF-Token": csrf(client)},
    )


def quiz_form(section_id: str, wrong: int = 0) -> dict:
    """Ответы на тест: первые wrong вопросов неверно, остальные верно."""
    data = {}
    for number, question in enumerate(get_course().quiz_unit(section_id).quiz):
        chosen = [2] if number < wrong else sorted(question.correct)
        data[f"q-{question.id}"] = [str(i) for i in chosen]
    return data


def take_quiz(client, section_id, wrong=0):
    return post(client, f"/quiz/{section_id}", quiz_form(section_id, wrong))


HOMEWORK_ANSWER = "Средний возраст пациентов 61 год, пропусков нет; выводы приведены ниже."


def finish_section_a(client):
    post(client, "/lesson/a1/complete")
    check(client, "a2", GOOD_VALUES)
    post(client, "/lesson/a3/homework", {"answer": HOMEWORK_ANSWER})


def reflect(client, unit_id, **answers):
    data = {"rating": "4", "useful": "Разбор метрик на реальных данных"}
    data.update(answers)
    return post(client, f"/reflection/{unit_id}", data)


def test_new_student_sees_only_first_lesson(client):
    enter(client)
    assert client.get("/course").status_code == 200
    assert client.get("/lesson/a1").status_code == 200
    assert client.get("/lesson/a2").status_code == 403
    assert client.get("/quiz/a").status_code == 403
    assert client.get("/lesson/b1").status_code == 403
    assert client.get("/certificate").status_code == 403
    assert client.get("/lesson/nope").status_code == 404


def test_completing_theory_opens_next_lesson(client, db):
    user_id = enter(client)
    response = post(client, "/lesson/a1/complete")
    assert response.status_code == 303 and response.headers["location"] == "/lesson/a2"
    assert client.get("/lesson/a2").status_code == 200
    # Повторная отметка не создаёт дубликат.
    post(client, "/lesson/a1/complete")
    rows = db.scalars(select(LessonProgress).where(LessonProgress.user_id == user_id)).all()
    assert [row.lesson_id for row in rows] == ["a1"]


def test_locked_lesson_cannot_be_completed(client):
    enter(client)
    assert post(client, "/lesson/b1/complete").status_code == 403
    assert check(client, "a2", GOOD_VALUES).status_code == 403


def test_practice_cannot_be_marked_done_without_check(client):
    enter(client)
    post(client, "/lesson/a1/complete")
    assert post(client, "/lesson/a2/complete").status_code == 400
    assert client.get("/quiz/a").status_code == 403


def test_practice_check_reports_each_problem(client, db):
    user_id = enter(client)
    post(client, "/lesson/a1/complete")

    body = check(client, "a2", {"total": 54}).json()
    assert body["passed"] is False
    by_label = {item["label"]: item for item in body["results"]}
    assert by_label["Сумма"]["message"] == "Используйте sum и range."
    assert "не найдена" in by_label["Отношение"]["message"]
    assert client.get("/quiz/a").status_code == 403

    body = check(client, "a2", GOOD_VALUES, code="total = sum(range(1, 11))").json()
    assert body["passed"] is True and all(item["ok"] for item in body["results"])
    submission = db.scalar(select(PracticeSubmission).where(PracticeSubmission.user_id == user_id))
    assert submission.passed and submission.attempts == 2 and "sum(range" in submission.code
    assert client.get("/lesson/a3").status_code == 200
    assert client.get("/quiz/a").status_code == 403


def test_practice_stays_done_after_later_wrong_submission(client, db):
    enter(client)
    post(client, "/lesson/a1/complete")
    check(client, "a2", GOOD_VALUES)
    assert check(client, "a2", {"total": 1}).json()["passed"] is False
    assert client.get("/lesson/a3").status_code == 200


def test_practice_api_requires_csrf_and_login(client):
    assert client.post("/api/practice/a2/check", json={"code": "", "values": {}}).status_code == 403
    enter(client)
    post(client, "/lesson/a1/complete")
    assert client.post("/api/practice/a2/check", json={"code": "", "values": {}}).status_code == 403


def test_quiz_pass_opens_next_section(client, db):
    user_id = enter(client)
    finish_section_a(client)
    response = take_quiz(client, "a", wrong=3)  # 12 из 15 = 80%
    assert response.status_code == 303
    attempt = db.scalar(select(QuizAttempt).where(QuizAttempt.user_id == user_id))
    assert attempt.score == 12 and attempt.passed
    result = client.get("/quiz/a/result")
    assert "Тест сдан" in result.text and "Пояснение 1" in result.text
    # Следующий раздел открывается только после рефлексии.
    assert client.get("/lesson/b1").status_code == 403
    assert reflect(client, "a").headers["location"] == "/lesson/b1"
    assert client.get("/lesson/b1").status_code == 200
    # Сданный тест повторно не открывается.
    assert client.get("/quiz/a").headers["location"] == "/quiz/a/result"


def test_failed_quiz_hides_correct_answers(client, db):
    enter(client)
    finish_section_a(client)
    take_quiz(client, "a", wrong=4)  # 11 из 15 — ниже порога
    result = client.get("/quiz/a/result").text
    assert "Пока не сдан" in result
    assert "Пояснение" not in result and "Верный вариант" not in result
    assert "Теория А1" in result  # ссылка на урок для повторения
    assert client.get("/lesson/b1").status_code == 403


def test_quiz_attempt_limit_and_cooldown(client, db):
    user_id = enter(client)
    finish_section_a(client)
    for _ in range(3):
        assert client.get("/quiz/a").status_code == 200
        take_quiz(client, "a", wrong=15)
    page = client.get("/quiz/a")
    assert "Попытки закончились" in page.text
    take_quiz(client, "a")  # отправка во время паузы игнорируется
    assert db.query(QuizAttempt).filter_by(user_id=user_id).count() == 3

    # Через сутки открывается новая серия из трёх попыток.
    for attempt in db.scalars(select(QuizAttempt)):
        attempt.created_at -= timedelta(hours=25)
    db.commit()
    page = client.get("/quiz/a")
    assert page.status_code == 200 and "Осталось попыток: 3" in page.text
    take_quiz(client, "a")
    assert "Тест сдан" in client.get("/quiz/a/result").text


def test_admin_can_reset_quiz_attempts(client, db):
    from fastapi.testclient import TestClient

    from app.main import app

    student_id = enter(client)
    finish_section_a(client)
    for _ in range(3):
        take_quiz(client, "a", wrong=15)
    assert "Попытки закончились" in client.get("/quiz/a").text

    create_user("admin@example.com", role="admin")
    with TestClient(app, follow_redirects=False) as admin:
        login(admin, "admin@example.com")
        assert post(admin, f"/admin/users/{student_id}/reset-quiz/a").status_code == 303

    page = client.get("/quiz/a")
    assert page.status_code == 200 and "Осталось попыток: 3" in page.text
    assert all(a.is_void for a in db.scalars(select(QuizAttempt)))


def test_unanswered_and_garbage_answers_count_as_wrong(client, db):
    enter(client)
    finish_section_a(client)
    post(client, "/quiz/a", {"q-a-q1": "99", "q-a-q2": "abc", "unknown": "1"})
    attempt = db.scalar(select(QuizAttempt))
    assert attempt.score == 0 and not attempt.passed


def test_partial_choice_in_multiple_answer_question_is_wrong(client, db):
    enter(client)
    finish_section_a(client)
    form = quiz_form("a")
    form["q-a-q5"] = ["0"]  # в вопросе два верных варианта, выбран один
    post(client, "/quiz/a", form)
    assert db.scalar(select(QuizAttempt)).score == 14


def test_certificate_after_all_quizzes(client, db):
    user_id = enter(client)
    finish_section_a(client)
    take_quiz(client, "a")
    reflect(client, "a")
    assert client.get("/certificate").status_code == 403
    post(client, "/lesson/b1/complete")
    take_quiz(client, "b")
    reflect(client, "b")
    # Итоговый тест и итоговая рефлексия обязательны для сертификата.
    assert client.get("/certificate").status_code == 403
    assert client.get("/quiz/final").status_code == 200
    take_quiz(client, "final")
    assert client.get("/certificate").status_code == 403
    reflect(client, "final")

    certificate = db.scalar(select(Certificate).where(Certificate.user_id == user_id))
    assert certificate is not None and certificate.number.startswith("CAI-")
    page = client.get("/certificate")
    assert page.status_code == 200 and certificate.number in page.text and "Тестовый Пользователь" in page.text
    assert "Курс пройден полностью" in client.get("/course").text

    post(client, "/logout")
    verify = client.get(f"/verify/{certificate.number.lower()}")
    assert verify.status_code == 200 and "Сертификат действителен" in verify.text
    assert client.get("/verify/CAI-0000-FFFFFFFF").status_code == 404


def test_admin_sees_everything_but_gets_no_certificate(client):
    enter(client, "admin@example.com", role="admin")
    for path in ("/lesson/a2", "/lesson/b1", "/quiz/a", "/quiz/b"):
        assert client.get(path).status_code == 200
    assert client.get("/certificate").status_code == 403


def test_admin_pages_are_closed_to_students(client):
    enter(client)
    assert client.get("/admin").status_code == 403
    assert client.get("/admin/homework").status_code == 403


def test_admin_user_management(client, db):
    from fastapi.testclient import TestClient

    from app.main import app

    student_id = create_user("student@example.com")
    admin_id = enter(client, "admin@example.com", role="admin")

    assert "student@example.com" in client.get("/admin").text
    assert client.get(f"/admin/users/{student_id}").status_code == 200
    assert client.get("/admin/users/9999").status_code == 404

    # Временный пароль показывается один раз и требует смены при входе.
    response = post(client, f"/admin/users/{student_id}/reset-password")
    assert response.status_code == 200
    temp = response.text.split('class="temp-password">')[1].split("<")[0]
    db.expire_all()
    assert db.get(User, student_id).must_change_password
    with TestClient(app, follow_redirects=False) as student:
        assert login(student, "student@example.com").status_code == 400  # старый пароль не подходит
        response = login(student, "student@example.com", temp)
        assert response.headers["location"] == "/profile/password"
        assert student.get("/course").headers["location"] == "/profile/password"
        response = post(student, "/profile/password", {"password": "my-own-pass-55", "password2": "my-own-pass-55"})
        assert response.status_code == 303
        assert student.get("/course").status_code == 200

        # Блокировка обрывает действующую сессию.
        assert post(client, f"/admin/users/{student_id}/toggle-active").status_code == 303
        assert student.get("/course").status_code == 303

    # Собой управлять нельзя.
    assert post(client, f"/admin/users/{admin_id}/toggle-active").status_code == 400
    assert post(client, f"/admin/users/{admin_id}/toggle-admin").status_code == 400
    assert post(client, f"/admin/users/{admin_id}/reset-password").status_code == 400

    post(client, f"/admin/users/{student_id}/toggle-admin")
    db.expire_all()
    assert db.get(User, student_id).role == "admin"


def test_homework_requires_answer_and_unlocks_quiz(client, db):
    enter(client)
    post(client, "/lesson/a1/complete")
    check(client, "a2", GOOD_VALUES)
    assert client.get("/lesson/a3").status_code == 200
    assert post(client, "/lesson/a3/complete").status_code == 400
    post(client, "/lesson/a3/homework", {"answer": "коротко"})
    assert db.scalar(select(HomeworkSubmission)) is None
    assert client.get("/quiz/a").status_code == 403

    response = post(client, "/lesson/a3/homework", {"answer": HOMEWORK_ANSWER})
    assert response.headers["location"] == "/quiz/a"
    assert db.scalar(select(HomeworkSubmission)).status == "submitted"
    assert client.get("/quiz/a").status_code == 200


def test_admin_reviews_homework(client, db):
    from fastapi.testclient import TestClient

    from app.main import app

    enter(client)
    finish_section_a(client)
    submission = db.scalar(select(HomeworkSubmission))

    create_user("admin@example.com", role="admin")
    with TestClient(app, follow_redirects=False) as admin:
        login(admin, "admin@example.com")
        assert HOMEWORK_ANSWER in admin.get("/admin/homework").text
        # Возврат без комментария не принимается.
        post(admin, f"/admin/homework/{submission.id}/review", {"decision": "returned"})
        db.expire_all()
        assert db.get(HomeworkSubmission, submission.id).status == "submitted"
        post(admin, f"/admin/homework/{submission.id}/review", {"decision": "returned", "comment": "Добавьте график"})
        db.expire_all()
        assert db.get(HomeworkSubmission, submission.id).status == "returned"
        assert "Добавьте график" in client.get("/lesson/a3").text

        post(client, "/lesson/a3/homework", {"answer": HOMEWORK_ANSWER + " График добавлен."})
        post(admin, f"/admin/homework/{submission.id}/review", {"decision": "accepted", "comment": "Отлично"})
        db.expire_all()
        assert db.get(HomeworkSubmission, submission.id).status == "accepted"
        # Принятую работу изменить нельзя.
        post(client, "/lesson/a3/homework", {"answer": "Совсем другой ответ на задание раздела"})
        db.expire_all()
        assert "График добавлен" in db.get(HomeworkSubmission, submission.id).answer


def test_reflection_requires_passed_quiz_and_rating(client, db):
    enter(client)
    finish_section_a(client)
    assert client.get("/reflection/a").status_code == 403
    take_quiz(client, "a")
    assert client.get("/reflection/a").status_code == 200
    assert reflect(client, "a", rating="9").status_code == 400
    assert reflect(client, "a", useful="").status_code == 400
    assert reflect(client, "a").status_code == 303
    reflection = db.scalar(select(Reflection))
    assert reflection.rating == 4 and "Разбор метрик" in reflection.answers_json


def test_public_pages(client):
    about = client.get("/about")
    assert about.status_code == 200 and "Учебный план" in about.text and "академических часа" in about.text
    assert client.get("/privacy").status_code == 200
    assert client.get("/sandbox").status_code == 303  # только после входа
    enter(client)
    assert client.get("/sandbox").status_code == 200

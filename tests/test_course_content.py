"""Проверки настоящего курса из каталога content/.

Остальные тесты работают с маленьким тестовым курсом; здесь проверяется, что
учебные материалы целы: структура соответствует программе, эталонные решения
проходят собственные проверки, а примеры кода в уроках выполняются и их вывод
в тексте не устарел.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from app.content import load_course  # noqa: E402

pytest.importorskip("sklearn", reason="нужны зависимости из requirements-dev.txt")

import run_solution  # noqa: E402
import sync_lesson_outputs  # noqa: E402

COURSE = load_course(ROOT / "content")
PRACTICES = sorted((ROOT / "content").glob("section-*/*practice*.yaml"))
LESSONS = sorted((ROOT / "content").glob("section-*/*.md"))


def test_course_structure():
    assert len(COURSE.sections) == 5
    for section in COURSE.sections:
        practices = [lesson for lesson in section.lessons if lesson.is_practice]
        assert 5 <= len(section.lessons) <= 7, section.title
        assert 2 <= len(practices) <= 3, section.title
        assert len(section.quiz) == 15, section.title
        assert not section.lessons[0].is_practice, "раздел начинается с теории"


def test_every_lesson_file_is_listed_in_course():
    listed = sum(len(section.lessons) for section in COURSE.sections)
    assert listed == len(PRACTICES) + len(LESSONS)


def test_quiz_questions_cover_several_lessons():
    for section in COURSE.sections:
        covered = {question.lesson_id for question in section.quiz}
        assert len(covered) >= 4, f"{section.title}: вопросы ссылаются только на {sorted(covered)}"
        multiple = sum(question.multiple for question in section.quiz)
        assert 2 <= multiple <= 6, f"{section.title}: вопросов с несколькими ответами {multiple}"


def test_theory_lessons_have_expected_length():
    for lesson in COURSE.lessons:
        if lesson.is_practice:
            continue
        prose = re.sub(r"<pre.*?</pre>", " ", lesson.html, flags=re.S)
        words = len(re.sub(r"<[^>]+>", " ", prose).split())
        assert 600 <= words <= 1300, f"{lesson.id}: {words} слов"


def test_lesson_images_exist():
    for lesson in COURSE.lessons:
        for src in re.findall(r'<img src="([^"]+)"', lesson.html):
            assert src.startswith("/static/"), src
            assert (ROOT / "app" / src.lstrip("/")).is_file(), f"{lesson.id}: нет файла {src}"
        assert 'alt=""' not in lesson.html, f"{lesson.id}: рисунок без описания"


def test_practice_datasets_and_packages_are_known():
    available = {path.name for path in (ROOT / "app" / "static" / "data").glob("*.csv")}
    allowed = {"pandas", "numpy", "scipy", "scikit-learn", "statsmodels", "matplotlib"}
    for lesson in COURSE.lessons:
        if lesson.is_practice:
            assert set(lesson.practice.datasets) <= available, lesson.id
            assert set(lesson.practice.packages) <= allowed, lesson.id
            assert lesson.practice.datasets, lesson.id


@pytest.mark.parametrize("path", PRACTICES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_reference_solution_passes_its_checks(path):
    result, verdicts = run_solution.run_solution(path)
    assert result["error"] is None, result["error"]
    failed = [f"{v.label}: {v.message}" for v in verdicts if not v.ok]
    assert not failed, failed


@pytest.mark.parametrize("path", PRACTICES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_starter_code_does_not_pass(path):
    """Заготовка не должна засчитываться: иначе задание можно сдать, ничего не написав."""
    import yaml

    task = yaml.safe_load(path.read_text(encoding="utf-8"))
    _, verdicts = run_solution.run_task(dict(task, solution=task["starter"]))
    assert not all(v.ok for v in verdicts)


def test_lesson_code_runs_and_outputs_are_current():
    stale = sync_lesson_outputs.sync(LESSONS, check=True)
    assert not stale, f"запустите python scripts/sync_lesson_outputs.py — устарели: {stale}"

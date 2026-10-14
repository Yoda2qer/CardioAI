"""Маленький учебный курс для тестов платформы: два раздела, три урока, два теста."""

from pathlib import Path

import yaml

PRACTICE = {
    "packages": [],
    "datasets": [],
    "statement": "Посчитайте сумму чисел от 1 до 10 и сохраните её в переменную `total`.",
    "starter": "total = ...\n",
    "solution": "total = sum(range(1, 11))\nratio = total / 4\n",
    "checks": [
        {"var": "total", "type": "equal", "expected": 55, "label": "Сумма", "hint": "Используйте sum и range."},
        {"var": "ratio", "type": "approx", "expected": 13.75, "tol": 0.01, "label": "Отношение"},
    ],
}


def _quiz(lesson_id: str) -> dict:
    questions = []
    for i in range(1, 16):
        multiple = i % 5 == 0
        questions.append(
            {
                "text": f"Вопрос {i}",
                "lesson": lesson_id,
                "explanation": f"Пояснение {i}",
                "options": [
                    {"text": "Верный вариант", "correct": True},
                    {"text": "Ещё один верный" if multiple else "Неверный вариант", "correct": multiple},
                    {"text": "Неверный вариант 2"},
                    {"text": "Неверный вариант 3"},
                ],
            }
        )
    return {"questions": questions}


def write_minicourse(root: Path) -> None:
    course = {
        "title": "Тестовый курс",
        "sections": [
            {
                "id": "a", "title": "Раздел А", "description": "Первый раздел", "dir": "a",
                "lessons": [
                    {"id": "a1", "type": "theory", "title": "Теория А1", "file": "a1.md", "minutes": 5},
                    {"id": "a2", "type": "practice", "title": "Практика А2", "file": "a2.yaml", "minutes": 10},
                ],
            },
            {
                "id": "b", "title": "Раздел Б", "description": "Второй раздел", "dir": "b",
                "lessons": [
                    {"id": "b1", "type": "theory", "title": "Теория Б1", "file": "b1.md", "minutes": 5},
                ],
            },
        ],
    }
    (root / "a").mkdir(parents=True, exist_ok=True)
    (root / "b").mkdir(parents=True, exist_ok=True)
    dump = lambda data: yaml.safe_dump(data, allow_unicode=True, sort_keys=False)  # noqa: E731
    (root / "course.yaml").write_text(dump(course), encoding="utf-8")
    (root / "a" / "a1.md").write_text(
        "## Заголовок\n\nТекст урока.\n\n::: clinic\nПример из практики.\n:::\n\n"
        "```python\nprint('привет')\n```\n",
        encoding="utf-8",
    )
    (root / "a" / "a2.yaml").write_text(dump(PRACTICE), encoding="utf-8")
    (root / "a" / "quiz.yaml").write_text(dump(_quiz("a1")), encoding="utf-8")
    (root / "b" / "b1.md").write_text("Текст второго раздела.\n", encoding="utf-8")
    (root / "b" / "quiz.yaml").write_text(dump(_quiz("b1")), encoding="utf-8")
